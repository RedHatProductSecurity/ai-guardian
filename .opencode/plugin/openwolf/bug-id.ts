/** PR #69 @liveoakwag, extended with a persisted high-water mark.
 * Caller MUST hold buglog.json.lock while allocating and persisting.
 */
export function nextBugId(log: { bugs: Array<{ id?: unknown }>; next_id?: number }): string {
  let next = Number.isSafeInteger(log.next_id) && log.next_id! > 0 ? log.next_id! : 1;
  for (const bug of log.bugs) {
    const match = /^bug-(\d+)$/.exec(String(bug?.id ?? ""));
    if (match && Number.isSafeInteger(Number(match[1]))) next = Math.max(next, Number(match[1]) + 1);
  }
  if (!Number.isSafeInteger(next + 1)) throw new Error("Bug ID space exhausted");
  log.next_id = next + 1;
  return `bug-${String(next).padStart(3, "0")}`;
}
