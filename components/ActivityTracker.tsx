'use client';
import { useEffect } from 'react';
import { getSupabaseClient } from '../lib/supabase/client';
import { ensureSession } from '../lib/supabase/session';

/** Token refresh and hidden tabs do not extend retention. */
export function ActivityTracker() {
  useEffect(() => {
    let active = true, running = false;
    async function touch() {
      if (!active || running || document.visibilityState !== 'visible') return;
      running = true;
      try { await ensureSession(); if (active) await getSupabaseClient().rpc('touch_user_activity'); }
      catch { /* Existing authentication UI owns retry. */ }
      finally { running = false; }
    }
    void touch();
    const foreground = () => { if (document.visibilityState === 'visible') void touch(); };
    document.addEventListener('visibilitychange', foreground);
    const timer = setInterval(() => void touch(), 60 * 60 * 1000);
    return () => { active = false; clearInterval(timer); document.removeEventListener('visibilitychange', foreground); };
  }, []);
  return null;
}
