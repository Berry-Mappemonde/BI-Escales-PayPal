import { describe, expect, it } from "vitest";
import type { CaptainProposal, PublicPledge } from "../../api/types";
import {
  buildEvidence,
  describeModelSource,
  releasableHolds,
  stopOnSchedule,
  sumEur,
} from "./captainEvidence";

const NOW = new Date("2026-11-13T00:00:00Z");
const review: CaptainProposal = {
  milestone_id: "dep-ajaccio-corse",
  proposal: "wait",
  pledge_ids: ["p-1", "p-2"],
  pending_authorizations: [
    { pledge_id: "p-1", amount_eur: "20.00", authorization_expires_at: "2026-12-11T00:00:00Z" },
    { pledge_id: "p-2", amount_eur: "12.50", authorization_expires_at: "2026-12-03T00:00:00Z" },
  ],
  paypal_tool_calls: [
    { tool: "orders.get", resource_id: "ORDER-1" },
    { tool: "authorizations.get", resource_id: "AUTH-1" },
    { tool: "orders.get", resource_id: "ORDER-2" },
    { tool: "authorizations.get", resource_id: "AUTH-2" },
    { tool: "disputes.list", resource_id: "" },
  ],
};

describe("buildEvidence", () => {
  it("cites every claim to a source that exists", () => {
    const { claims, sources } = buildEvidence(review, "2026-11-28T22:02:54.002Z", NOW);
    expect(sources.map((source) => source.kind)).toEqual([
      "schedule",
      "pending_authorizations",
      "authorizations.get",
      "orders.get",
    ]);
    expect(sources.map((source) => source.n)).toEqual([1, 2, 3, 4]);
    for (const claim of claims) {
      expect(sources.some((source) => source.n === claim.cite)).toBe(true);
    }
    expect(claims.map((claim) => [claim.key, claim.cite])).toEqual([
      ["arrival", 1],
      ["holds", 2],
      ["validTo", 2],
      ["authorizationsRead", 3],
      ["ordersRead", 4],
    ]);
  });

  it("sums the holds and takes the earliest expiry", () => {
    const { claims } = buildEvidence(review, undefined, NOW);
    expect(claims.find((claim) => claim.key === "holds")).toMatchObject({ count: 2, totalEur: 32.5 });
    expect(claims.find((claim) => claim.key === "validTo")?.iso).toBe("2026-12-03T00:00:00Z");
  });

  it("says expired rather than valid once the earliest expiry has passed", () => {
    const { claims } = buildEvidence(review, undefined, new Date("2026-12-05T00:00:00Z"));
    expect(claims.map((claim) => claim.key)).toContain("expired");
    expect(claims.map((claim) => claim.key)).not.toContain("validTo");
  });

  it("drops a claim and renumbers when its field is missing", () => {
    const { claims, sources } = buildEvidence(
      { milestone_id: "m", proposal: "wait", pledge_ids: [], paypal_tool_calls: review.paypal_tool_calls },
      undefined,
      NOW,
    );
    expect(sources.map((source) => [source.n, source.kind])).toEqual([
      [1, "authorizations.get"],
      [2, "orders.get"],
    ]);
    expect(claims.map((claim) => claim.key)).toEqual(["authorizationsRead", "ordersRead"]);
  });

  it("makes no claim at all when there is no review or schedule", () => {
    expect(buildEvidence(null, undefined, NOW)).toEqual({ claims: [], sources: [] });
  });

  it("leaves out the expiry for saved cards, which have none", () => {
    const { claims } = buildEvidence(
      { ...review, pending_authorizations: [{ pledge_id: "p-v", amount_eur: "10.00", status: "vaulted" }] },
      undefined,
      NOW,
    );
    expect(claims.map((claim) => claim.key)).not.toContain("validTo");
  });

  it("lists each PayPal id once, and only for the two review tools", () => {
    const { sources } = buildEvidence(
      { ...review, paypal_tool_calls: [...(review.paypal_tool_calls ?? []), { tool: "orders.get", resource_id: "ORDER-1" }] },
      undefined,
      NOW,
    );
    expect(sources.find((source) => source.kind === "orders.get")?.ids).toEqual(["ORDER-1", "ORDER-2"]);
    expect(sources.some((source) => String(source.kind) === "disputes.list")).toBe(false);
  });
});

describe("sumEur", () => {
  it("adds in cents and ignores unreadable amounts", () => {
    expect(sumEur(["0.10", "0.20"])).toBe(0.3);
    expect(sumEur(["10,50", undefined, "abc"])).toBe(10.5);
  });
});

describe("stopOnSchedule", () => {
  it("finds a stop and a leg, and returns nothing for an unknown id", () => {
    const schedule = {
      export: { escales: [{ milestone_id: "dep-ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: "2026-11-28T22:02:54Z" }] },
      legs: [{ id: "leg-a", from_name: "La Rochelle", to_name: "Ajaccio (Corse)", arrival_iso: "2026-11-28T22:02:54Z" }],
    };
    expect(stopOnSchedule(schedule, "dep-ajaccio-corse")).toEqual({
      name: "Ajaccio (Corse)",
      arrivalIso: "2026-11-28T22:02:54Z",
    });
    expect(stopOnSchedule(schedule, "leg-a").name).toBe("La Rochelle → Ajaccio (Corse)");
    expect(stopOnSchedule(schedule, "nope")).toEqual({});
    expect(stopOnSchedule(null, "dep-ajaccio-corse")).toEqual({});
  });
});

describe("releasableHolds", () => {
  it("keeps held and saved pledges on this milestone only", () => {
    const pledge = (id: string, status: PublicPledge["status"], milestone_id = "m") =>
      ({ id, status, milestone_id }) as PublicPledge;
    const holds = releasableHolds(
      [
        pledge("a", "authorized"),
        pledge("b", "vaulted"),
        pledge("c", "pending"),
        pledge("d", "captured"),
        pledge("e", "authorized", "other"),
      ],
      "m",
    );
    expect(holds.map((row) => row.id)).toEqual(["a", "b"]);
  });
});

describe("describeModelSource", () => {
  it("names the model and provider, including the NIM fallback", () => {
    expect(describeModelSource({ provider: "nim", model: "private/nvidia/nemotron-3.5-super-120b-a12b" })).toEqual({
      kind: "model",
      model: "Nemotron",
      provider: "NVIDIA NIM",
    });
    expect(describeModelSource({ provider: "nim_fallback", model: "nvidia/nemotron-3.5-lightning-30b-a3b" })).toMatchObject({
      provider: "NVIDIA NIM",
    });
  });

  it("never presents a rules fallback as a model", () => {
    expect(describeModelSource({ provider: "rules", model: "" })).toEqual({ kind: "rules" });
    expect(describeModelSource({ provider: "none", model: "" })).toEqual({ kind: "rules" });
  });

  it("copes with partial sources and never returns an empty name", () => {
    expect(describeModelSource({ provider: "llm", model: "" })).toEqual({ kind: "model_unnamed" });
    expect(describeModelSource({ provider: "nim", model: "" })).toEqual({ kind: "provider", provider: "NVIDIA NIM" });
    expect(describeModelSource({ provider: "", model: "vendor/some-model" })).toEqual({
      kind: "provider",
      provider: "some-model",
    });
    expect(describeModelSource({ provider: "", model: "" })).toBeNull();
    expect(describeModelSource(undefined)).toBeNull();
  });
});
