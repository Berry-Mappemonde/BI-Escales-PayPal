import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPublicFunds } from "./escales";

const answer = (body: unknown, ok = true, status = 200) =>
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, status, json: async () => body, text: async () => JSON.stringify(body) }));

describe("fetchPublicFunds", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the one public summary, with no key", async () => {
    const body = { currency: "EUR", stops: [], legs: [], projects: [], common_fund: { authorized_eur: "0.00", captured_eur: "1.00", refunded_eur: "0.00" } };
    answer(body);
    await expect(fetchPublicFunds()).resolves.toEqual(body);
    const [target, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit | undefined];
    expect(target).toMatch(/\/api\/escales\/funds\/public$/);
    expect(JSON.stringify(init ?? {})).not.toContain("x-admin-key");
  });

  it("fills in a zero common fund when the answer has none", async () => {
    answer({ currency: "EUR", stops: [], legs: [], projects: [] });
    await expect(fetchPublicFunds()).resolves.toMatchObject({ common_fund: { authorized_eur: "0.00", captured_eur: "0.00", refunded_eur: "0.00" } });
  });

  it.each([
    ["an error status", { detail: "Not Found" }, false, 404],
    ["an answer of another shape", { json: { stops: [] } }, true, 200],
    ["an empty answer", null, true, 200],
  ])("throws on %s", async (_case, body, ok, status) => {
    answer(body, ok as boolean, status as number);
    await expect(fetchPublicFunds()).rejects.toThrow();
  });
});
