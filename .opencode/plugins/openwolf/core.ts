import {activityState} from './visibility.js'
import {scheduleUpdate, updateNotice} from "./runtime-updates.js"
import { mutateJSON, HOOK_LOCK_BUDGET_MS } from "./anatomy-lock.js"
import {readJSON,sessionFilePath} from "./fs.js"
import { recordUsage } from "./usage.js"
import { approvedMemory } from "./trusted-memory.js"
import * as fs from "node:fs"
import * as path from "node:path"

import { wolfDirExists, getWolfDir } from "./fs.js"
import { handleSessionStart, deleteSession } from "./session.js"
import { handlePreRead } from "./pre-read.js"
import { handlePreWrite } from "./pre-write.js"
import { handlePostRead } from "./post-read.js"
import { handlePostWrite } from "./post-write.js"
import { handleStop } from "./stop.js"

export type OpenCodeEvent = { type?: unknown; [key: string]: unknown }

export interface OpenCodeEventOptions {
  beforeStop?: (sessionId: string) => Promise<void> | void
  toast?: (message: string) => void
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function eventData(event: OpenCodeEvent): Record<string, unknown> {
  const data = record(event.data)
  if (Object.keys(data).length > 0) return data
  return record(event.properties)
}

/**
 * OpenCode event payloads have changed shape between plugin generations. V1
 * uses top-level/properties fields; V2 uses a durable `data` envelope. Keep
 * the integration tolerant so the filesystem handlers stay version-neutral.
 */
export function extractSessionId(source: unknown): string {
  const obj = record(source)
  const properties = record(obj.properties)
  const data = record(obj.data)
  const propertyInfo = record(properties.info)
  const dataInfo = record(data.info)
  const candidates = [
    obj.session_id,
    obj.sessionID,
    obj.sessionId,
    properties.session_id,
    properties.sessionID,
    properties.sessionId,
    propertyInfo.id,
    propertyInfo.session_id,
    propertyInfo.sessionID,
    data.session_id,
    data.sessionID,
    data.sessionId,
    dataInfo.id,
    dataInfo.session_id,
    dataInfo.sessionID,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate) return candidate
  }
  return ""
}

function eventType(event: OpenCodeEvent): string {
  return typeof event.type === "string" ? event.type : ""
}

// OpenCode 2 can deliver more than one turn-end event for one turn
// (session.execution.succeeded plus session.idle), so remember sessions that
// already stopped since their last observed activity.
const stoppedSinceActivity = new Set<string>()

// OpenCode 2's session.usage.updated carries CUMULATIVE session totals, so
// per-message usage must come from the per-step events instead. The model is
// only reported on session.step.started, so it is remembered by assistant
// message id until the matching session.step.ended (or failed) arrives.
const stepModels = new Map<string, { providerID?: string; modelID?: string; sessionID: string }>()

// OpenCode 2 does not deliver session.created for a session that already
// existed when the plugin subscribed, so the session file is created lazily,
// once, on the first event or tool call that names the session.
const startedSessions = new Set<string>()

function ensureSession(directory: string, sessionId: string): void {
  if (!wolfDirExists(directory) || startedSessions.has(path.resolve(directory)+":"+sessionId)) return
  startedSessions.add(path.resolve(directory)+":"+sessionId)
  handleSessionStart(directory, sessionId)
}

export async function handleOpenCodeEvent(
  directory: string,
  event: OpenCodeEvent,
  options: OpenCodeEventOptions = {},
): Promise<void> {
  const type = eventType(event)
  if (type === "session.created" && !wolfDirExists(directory)) return

  if (!wolfDirExists(directory)) return
  if (type === "message.updated") {
    const info = record(eventData(event).info)
    if (Object.keys(info).length > 0) {
      try { recordUsage(directory, info) } catch (error) { console.warn(String(error)) }
    }
  }

  const sessionId = extractSessionId(event)
  if (!sessionId) return

  // Any event that names the session is activity for the turn-end dedupe.
  if (type === "session.created" || type === "message.updated" || type === "session.step.started") {
    stoppedSinceActivity.delete(path.resolve(directory)+":"+sessionId)
  }

  // Lazily create the session for v2 sessions that never got
  // session.created; deletion drops the lazy-start marker instead.
  if (type === "session.deleted") {
    startedSessions.delete(path.resolve(directory)+":"+sessionId)
  } else {
    ensureSession(directory, sessionId)
  }

  if (type === "session.step.started") {
    const data = eventData(event)
    const messageID = typeof data.assistantMessageID === "string" ? data.assistantMessageID : ""
    const model = record(data.model)
    if (messageID) {
      stepModels.set(path.resolve(directory)+":"+messageID, {
        providerID: typeof model.providerID === "string" ? model.providerID : undefined,
        modelID: typeof model.id === "string" ? model.id : undefined,
        sessionID: typeof data.sessionID === "string" ? data.sessionID : sessionId,
      })
    }
  }

  // A failed step (e.g. content filter, stream cut off) may still report the
  // tokens the provider billed, with the same shape as step.ended.
  if (type === "session.step.ended" || type === "session.step.failed") {
    const data = eventData(event)
    const messageID = typeof data.assistantMessageID === "string" ? data.assistantMessageID : ""
    const step = messageID ? stepModels.get(path.resolve(directory)+":"+messageID) : undefined
    stepModels.delete(path.resolve(directory)+":"+messageID)
    if (messageID && data.tokens) {
      try {
        recordUsage(directory, {
          // id = assistantMessageID keeps a redelivered step.ended idempotent.
          id: messageID,
          role: "assistant",
          sessionID: typeof data.sessionID === "string" ? data.sessionID : (step?.sessionID ?? sessionId),
          providerID: step?.providerID,
          modelID: step?.modelID,
          tokens: data.tokens,
          time: { created: event.created, completed: event.created },
        })
      } catch (error) {
        console.warn(String(error))
      }
    }
  }

  // Title generation and compaction run outside the step events and report
  // their usage once each (not cumulative); the event id keeps redelivery
  // idempotent. The event carries no model, so it is recorded as unknown.
  if (type === "session.usage.recorded") {
    const data = eventData(event)
    if (typeof event.id === "string" && data.tokens) {
      try {
        recordUsage(directory, {
          id: `usage:${event.id}`,
          role: "assistant",
          sessionID: sessionId,
          tokens: data.tokens,
          time: { created: event.created, completed: event.created },
        })
      } catch (error) {
        console.warn(String(error))
      }
    }
  }

  if (type === "session.created") {
    ensureSession(directory, sessionId)
    scheduleUpdate(directory)
    const notice = updateNotice(directory, sessionId)
    if (notice) options.toast?.(notice)
  }

  // OpenCode 2.0.32 ends a successful turn with
  // session.execution.succeeded and never delivered session.idle in tests,
  // so both end the turn; the dedupe below keeps a turn from stopping twice
  // if both fire (v1's idle-only turns still stop exactly once).
  const ended = type === "session.idle" ||
    type === "session.error" ||
    type === "session.deleted" ||
    type === "session.execution.succeeded" ||
    type === "session.execution.failed" ||
    type === "session.execution.interrupted"
  if (!ended) return

  if (type !== "session.deleted" && stoppedSinceActivity.has(path.resolve(directory)+":"+sessionId)) return

  scheduleUpdate(directory)
  const update = updateNotice(directory, sessionId)
  const activity = update ?? activityState(
    directory,
    {
      agent: "opencode",
      session: sessionId,
      turn: String(readJSON<Record<string, unknown>>(
        sessionFilePath(pathForHooks(directory), sessionId),
        {},
      ).stop_count ?? 0),
      surface: "opencode-toast",
    },
  ).message
  if (activity) options.toast?.(activity)

  try {
    await options.beforeStop?.(sessionId)
  } catch {
    // Reconciliation is advisory; it must never prevent the session ledger
    // from being flushed at its normal stop boundary.
  }
  handleStop(directory, sessionId)

  // A finished turn owns no in-flight steps; drop any model info still
  // keyed to this session.
  for (const [messageID, step] of stepModels) {
    if (messageID.startsWith(path.resolve(directory)+":") && step.sessionID === sessionId) stepModels.delete(messageID)
  }

  if (type === "session.deleted") {
    const file = sessionFilePath(pathForHooks(directory), sessionId)
    mutateJSON<Record<string, unknown>>(
      file,
      {},
      HOOK_LOCK_BUDGET_MS,
      state => { state.ended = new Date().toISOString() },
    )
    deleteSession(sessionId)
    stoppedSinceActivity.delete(path.resolve(directory)+":"+sessionId)
  } else {
    stoppedSinceActivity.add(path.resolve(directory)+":"+sessionId)
  }
}

function pathForHooks(directory: string): string {
  return path.join(getWolfDir(directory), "hooks")
}

function toolArgs(value: unknown): Record<string, unknown> {
  return record(value)
}

export function handleOpenCodeToolBefore(
  directory: string,
  sessionId: string,
  toolName: unknown,
  input: unknown,
): void {
  if (!wolfDirExists(directory) || !sessionId || typeof toolName !== "string") return

  // v2: tool calls are activity and can arrive before any session event, so
  // lazily start the session and clear the turn-end dedupe.
  ensureSession(directory, sessionId)
  stoppedSinceActivity.delete(path.resolve(directory)+":"+sessionId)

  const args = toolArgs(input)
  const tool = toolName.toLowerCase()
  if (tool === "read") {
    // OpenCode 2 tool input names the file "path" (v1 used "filePath").
    const filePath = String(args.path || args.filePath || args.file_path || "")
    const ranged = args.offset !== undefined || args.limit !== undefined
    if (filePath) handlePreRead(directory, sessionId, filePath, ranged)
  }

  if (tool === "write" || tool === "edit") {
    // OpenCode 2 tool input names the file "path" (v1 used "filePath").
    const filePath = String(args.path || args.filePath || args.file_path || "")
    const content = String(args.content || "")
    const oldStr = String(args.old_string || args.oldString || "")
    const newStr = String(args.new_string || args.newString || "")
    if (filePath) handlePreWrite(directory, sessionId, filePath, content, oldStr, newStr)
  }
}

function contentText(value: unknown): string {
  if (typeof value === "string") return value
  if (!value || typeof value !== "object") return value === undefined ? "" : String(value)
  const object = value as Record<string, unknown>
  if (typeof object.output === "string") return object.output
  // OpenCode 2 read results carry the raw file text in output.content; the
  // content[] text parts add a header and line-number prefixes.
  const output = record(object.output)
  if (typeof output.content === "string") return output.content
  if (typeof object.text === "string") return object.text
  if (Array.isArray(object.content)) {
    return object.content
      .map(part => {
        const item = record(part)
        return typeof item.text === "string" ? item.text : ""
      })
      .filter(Boolean)
      .join("\n")
  }
  return JSON.stringify(value) || ""
}

export function handleOpenCodeToolAfter(
  directory: string,
  sessionId: string,
  toolName: unknown,
  input: unknown,
  result: unknown,
  callId?: string,
): void {
  if (!wolfDirExists(directory) || !sessionId || typeof toolName !== "string") return

  // v2: tool results are activity and can arrive before any session event,
  // so lazily start the session and clear the turn-end dedupe.
  ensureSession(directory, sessionId)
  stoppedSinceActivity.delete(path.resolve(directory)+":"+sessionId)

  const args = toolArgs(input)
  const tool = toolName.toLowerCase()
  if (tool === "read") {
    // OpenCode 2 tool input names the file "path" (v1 used "filePath").
    const filePath = String(args.path || args.filePath || args.file_path || "")
    const ranged = args.offset !== undefined || args.limit !== undefined
    if (filePath) handlePostRead(directory, sessionId, filePath, contentText(result), ranged, callId)
  }

  if (tool === "write" || tool === "edit") {
    // OpenCode 2 tool input names the file "path" (v1 used "filePath").
    const filePath = String(args.path || args.filePath || args.file_path || "")
    const content = String(args.content || "")
    const oldStr = String(args.old_string || args.oldString || "")
    const newStr = String(args.new_string || args.newString || "")
    if (filePath) handlePostWrite(directory, sessionId, toolName, filePath, content, oldStr, newStr)
  }
}

export function handleOpenCodeStop(directory: string, source: unknown): void {
  if (!wolfDirExists(directory)) return
  const sessionId = extractSessionId(source)
  if (sessionId) handleStop(directory, sessionId)
}

export function openWolfSystemText(directory: string): string | undefined {
  if (!wolfDirExists(directory)) return
  const openwolfPath = path.join(getWolfDir(directory), "OPENWOLF.md")
  try {
    if (!fs.existsSync(openwolfPath)) return
    const openwolfContent = approvedMemory(getWolfDir(directory), "OPENWOLF.md")
    return `\n<openwolf-protocol>\n${openwolfContent}\n</openwolf-protocol>`
  } catch {}
}
