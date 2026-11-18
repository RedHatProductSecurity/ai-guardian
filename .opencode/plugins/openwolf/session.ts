import * as fs from "node:fs"
import * as path from "node:path"
import { getWolfDir, writeJSON, readJSON, appendMarkdown, timeShort, timestamp, readMarkdown, sessionFilePath, gcSessionFiles } from "./fs.js"
import type { SessionState } from "./types.js"

const sessions = new Map<string, SessionState>()

export function getSessionState(sessionId: string): SessionState | undefined {
  return sessions.get(sessionId)
}

export function setSessionState(sessionId: string, state: SessionState): void {
  sessions.set(sessionId, state)
}

export function deleteSession(sessionId: string): void {
  sessions.delete(sessionId)
}

export function handleSessionStart(directory: string, sessionId: string): void {
  const wolfDir = getWolfDir(directory)
  if (!fs.existsSync(wolfDir)) return

  const hooksDir = path.join(wolfDir, "hooks")
  fs.mkdirSync(hooksDir, { recursive: true })

  gcSessionFiles(hooksDir)

  const sessionFile = sessionFilePath(hooksDir, sessionId)
  const existing = readJSON<SessionState | null>(sessionFile, null)
  if (existing?.session_id === sessionId) { sessions.set(sessionId, existing); return }
  const state: SessionState = {
    session_id: sessionId,
    started: timestamp(),
    files_read: {},
    files_written: [],
    edit_counts: {},
    anatomy_hits: 0,
    anatomy_misses: 0,
    repeated_reads_warned: 0,
    cerebrum_warnings: 0,
    stop_count: 0,
  }
  sessions.set(sessionId, state)
  writeJSON(sessionFile, state)

  const memoryPath = path.join(wolfDir, "memory.md")
  const now = new Date()
  const header = `\n## Session: ${now.toISOString().slice(0, 10)} ${timeShort()}\n\n| Time | Action | File(s) | Outcome | ~Tokens |\n|------|--------|---------|---------|--------|\n`
  appendMarkdown(memoryPath, header)

  // Count the new session in the lifetime totals. readJSON deep-merges the
  // fallback, so a pre-2.0 ledger without `lifetime` still gets the default;
  // the guard below covers a ledger where `lifetime` is not an object at all.
  const ledgerPath = path.join(wolfDir, "token-ledger.json")
  const ledger = readJSON<Record<string, unknown>>(ledgerPath, { version: 1, lifetime: { total_sessions: 0 } }) as {
    version: number
    lifetime: { total_sessions: number }
    [key: string]: unknown
  }
  if (!ledger.lifetime || typeof ledger.lifetime !== "object") {
    ledger.lifetime = { total_sessions: 0 }
  }
  if (typeof ledger.lifetime.total_sessions !== "number" || !isFinite(ledger.lifetime.total_sessions)) {
    ledger.lifetime.total_sessions = 0
  }
  ledger.lifetime.total_sessions++
  writeJSON(ledgerPath, ledger)
}