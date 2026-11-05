import { afterEach, expect, it, vi } from "vitest";
import { createPledge } from "./escales";
afterEach(() => vi.unstubAllGlobals());
it("sends the displayed total and quantity to POST /pledges", async () => {
  const fetch = vi.fn().mockResolvedValue({ok:true, json:async () => ({id:"P"})});vi.stubGlobal("fetch",fetch);
  await createPledge({amount_eur:"90.00",quantity:3,kind:"berth",description:"3 berths",milestone_id:"dep-mayotte"},"quantity-checkout");
  const [url,options]=fetch.mock.calls[0];expect(url).toContain("/pledges");expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toMatchObject({amount_eur:"90.00",quantity:3});
});
