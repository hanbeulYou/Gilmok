import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseClient } from "./client";

// One shared request also covers React Strict Mode effect replays.
export function createPreviewLoader(getClient: () => SupabaseClient) {
  let pending: Promise<unknown> | undefined;
  return () => {
    if (!pending) {
      pending = (async () => {
        const client = getClient();
        const { data, error } = await client.auth.getSession();
        if (error) throw new Error("로그인 상태를 확인하지 못했습니다.");
        if (!data.session) {
          const signedIn = await client.auth.signInAnonymously();
          if (signedIn.error || !signedIn.data.session) throw new Error("익명 로그인에 실패했습니다.");
        }
        const result = await client.rpc("score_inputs", {
          lat: 37.5025724504279, lng: 127.057585738094, radius_m: 800, floor: 3,
        });
        if (result.error) throw new Error("후보지 데이터를 불러오지 못했습니다.");
        return result.data as unknown;
      })().catch((error: unknown) => {
        pending = undefined;
        throw error;
      });
    }
    return pending;
  };
}

export const loadPreview = createPreviewLoader(getSupabaseClient);
