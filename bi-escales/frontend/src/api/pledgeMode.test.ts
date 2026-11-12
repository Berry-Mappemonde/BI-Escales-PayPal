import { afterEach, expect, it, vi } from "vitest";
import { fetchPledgeMode } from "./escales";
afterEach(() => vi.unstubAllGlobals());
it("looks up mode with a read-only GET", async () => {
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async () => ({payment_mode:"VAULT"})});vi.stubGlobal("fetch",fetch);
  expect(await fetchPledgeMode("leg-test", "cabin_leg")).toEqual({payment_mode:"VAULT"});
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0]).toEqual([expect.stringContaining("/pledges/mode?milestone_id=leg-test&kind=cabin_leg")]);
});
it("rejects unsupported modes before Card Fields can initialize", async () => {
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async () => ({payment_mode:"UNKNOWN"})}));
  await expect(fetchPledgeMode("dep-test")).rejects.toThrow("Invalid card payment mode");
});

it("accepts the immediate donation CAPTURE mode returned by the backend", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ payment_mode: "CAPTURE" }) }));
  expect(await fetchPledgeMode("", "project_pledge")).toEqual({ payment_mode: "CAPTURE" });
});
