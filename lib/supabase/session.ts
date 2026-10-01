import type { Session, SupabaseClient } from '@supabase/supabase-js';
import { getSupabaseClient } from './client';

/** Shared in-flight promise prevents Strict Mode and simultaneous forms signing up twice. */
export function createSessionLoader(getClient: () => SupabaseClient) {
  let pending: Promise<Session> | undefined;
  return () => {
    if (!pending) pending = (async () => {
      const client = getClient();
      const existing = await client.auth.getSession();
      if (existing.error) throw new Error('인증 정보를 확인하지 못했습니다. 다시 시도해 주세요.');
      if (existing.data.session) return existing.data.session;
      const created = await client.auth.signInAnonymously();
      if (created.error || !created.data.session) throw new Error('익명 로그인을 완료하지 못했습니다. 다시 시도해 주세요.');
      return created.data.session;
    })().finally(() => { pending = undefined; });
    return pending;
  };
}
export const ensureSession = createSessionLoader(getSupabaseClient);
