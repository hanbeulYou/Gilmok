import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createPreviewLoader } from "../../lib/supabase/preview";

function fixture(hasSession = false) {
  const client = {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: hasSession ? { user: { id: "owner" } } : null }, error: null }),
      signInAnonymously: vi.fn().mockResolvedValue({ data: { session: { user: { id: "owner" } } }, error: null }),
    },
    rpc: vi.fn().mockResolvedValue({ data: { meta: { schema_version: "1.3" } }, error: null }),
  };
  return { client, load: createPreviewLoader(() => client as unknown as SupabaseClient) };
}

describe("anonymous comparison preview", () => {
  it("coalesces Strict Mode requests into one sign-in and one RPC without an address", async () => {
    const { client, load } = fixture();
    const [a, b] = await Promise.all([load(), load()]);
    expect(a).toEqual(b);
    await load();
    expect(client.auth.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(client.rpc).toHaveBeenCalledExactlyOnceWith("score_inputs", {
      lat: 37.5025724504279, lng: 127.057585738094, radius_m: 800, floor: 3,
    });
  });
  it("reuses an existing identity", async () => {
    const { client, load } = fixture(true);
    await load();
    expect(client.auth.signInAnonymously).not.toHaveBeenCalled();
  });
  it("does not request data after an authentication error and allows retry", async () => {
    const { client, load } = fixture();
    client.auth.signInAnonymously.mockResolvedValueOnce({ data: { session: null }, error: { message: "private details" } });
    await expect(load()).rejects.toThrow("익명 로그인에 실패했습니다.");
    expect(client.rpc).not.toHaveBeenCalled();
    await expect(load()).resolves.toEqual({ meta: { schema_version: "1.3" } });
  });
});
