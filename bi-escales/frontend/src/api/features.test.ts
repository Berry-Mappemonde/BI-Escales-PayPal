import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchFeatures } from "./escales";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchFeatures", () => {
  it("does not expose paypal_client_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ vault: true, clock_pinned: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const flags = await fetchFeatures();
    expect(flags.clock_pinned).toBe(true);
    expect("paypal_client_id" in flags).toBe(false);
  });
});
