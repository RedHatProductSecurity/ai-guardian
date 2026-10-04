// OpenWolf plugin entry — implementation lives in ./openwolf/.
import {OpenWolf as installed} from "./openwolf/index.js"
import {pinRuntime, scheduleUpdate} from "./openwolf/runtime-updates.js"
import {pathToFileURL} from "node:url"
import * as path from "node:path"
import type {Plugin} from "@opencode-ai/plugin"
export const OpenWolf: Plugin = async (ctx) => {
  scheduleUpdate(ctx.directory)
  // The server's plugin instance remains fixed; no reload during a session.
  let pkg: string | undefined
  try { pkg = pinRuntime(ctx.directory, "opencode-server:" + process.pid + ":" + Date.now()) } catch {}
  if (pkg) {
    try {
      const next = await import(pathToFileURL(path.join(pkg,"src/templates/opencode-plugin/index.ts")).href)
      return await next.OpenWolf(ctx)
    } catch {} // retain the installed plugin if the staged module cannot load
  }
  return installed(ctx)
}
