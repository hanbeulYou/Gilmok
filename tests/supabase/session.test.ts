import { expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import { createSessionLoader } from '../../lib/supabase/session';
it('shares signup, reuses existing session, and allows authentication retry', async () => {
  const session = { access_token: 'fixture' };
  const auth = { getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
    signInAnonymously: vi.fn().mockResolvedValue({ data: { session } }) };
  const ensure = createSessionLoader(() => ({ auth }) as unknown as SupabaseClient);
  expect(await Promise.all([ensure(), ensure()])).toEqual([session, session]);
  expect(auth.signInAnonymously).toHaveBeenCalledTimes(1);
  auth.getSession.mockResolvedValue({ data: { session } });
  await ensure(); expect(auth.signInAnonymously).toHaveBeenCalledTimes(1);
  auth.getSession.mockResolvedValueOnce({ data: {}, error: new Error('fail') });
  await expect(ensure()).rejects.toThrow('인증 정보를');
  expect(await ensure()).toEqual(session);
});
