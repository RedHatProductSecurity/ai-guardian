import { withFileLock, HOOK_LOCK_BUDGET_MS } from "./anatomy-lock.js"
import * as fs from "node:fs"
import * as path from "node:path"
import * as crypto from "node:crypto"

/** Persist only usage metadata; never transcript text or private reasoning. */
export function recordUsage(directory: string, info: any): void {
  if (info?.role !== "assistant" || !info.tokens || !info.id || !info.sessionID) return
  const dir = path.join(directory, ".wolf", "usage", "opencode")
  fs.mkdirSync(dir, { recursive: true })
  const id = crypto.createHash("sha256").update(`${info.sessionID}:${info.id}`).digest("hex")
  const file = path.join(dir, id + ".json")
  const tmp = file + "." + crypto.randomUUID() + ".tmp"
  const message = { id: info.id, sessionID: info.sessionID, role: info.role, providerID: info.providerID, modelID: info.modelID, tokens: info.tokens, time: info.time }
  const committed = withFileLock(file + ".lock", HOOK_LOCK_BUDGET_MS, () => {
    try {
      const previous = JSON.parse(fs.readFileSync(file,"utf8"))?.message
      if (previous?.time?.completed && !info.time?.completed) return true
      if ((previous?.time?.completed ?? 0) > (info.time?.completed ?? 0)) return true
    } catch {}
  try {
    const fd = fs.openSync(tmp, "wx", 0o600)
    try { fs.writeFileSync(fd, JSON.stringify({ version: 1, directory, message })); fs.fsyncSync(fd) } finally { fs.closeSync(fd) }
    fs.renameSync(tmp, file)
  } finally { try { fs.unlinkSync(tmp) } catch {} }
    return true
  })
  if (!committed) throw new Error("OpenCode usage busy; session reconciliation will retry")
}

/** Read-only SDK backfill recovers usage from before plugin installation. */
export async function reconcileOpenCode(directory: string, client: any, sessionId?: string): Promise<void> {
  const unwrap = (response: any) => response?.data ?? response;
  const sessions = sessionId ? [unwrap(await client.session.get({path:{id:sessionId}}))] : unwrap(await client.session.list({query:{directory}}));
  if (!Array.isArray(sessions)) throw new Error("Unsupported OpenCode session list response");
  for (const session of sessions) {
    if (typeof session?.id !== "string" || typeof session.directory !== "string" || path.resolve(session.directory) !== path.resolve(directory)) continue;
    const messages = unwrap(await client.session.messages({path:{id:session.id},query:{directory}}));
    if (!Array.isArray(messages)) throw new Error("Unsupported OpenCode messages response");
    for (const message of messages) recordUsage(directory,message.info);
  }
}
