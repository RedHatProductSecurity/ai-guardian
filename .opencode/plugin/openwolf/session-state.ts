/** Complete state at every ingress, including a missed SessionStart (#96 @davdittrich). */
export function normalizeSession(value: unknown, id: string, now = new Date().toISOString()): Record<string, any> {
  const s: Record<string, any> = value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
  s.session_id = id;
  if (typeof s.started !== "string" || !Number.isFinite(Date.parse(s.started))) s.started = now;
  for (const key of ["files_read", "edit_counts", "reminders_sent", "injected_by_source"]) {
    if (!s[key] || typeof s[key] !== "object" || Array.isArray(s[key])) s[key] = {};
  }
  for (const key of ["files_written", "pending_reminders"]) if (!Array.isArray(s[key])) s[key] = [];
  for (const key of ["anatomy_hits", "anatomy_misses", "repeated_reads_warned", "stop_count", "cerebrum_warnings"]) {
    if (!Number.isSafeInteger(s[key]) || s[key] < 0) s[key] = 0;
  }
  for (const [file, r] of Object.entries(s.files_read) as Array<[string, any]>) {
    if (!r || typeof r !== "object") { delete s.files_read[file]; continue; }
    r.count = Number.isSafeInteger(r.count) && r.count >= 0 ? r.count : 0;
    r.tokens = Number.isFinite(r.tokens) && r.tokens >= 0 ? r.tokens : 0;
  }
  s.files_written = s.files_written.filter((w: any) => w && typeof w.file === "string").map((w: any) => ({ ...w, tokens: Number.isFinite(w.tokens) && w.tokens >= 0 ? w.tokens : 0 }));
  return s;
}
