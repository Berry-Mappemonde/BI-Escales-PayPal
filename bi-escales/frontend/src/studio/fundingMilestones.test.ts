import { describe, expect, it } from "vitest";
import { fundingGroups } from "./fundingMilestones";

describe("milestone crowdfunding ledger projections", () => {
  it("isolates marine projects from sailing stopovers and common funds", () => {
    const groups = fundingGroups([
      { kind: "project_pledge", target_id: "reef-1", milestone_id: "any", status: "captured", amount_eur: 20, net_eur: 20 },
      { kind: "project_pledge", target_id: "reef-1", milestone_id: "any", status: "partially_refunded", amount_eur: 50, net_eur: 30 },
      { kind: "mile", milestone_id: "port-2", status: "authorized", amount_eur: 40, net_eur: 40 },
      { kind: "common_fund", milestone_id: "common", status: "captured", amount_eur: 12 },
    ]);
    expect(groups).toEqual([
      { id: "reef-1", kind: "project", capturedEur: 50, authorizedEur: 0, savedEur: 0, releasedEur: 0, pledgeCount: 2 },
      { id: "port-2", kind: "stop", capturedEur: 0, authorizedEur: 40, savedEur: 0, releasedEur: 0, pledgeCount: 1 },
      { id: "common", kind: "common", capturedEur: 12, authorizedEur: 0, savedEur: 0, releasedEur: 0, pledgeCount: 1 },
    ]);
  });

  it("counts vaulted promises separately, excludes failed or fully refunded payments", () => {
    const [row] = fundingGroups([
      { kind: "mile", milestone_id: "port-1", status: "vaulted", amount_eur: 75 },
      { kind: "mile", milestone_id: "port-1", status: "refunded", amount_eur: 25, net_eur: 0 },
      { kind: "mile", milestone_id: "port-1", status: "voided", amount_eur: 15 },
      { kind: "mile", milestone_id: "port-1", status: "capture_failed", amount_eur: 100 },
    ]);
    expect(row).toMatchObject({ capturedEur: 0, authorizedEur: 0, savedEur: 75, releasedEur: 15, pledgeCount: 3 });
  });

  it("handles AG Studio prefixed columns and decimal cents without floating error", () => {
    const [row] = fundingGroups([
      { "pledges.kind": "project_pledge", "pledges.target_id": "reef-2", "pledges.status": "captured", "pledges.amount_eur": "0.10", "pledges.net_eur": "0.10" },
      { "pledges.kind": "project_pledge", "pledges.target_id": "reef-2", "pledges.status": "captured", "pledges.amount_eur": "0.20", "pledges.net_eur": "0.20" },
    ]);
    expect(row.capturedEur).toBe(0.3);
    expect(row.id).toBe("reef-2");
  });

  it("ignores invalid amounts and statuses rather than inventing totals", () => {
    expect(fundingGroups([{ status: "pending", amount_eur: "999" }])).toEqual([]);
    const [row] = fundingGroups([{ status: "authorized", kind: "mile", milestone_id: "port", amount_eur: "NaN" }]);
    expect(row.authorizedEur).toBe(0);
  });
});
