import * as fs from "node:fs";
import * as crypto from "node:crypto";
import * as path from "node:path";
import { readJSON, writeJSON, readTranscriptUsage, detectAgent } from "./shared.js";
import { withFileLock, HOOK_LOCK_BUDGET_MS } from "./anatomy-lock.js";
import {
  MAX_LEDGER_SESSIONS,
  emptyLedger,
  buildSessionTotals,
  numericFields,
  foldEntry,
  foldEntryMaps,
  emptyMaps,
  recomputeLifetime,
  type SessionData,
  type SessionEntry,
  type LedgerData,
} from "./ledger-math.js";

// ─────────────────────────────────────────────────────────────────────────────
// Token-ledger writer shared by the Stop and SessionEnd hooks.
//
// Stop fires at the end of EVERY turn, so the ledger write must be idempotent:
// the session entry is UPSERTED by session id (replaced, never appended), and
// lifetime totals are derived — archived baseline + fold over the retained
// sessions — rather than incremented. The old increment-on-every-Stop scheme
// re-added turns 1..N on turn N, quadratically inflating every lifetime metric
// and duplicating session entries.
//
// The pure math (folds, lifetime derivation, migrations) lives in
// ledger-math.ts; this module owns IO and session-entry assembly.
// ─────────────────────────────────────────────────────────────────────────────

export * from "./ledger-math.js";

/** Build the ledger entry for the current session state (idempotent). */
export function buildSessionEntry(session: SessionData, transcriptPath?: string): SessionEntry {
  const reads = Object.entries(session.files_read).map(([file, data]) => ({
    file,
    tokens_estimated: data.tokens,
    was_repeated: data.count > 1,
    anatomy_had_description: data.anatomy_hit === true,
  }));

  const writes = session.files_written.map((w) => ({
    file: w.file,
    tokens_estimated: w.tokens,
    action: w.action,
  }));

  const entry: SessionEntry = {
    id: session.session_id,
    agent: typeof session.agent === "string" ? session.agent : detectAgent(),
    started: session.started,
    ended: new Date().toISOString(),
    reads,
    writes,
    totals: buildSessionTotals(session, reads, writes),
  };

  if (session.injected_by_source && Object.keys(session.injected_by_source).length > 0) {
    entry.injected_by_source = { ...session.injected_by_source };
  }

  if (transcriptPath) {
    // readTranscriptUsage dedupes by message id, so this is the cumulative
    // total for the whole session — correct to REPLACE, never to add.
    const real = readTranscriptUsage(transcriptPath);
    if (real) entry.real_usage = real;
  }

  return entry;
}

/** Upsert the entry, roll old sessions into the baseline, derive lifetime. */
export function flushSessionToLedger(wolfDir: string, entry: SessionEntry): void {
  if (!entry.id) return;
  const pending = path.join(wolfDir,"ledger-pending");
  fs.mkdirSync(pending,{recursive:true});
  const file = path.join(pending,crypto.randomUUID()+".json");
  const fd = fs.openSync(file,"wx",0o600);
  try { fs.writeFileSync(fd,JSON.stringify(entry)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  reconcileLedger(wolfDir);
}

/** All per-session snapshots survive the 200-row UI window. A late resumed
 * session replaces its old snapshot instead of being added to baseline twice.
 */
export function reconcileLedger(wolfDir: string): boolean {
  const ledgerPath = path.join(wolfDir,"token-ledger.json");
  const pending = path.join(wolfDir,"ledger-pending");
  const snapshots = path.join(wolfDir,"ledger-sessions");
  fs.mkdirSync(snapshots,{recursive:true});
  const result = withFileLock(ledgerPath+".lock",HOOK_LOCK_BUDGET_MS,()=>{
    const read = <T>(file: string, fallback: T): T => {
      try {return JSON.parse(fs.readFileSync(file,"utf8"));} catch(e) {if ((e as NodeJS.ErrnoException).code === "ENOENT") return fallback; throw e;}
    };
    const ledger = read<LedgerData>(ledgerPath,emptyLedger());
    const baselineFile = path.join(wolfDir,"_legacy-ledger-baseline.json");
    const legacy = read(baselineFile,{totals:ledger.lifetime_baseline ?? {},maps:ledger.lifetime_baseline_maps ?? emptyMaps()});
    if (!fs.existsSync(baselineFile)) writeJSON(baselineFile,legacy);
    const key = (e: SessionEntry) => crypto.createHash("sha256").update(`${e.agent ?? 'claude'}:${e.id}`).digest("hex")+".json";
    for (const e of ledger.sessions ?? []) {
      if (!e?.id) continue;
      const dest = path.join(snapshots,key(e));
      if (!fs.existsSync(dest)) writeJSON(dest,e);
    }
    let names: string[] = [];
    try {names=fs.readdirSync(pending).filter(n=>n.endsWith(".json"));} catch {}
    for (const name of names) {
      const e = read<SessionEntry | null>(path.join(pending,name),null);
      if (!e?.id || !e.totals) throw new Error("Invalid pending ledger entry retained for review");
      const dest = path.join(snapshots,key(e));
      const previous = read<SessionEntry | null>(dest,null);
      if (!previous || e.ended >= previous.ended) writeJSON(dest,e);
    }
    const all = fs.readdirSync(snapshots).filter(n=>n.endsWith(".json")).map(n=>read<SessionEntry>(path.join(snapshots,n),null as any))
      .sort((a,b)=>a.started.localeCompare(b.started) || a.id.localeCompare(b.id));
    ledger.sessions = all.slice(-MAX_LEDGER_SESSIONS);
    const baseline = numericFields(legacy.totals);
    ledger.lifetime_baseline = baseline;
    ledger.lifetime_baseline_maps = structuredClone(legacy.maps);
    for (const old of all.slice(0,Math.max(0,all.length-MAX_LEDGER_SESSIONS))) {
      foldEntry(baseline,old);
      foldEntryMaps(ledger.lifetime_baseline_maps,old);
    }
    recomputeLifetime(ledger);
    writeJSON(ledgerPath,ledger);
    for (const name of names) {try {fs.unlinkSync(path.join(pending,name));} catch {}}
    return true;
  });
  return result === true;
}
