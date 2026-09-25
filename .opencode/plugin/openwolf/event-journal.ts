import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { mutateJSON, HOOK_LOCK_BUDGET_MS } from "./anatomy-lock.js";

export interface ReadObservation {
  id: string;
  file: string;
  at: string;
  tokens: number;
  fingerprint?: string;
  mtime?: number;
  internal?: boolean;
  kind?: "read" | "write";
  action?: string;
  editKey?: string;
}

/** One immutable event per file: no contended append, and no shared offset. */
export function persistRead(sessionFile: string, event: ReadObservation): void {
  const dir = sessionFile + ".events";
  fs.mkdirSync(dir, { recursive: true });
  const dest = path.join(dir, crypto.createHash("sha256").update(event.id).digest("hex") + ".json");
  const tmp = dest + "." + crypto.randomUUID() + ".tmp";
  try {
    const fd = fs.openSync(tmp, "wx", 0o600);
    try { fs.writeFileSync(fd, JSON.stringify(event)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    // A retry of the same upstream event cannot replace an already persisted event.
    try { fs.linkSync(tmp, dest); } catch (e) { if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e; }
  } finally { try { fs.unlinkSync(tmp); } catch {} }
}

export function reconcileReads(sessionFile: string, budget = HOOK_LOCK_BUDGET_MS): boolean {
  const dir = sessionFile + ".events";
  let names: string[];
  try { names = fs.readdirSync(dir).filter(n => n.endsWith(".json")); } catch { return true; }
  if (!names.length) return true;
  const done: string[] = [];
  const result = mutateJSON<Record<string, any>>(sessionFile, { files_read: {} }, budget, s => {
    s.applied_read_events ??= {};
    s.files_read ??= {};
    const events = names.flatMap(name => {
      try { return [{ name, event: JSON.parse(fs.readFileSync(path.join(dir, name), "utf8")) as ReadObservation }]; }
      catch (e) { if ((e as NodeJS.ErrnoException).code === "ENOENT") return []; throw e; }
    }).sort((a,b) => a.event.at.localeCompare(b.event.at));
    for (const { name, event: e } of events) {
      if (!s.applied_read_events[e.id]) {
        if (e.kind === "write") {
          s.files_written ??= [];
          s.edit_counts ??= {};
          s.files_written.push({file:e.file,action:e.action ?? "edit",tokens:e.tokens,at:e.at});
          const key=e.editKey ?? e.file;
          s.edit_counts[key]=(s.edit_counts[key] ?? 0)+1;
          delete s.files_read[e.file];
        } else if (e.internal) {
          s.wolf_internal_tokens = (s.wolf_internal_tokens ?? 0) + e.tokens;
          s.wolf_internal_reads ??= {};
          s.wolf_internal_reads[e.file] = (s.wolf_internal_reads[e.file] ?? 0) + e.tokens;
        } else {
          const previous = s.files_read[e.file];
          if (!previous?.observed_at || previous.observed_at <= e.at) {
            s.files_read[e.file] = { ...previous, count: previous?.count ?? 1, tokens: e.tokens, first_read: previous?.first_read ?? e.at, observed_at: e.at, ranged: false, read_hash: e.fingerprint, read_mtime: e.mtime };
          }
        }
        s.applied_read_events[e.id] = true;
      }
      done.push(name);
    }
  });
  if (result === null) return false;
  // Receipts remain in the state, so a crash between commit and unlink is safe.
  for (const name of done) { try { fs.unlinkSync(path.join(dir, name)); } catch {} }
  return true;
}

export const persistObservation = persistRead;
