import {wolfDirExists} from "./fs.js"
import { pathToFileURL } from "node:url"
import * as path from "node:path"
import { pinRuntime, scheduleUpdate } from "./runtime-updates.js"
import {
  extractSessionId,
  handleOpenCodeEvent,
  handleOpenCodeToolAfter,
  handleOpenCodeToolBefore,
  openWolfSystemText,
} from "./core.js"

type V2SystemPart = { type: "text"; text: string }
type V2ToolBeforeEvent = {
  readonly tool: string
  readonly sessionID: string
  input: unknown
}
type V2ToolAfterEvent = {
  readonly tool: string
  readonly sessionID: string
  readonly id: string
  readonly input: unknown
  readonly status: "completed" | "error"
  readonly result?: unknown
  readonly error?: { message: string }
}
type V2ContextEvent = { system: V2SystemPart[] }
type V2Context = {
  location: { directory: string }
  event: {
    subscribe(options?: { signal?: AbortSignal }): AsyncIterable<unknown>
  }
  tool: {
    hook(name: "execute.before", callback: (event: V2ToolBeforeEvent) => void): Promise<unknown>
    hook(name: "execute.after", callback: (event: V2ToolAfterEvent) => void): Promise<unknown>
  }
  session: {
    hook(name: "context", callback: (event: V2ContextEvent) => void): Promise<unknown>
  }
}
type V2Plugin = {
  id: string
  setup(context: V2Context): Promise<(() => void) | void> | (() => void) | void
}

/**
 * Wait out a resubscribe backoff. The timer is unref'd so it cannot keep the
 * process alive, and the wait resolves immediately when the plugin aborts.
 */
function waitWithBackoff(signal: AbortSignal, ms: number): Promise<void> {
  return new Promise(resolve => {
    const timer = setTimeout(() => {signal.removeEventListener("abort", onAbort);resolve()}, ms)
    const timeout = timer as { unref?: () => void }
    if (typeof timeout.unref === "function") timeout.unref()
    const onAbort = () => {
      clearTimeout(timer)
      resolve()
    }
    if (signal.aborted) {
      onAbort()
      return
    }
    signal.addEventListener("abort", onAbort, { once: true })
  })
}

/**
 * The installed entrypoint owns runtime selection. A staged release imports
 * this function directly so it can replace only the implementation while the
 * current OpenCode plugin instance remains pinned for its lifetime.
 */
export async function setupOpenWolfV2(ctx: V2Context): Promise<(() => void) | void> {
  const directory = ctx.location.directory
  if (!wolfDirExists(directory)) return () => {}
  const sessionKey = `opencode-server:${process.pid}:${Date.now()}`
  scheduleUpdate(directory)

  let pkg: string | undefined
  try {
    pkg = pinRuntime(directory, sessionKey)
  } catch {}
  if (pkg) {
    try {
      const next = await import(
        pathToFileURL(path.join(pkg, "src/templates/opencode-plugin/index-v2.ts")).href,
      )
      if (typeof next.setupOpenWolfV2 === "function" && next.setupOpenWolfV2 !== setupOpenWolfV2) {
        return await next.setupOpenWolfV2(ctx)
      }
    } catch {
      // Retain the installed plugin if the staged module cannot load.
    }
  }

  const controller = new AbortController()
  // OpenCode 2's event subscription can fail or end at any time, after which
  // no further events arrive unless we subscribe again; retry with capped
  // exponential backoff (reset by any received event) until teardown.
  void (async () => {
    let backoffMs = 500
    while (!controller.signal.aborted) {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          backoffMs = 500
          await handleOpenCodeEvent(directory, event as unknown as Record<string, unknown>)
        }
      } catch {
        // A failed or closed stream is retried by the loop below.
      }
      if (controller.signal.aborted) return
      console.warn(`OpenWolf: event stream ended; resubscribing in ${backoffMs}ms`)
      await waitWithBackoff(controller.signal, backoffMs)
      backoffMs = Math.min(backoffMs * 2, 30000)
    }
  })()

  // A throw inside a hook would fail the agent's tool call; tracking must not.
  await ctx.tool.hook("execute.before", event => {
    try {
      handleOpenCodeToolBefore(directory, extractSessionId(event), event.tool, event.input)
    } catch (error) {
      console.warn(`OpenWolf: execute.before: ${error}`)
    }
  })

  await ctx.tool.hook("execute.after", event => {
    try {
      // A failed tool call changed nothing; recording it would log edits
      // that never happened (e.g. an edit whose oldString was not found).
      if (event.status !== "completed") return
      handleOpenCodeToolAfter(
        directory,
        extractSessionId(event),
        event.tool,
        event.input,
        event.result,
        event.id,
      )
    } catch (error) {
      console.warn(`OpenWolf: execute.after: ${error}`)
    }
  })

  await ctx.session.hook("context", event => {
    try {
      const text = openWolfSystemText(directory)
      if (text) event.system.push({ type: "text", text })
    } catch (error) {
      console.warn(`OpenWolf: context: ${error}`)
    }
  })

  return () => controller.abort()
}

// OpenCode validates this default shape. The official Plugin.define helper is
// an identity wrapper; keeping the generated local plugin dependency-free
// avoids requiring users to add a second .opencode package manifest.
const plugin: V2Plugin = {
  id: "openwolf",
  setup: setupOpenWolfV2,
}

export default plugin
