import { afterEach, describe, expect, it, vi } from "vitest";
import { createPledge } from "../api/escales";
import { demoPlay, fetchOwnDemoPledges } from "../api/demoPlay";
import { OWN_PLEDGES_MAX, forgetOwnPledgesForTests, ownPledgePairs, pledgeKey, rememberPledgeKey } from "./ownPledges";

const answer = (body: unknown, ok = true, status = 200) =>
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, status, statusText: "", json: async () => body }));
const lastCall = () => vi.mocked(fetch).mock.calls.at(-1) as [string, RequestInit];

describe("the pledges this browser made", () => {
  afterEach(() => {
    forgetOwnPledgesForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("remembers the request id a pledge was created with", () => {
    rememberPledgeKey("p-1", "key-1");
    rememberPledgeKey("p-2", "key-2");
    expect(pledgeKey("p-1")).toBe("key-1");
    expect(pledgeKey("p-3")).toBeNull();
    expect(ownPledgePairs()).toEqual([{ id: "p-1", key: "key-1" }, { id: "p-2", key: "key-2" }]);
  });

  it("ignores an empty id or key", () => {
    rememberPledgeKey("", "key");
    rememberPledgeKey("p-1", "  ");
    rememberPledgeKey(undefined, undefined);
    expect(ownPledgePairs()).toEqual([]);
  });

  it("keeps the newest pledges when it holds more than the server accepts", () => {
    for (let n = 0; n < OWN_PLEDGES_MAX + 5; n += 1) rememberPledgeKey(`p-${n}`, `key-${n}`);
    const pairs = ownPledgePairs();
    expect(pairs).toHaveLength(OWN_PLEDGES_MAX);
    expect(pairs[0].id).toBe("p-5");
    expect(pairs.at(-1)?.id).toBe(`p-${OWN_PLEDGES_MAX + 4}`);
  });

  it("reads nothing from a stored value that is not its own", () => {
    localStorage.setItem("escales.demo.pledge-keys", "not json");
    expect(ownPledgePairs()).toEqual([]);
    localStorage.setItem("escales.demo.pledge-keys", JSON.stringify(["p-1"]));
    expect(ownPledgePairs()).toEqual([]);
    localStorage.setItem("escales.demo.pledge-keys", JSON.stringify({ "p-1": 42, "p-2": "key-2" }));
    expect(ownPledgePairs()).toEqual([{ id: "p-2", key: "key-2" }]);
  });

  it("never throws when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    expect(() => rememberPledgeKey("p-1", "key-1")).not.toThrow();
    expect(ownPledgePairs()).toEqual([]);
    expect(pledgeKey("p-1")).toBeNull();
  });

  it("is filled by createPledge, with the request id the browser chose", async () => {
    answer({ id: "PLEDGE-9", status: "created" });
    await createPledge({ amount_eur: "20.00", description: "x", milestone_id: "dep-la-rochelle" }, "browser-chosen-id");
    expect(pledgeKey("PLEDGE-9")).toBe("browser-chosen-id");
    expect((lastCall()[1].headers as Record<string, string>)["PayPal-Request-Id"]).toBe("browser-chosen-id");
  });

  it("is not filled when the pledge could not be created", async () => {
    answer({ detail: "nope" }, false, 422);
    await expect(createPledge({ amount_eur: "20.00", description: "x", milestone_id: "dep-la-rochelle" }, "browser-chosen-id")).rejects.toThrow("nope");
    expect(ownPledgePairs()).toEqual([]);
  });
});

describe("demo treasurer API", () => {
  afterEach(() => {
    forgetOwnPledgesForTests();
    vi.unstubAllGlobals();
  });

  it("asks nothing of the server when this browser made no pledge", async () => {
    answer({ own: [] });
    await expect(fetchOwnDemoPledges()).resolves.toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("sends the ids and keys it remembers, and returns what the server confirms", async () => {
    rememberPledgeKey("p-1", "key-1");
    rememberPledgeKey("p-2", "key-2");
    const own = [{ pledge_id: "p-1", status: "authorized", arrival_simulated_at: null, approved_at: null, actions: ["simulate_arrival", "void"] }];
    answer({ own });
    await expect(fetchOwnDemoPledges()).resolves.toEqual(own);
    const [target, init] = lastCall();
    expect(target).toMatch(/\/api\/escales\/demo\/pledges\/own$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ pledges: [{ id: "p-1", key: "key-1" }, { id: "p-2", key: "key-2" }] });
    expect(JSON.stringify(init.headers)).not.toContain("x-admin-key");
  });

  it.each([
    ["simulate_arrival", "simulate-arrival"],
    ["approve", "approve"],
    ["capture", "capture"],
    ["void", "void"],
    ["refund", "refund"],
  ] as const)("%s goes to its own route with the pledge's key, and no treasurer key", async (action, path) => {
    rememberPledgeKey("p 1", "key-1");
    answer({ pledge: { id: "p 1" }, play: { pledge_id: "p 1", status: "authorized", actions: [] } });
    await demoPlay("p 1", action);
    const [target, init] = lastCall();
    expect(target).toMatch(new RegExp(`/api/escales/demo/pledges/p%201/${path}$`));
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "X-Pledge-Key": "key-1" });
  });

  it("gives the server's reason when an action is refused", async () => {
    answer({ detail: "this pledge was not made from this browser" }, false, 403);
    await expect(demoPlay("p-other", "capture")).rejects.toThrow("this pledge was not made from this browser");
    expect((lastCall()[1].headers as Record<string, string>)["X-Pledge-Key"]).toBe("");
  });
});
