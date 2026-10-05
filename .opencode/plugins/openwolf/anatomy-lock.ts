import { normalizeSession } from "./session-state.js";
export { normalizeSession } from "./session-state.js";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as crypto from "node:crypto";

// Cross-process mutual exclusion for anatomy writers (OPENWOLF-2.0 §F2b).
//
// Mechanism: lockfile created with the "wx" flag (atomic O_EXCL on macOS,
// Linux and Windows, no native deps). The file body records the owner for
// staleness detection. A stale lock (older than STALE_MS, or a dead pid on
// the same host) is stolen via rename-then-unlink: rename is atomic, so of N
// competing stealers exactly one wins and the rest keep waiting.
//
// Callers NEVER block the agent: on budget exhaustion withAnatomyLock returns
// null and the caller skips its update (the next writer converges the state).
// Self-contained on purpose: compiled standalone into the hooks bundle and
// imported directly by tests.

const LOCK_FILE = "anatomy-index.lock";
const STALE_MS = 10_000; // > hook timeout, so a killed hook's lock is reclaimable

export const HOOK_LOCK_BUDGET_MS = 2_000;
export const CLI_LOCK_BUDGET_MS = 5_000;

interface LockBody {
  pid: number;
  hostname: string;
  acquiredAt: number;
  nonce?: string;
}

/** Dependency-free synchronous sleep. */
function sleep(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function tryAcquire(lockPath: string): string | null {
  const nonce = crypto.randomBytes(16).toString("hex");
  try {
    const body: LockBody = { pid: process.pid, hostname: os.hostname(), acquiredAt: Date.now(), nonce };
    fs.writeFileSync(lockPath, JSON.stringify(body), { flag: "wx" });
    return nonce;
  } catch { return null; }
}

function isStale(lockPath: string): boolean {
  try {
    const body = JSON.parse(fs.readFileSync(lockPath, "utf-8")) as LockBody;
    // Age never grants permission to evict a live writer.
    if (body.hostname !== os.hostname() || !Number.isSafeInteger(body.pid) || body.pid <= 0) return false;
    try { process.kill(body.pid, 0); return false; }
    catch (err) { return (err as NodeJS.ErrnoException).code === "ESRCH"; }
  } catch {
    try { return Date.now() - fs.statSync(lockPath).mtimeMs > STALE_MS; }
    catch { return false; }
  }
}

function trySteal(lockPath: string): void {
  // Serialize reapers, then inspect AGAIN. A stale observation made before
  // another reaper ran must never rename a new owner's lock (#83).
  const reaper = lockPath + ".reap";
  let fd: number;
  try { fd = fs.openSync(reaper, "wx"); } catch { return; }
  try {
    if (isStale(lockPath)) {
      try { fs.unlinkSync(lockPath); } catch {}
    }
  } finally {
    fs.closeSync(fd);
    try { fs.unlinkSync(reaper); } catch {}
  }
}

/**
 * Run `fn` while holding the named lockfile. Returns fn's result, or null if
 * the lock could not be acquired within `budgetMs` (caller must degrade
 * gracefully — skip the update, never block). Same mechanism as the anatomy
 * lock; used for the other multi-writer JSON files (cron-state, token-ledger).
 */
export function acquireLock(lockPath: string, budgetMs: number): (() => void) | null {
  const deadline = Date.now() + budgetMs;
  let attempt = 0;
  let nonce: string | null = null;

  while (true) {
    nonce = tryAcquire(lockPath);
    if (nonce !== null) break;
    if (isStale(lockPath)) trySteal(lockPath);
    if (Date.now() >= deadline) return null;
    // Start tight, then back off. A contended session-state critical section
    // is 1-3 ms, so the old flat 25-50 ms poll meant a 60-way herd needed
    // roughly 2 s just to drain — precisely the hook budget, which made the
    // slowest few writers give up and skip their update under load. The
    // capped exponential keeps long holders (anatomy writes) from spinning.
    const base = Math.min(2 * 2 ** Math.min(attempt, 4), 32);
    sleep(base + Math.floor(Math.random() * base));
    attempt++;
  }

  return () => {
    try {
      const owner = JSON.parse(fs.readFileSync(lockPath, "utf8")) as LockBody;
      if (owner.nonce === nonce) fs.unlinkSync(lockPath);
    } catch {}
  }
}

export function withFileLock<T>(lockPath: string, budgetMs: number, fn: () => T): T | null {
  const release = acquireLock(lockPath, budgetMs);
  if (!release) return null;
  try { return fn(); } finally { release(); }
}

/**
 * Serialized read-modify-write against a shared JSON file.
 *
 * Issues #83, #84, #86 and #88, each reported with a fix by @davdittrich
 * (PRs #98, #109, #108, #105). This is the one helper those four sites share.
 *
 * Atomic writes (tmp + rename) prevent TORN files. They do not prevent LOST
 * UPDATES: two processes that each read, modify, and write independently both
 * produce a valid file, and the second one silently erases the first one's
 * change. Measured on real hooks: 60 concurrent post-read processes kept 26 of
 * 60 reads (#83); 60 concurrent registrations kept 43 of 60 projects (#88);
 * 60 concurrent SessionStart hooks counted 35 of 60 sessions (#84).
 *
 * The fix is not a better write, it is a serialized transaction. `mutate`
 * receives the CURRENT on-disk value, read inside the lock, and its result is
 * written before the lock is released. Never apply a delta to a snapshot read
 * before calling this.
 *
 * Returns the written value, or null if the lock could not be acquired within
 * `budgetMs` — callers must degrade, never block the agent. There is no
 * unlocked fallback on purpose: writing anyway on timeout defeats the lock for
 * every well-behaved writer (#86).
 */
export function mutateJSON<T>(
  filePath: string,
  fallback: T,
  budgetMs: number,
  mutate: (current: T) => T | void,
): T | null {
  // The lockfile lives next to the target, so its directory has to exist
  // BEFORE the first acquire attempt. Without this, a session file whose
  // directory has not been created yet can never take its own lock: every
  // tryAcquire fails with ENOENT, the whole budget is burned waiting, and the
  // update is skipped entirely.
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  } catch {}

  return withFileLock(filePath + ".lock", budgetMs, () => {
    let current: T;
    try {
      current = JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
    } catch {
      current = fallback;
    }
    if (/[/\\]hooks[/\\]sessions[/\\][^/\\]+\.json$/.test(filePath)) {
      current = normalizeSession(current, path.basename(filePath, ".json")) as T;
    }
    const returned = mutate(current);
    const next = returned === undefined ? current : (returned as T);
    writeJSONAtomic(filePath, next);
    return next;
  });
}

/** tmp + rename, with the Windows fallback used elsewhere in the codebase. */
function writeJSONAtomic(filePath: string, data: unknown): void {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const body = JSON.stringify(data, null, 2);
  const tmp = filePath + "." + crypto.randomBytes(4).toString("hex") + ".tmp";
  try {
    fs.writeFileSync(tmp, body, "utf-8");
    fs.renameSync(tmp, filePath);
  } catch {
    try { fs.unlinkSync(tmp); } catch {}
    throw new Error(`Atomic write failed: ${filePath}`);
  }
}

/**
 * Run `fn` while holding the anatomy lock. Returns fn's result, or null if
 * the lock could not be acquired within `budgetMs`.
 */
export function withAnatomyLock<T>(wolfDir: string, budgetMs: number, fn: () => T): T | null {
  return withFileLock(path.join(wolfDir, LOCK_FILE), budgetMs, fn);
}

/** Complete state at every ingress, including a missed SessionStart (#96 @davdittrich). */
