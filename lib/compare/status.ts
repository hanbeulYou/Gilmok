export const lookupStatuses = ['pending', 'processing', 'ready', 'not_found', 'ambiguous', 'failed'] as const;
export type LookupStatus = typeof lookupStatuses[number];
export interface LookupState { request_id: string; status: LookupStatus; updated_at: string }
export const isWaiting = (status?: string) => status === 'pending' || status === 'processing';
export const isTerminal = (status: LookupStatus) => !isWaiting(status);
/** Keep Postgres microseconds: Date.parse alone loses ordering within one millisecond. */
export function timestamp(value: string): bigint | null {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return null;
  const fraction = /\.(\d+)/.exec(value)?.[1] ?? '';
  return BigInt(Math.floor(ms / 1000)) * 1_000_000n + BigInt(fraction.slice(0, 6).padEnd(6, '0'));
}
export function lookupState(value: unknown): LookupState | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (typeof v.request_id !== 'string' || typeof v.updated_at !== 'string'
    || !lookupStatuses.includes(v.status as LookupStatus) || timestamp(v.updated_at) === null) return null;
  return { request_id: v.request_id, status: v.status as LookupStatus, updated_at: v.updated_at };
}
export function newer(next: LookupState, previous?: LookupState): boolean {
  return !previous || timestamp(next.updated_at)! > timestamp(previous.updated_at)!;
}
export function delayed(since: number | undefined, now: number): boolean {
  return since !== undefined && now - since >= 180_000;
}
