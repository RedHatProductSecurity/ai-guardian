import { persistRead, reconcileReads } from "./event-journal.js"
import * as crypto from "node:crypto"
import * as fs from "node:fs"
import * as path from "node:path"
import { getWolfDir, writeJSON, readJSON, normalizePath, estimateTokens, sessionFilePath } from "./fs.js"
import { lookupEntry } from "./anatomy.js"
import type { PartialSessionState } from "./types.js"

export function handlePostRead(directory: string, sessionId: string, filePath: string, content: string, ranged = false, observationId?: string): void {
  if (ranged) return
  filePath=path.resolve(directory,filePath)
  const wolfDir = getWolfDir(directory)
  if (!fs.existsSync(wolfDir)) return

  const hooksDir = path.join(wolfDir, "hooks")
  const sessionFile = sessionFilePath(hooksDir, sessionId)
  const normalizedFile = normalizePath(filePath)

  const projectDir = normalizePath(directory)
  const rel=path.relative(directory,filePath)
  if (!rel || rel==='..' || rel.startsWith('..'+path.sep) || path.isAbsolute(rel) || rel.split(path.sep)[0]==='.wolf') return

  const ext = path.extname(filePath).toLowerCase()
  const codeExts = new Set([".ts", ".js", ".tsx", ".jsx", ".py", ".rs", ".go", ".java", ".c", ".cpp", ".css", ".json", ".yaml", ".yml"])
  const proseExts = new Set([".md", ".txt", ".rst"])
  const type = codeExts.has(ext) ? "code" : proseExts.has(ext) ? "prose" : "mixed"

  let tokens = content ? estimateTokens(content, type as "code" | "prose" | "mixed") : 0

  // Fallback: if the tool output had no content, use the anatomy token estimate
  if (tokens === 0) {
    const entry = lookupEntry(wolfDir, projectDir, normalizedFile)
    if (entry) tokens = entry.tokens
  }

  let fingerprint: string | undefined
  let mtime=0
  try {const current=fs.readFileSync(filePath,"utf8");if(current===content){fingerprint=crypto.createHash("sha256").update(current).digest("hex");mtime=fs.statSync(filePath).mtimeMs}}catch{}
  persistRead(sessionFile,{id:observationId ?? crypto.randomUUID(),file:normalizedFile,at:new Date().toISOString(),tokens,fingerprint,mtime})
  reconcileReads(sessionFile)
}
