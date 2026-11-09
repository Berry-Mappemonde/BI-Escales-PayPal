import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPrices } from "./escales";

describe("fetchPrices", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the app language as ?lang= on /api/escales/prices", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ simulated: true, prices: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchPrices("en");

    const calledUrl = String(fetchMock.mock.calls[0]?.[0] ?? "");
    expect(calledUrl).toContain("/api/escales/prices");
    expect(calledUrl).toContain("lang=en");
  });
});
