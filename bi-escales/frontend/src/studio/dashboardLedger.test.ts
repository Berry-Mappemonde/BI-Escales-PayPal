import { describe, expect, it } from "vitest";
import type { PublicPledge } from "../api/types";
import { groupLedger, ledgerPledges, ledgerTotals } from "./dashboardLedger";
import { fundingLabel } from "./dashboardLocale";
import { pledgeStudioData } from "./pledgeData";

function pledge(overrides: Partial<PublicPledge>): PublicPledge {
  return {
    id: "pledge-1", status: "captured", intent: "CAPTURE", currency: "EUR",
    amount_eur: "30.00", milestone_id: "dep-brest", description: "Private notes",
    ...overrides,
  };
}

describe("treasurer dashboard ledger", () => {
  it("groups cabins by leg, projects by target, and common fund contributions together", () => {
    const rows = ledgerPledges([
      pledge({ kind: "berth", target_id: "marina-brest" }),
      pledge({ kind: "cabin_leg", milestone_id: "", target_id: "leg-brest-to-lorient" }),
      pledge({ kind: "common_fund", target_id: "dep-brest" }),
      pledge({ kind: "common_fund", milestone_id: "", target_id: "fonds-commun" }),
      pledge({ kind: "project_pledge", target_id: "reef-restoration" }),
      pledge({ milestone_id: "" }),
    ]);
    const names = { "dep-brest": "Brest", "dep-lorient": "Lorient" };
    const groups = groupLedger(rows, "target", (row) => fundingLabel(row, names, "en"));
    expect(groups.map(({ type, label, count }) => [type, label, count])).toEqual([
      ["stop", "Brest", 1],
      ["leg", "Brest → Lorient", 1],
      ["common", "Common fund", 2],
      ["project", "Reef restoration", 1],
      ["unassigned", "Unassigned", 1],
    ]);
  });

  it("keeps status buckets separate and adds exact cents", () => {
    const rows = ledgerPledges([
      pledge({ amount_eur: "0.10" }),
      pledge({ amount_eur: "0.20" }),
      pledge({ status: "partially_refunded", refunded_amount_eur: "10.10" }),
      pledge({ status: "refunded" }),
      pledge({ status: "authorized" }),
      pledge({ status: "vaulted" }),
      pledge({ status: "voided" }),
      pledge({ status: "pending" }),
    ]);
    expect(ledgerTotals(rows)).toEqual({
      count: 8, captured: 2020, authorized: 3000, vaulted: 3000, voided: 3000, refunded: 4010,
    });
  });

  it("propagates unavailable partial refunds without inflating net captures", () => {
    const rows = ledgerPledges([pledge({}), pledge({ status: "partially_refunded" }), pledge({ status: "authorized" })]);
    expect(ledgerTotals(rows)).toMatchObject({ captured: null, refunded: null, authorized: 3000 });
    expect(ledgerTotals(rows.filter((row) => row.status === "captured")).captured).toBe(3000);
  });

  it("uses captured after refunds for the Studio Net column and keeps holds and voids in status totals", () => {
    const rows = ledgerPledges([
      pledge({ status: "captured" }),
      pledge({ status: "partially_refunded", refunded_amount_eur: "10.10" }),
      pledge({ status: "refunded" }),
      pledge({ status: "authorized" }),
      pledge({ status: "vaulted" }),
      pledge({ status: "voided" }),
    ]);
    const [pledges, totals] = pledgeStudioData(rows).sources;

    expect(pledges).toMatchObject({ data: [30, 19.9, 0, 0, 0, 0].map((net_eur) => ({ net_eur })) });
    expect(totals).toMatchObject({ data: [
      { status: "captured", amount: 49.9 },
      { status: "authorized", amount: 30 },
      { status: "vaulted", amount: 30 },
      { status: "voided", amount: 30 },
      { status: "refunded", amount: 40.1 },
    ] });
    const [incomplete] = pledgeStudioData(ledgerPledges([pledge({ status: "partially_refunded" })])).sources;
    expect(incomplete).toMatchObject({ data: [{ net_eur: null }] });
  });

  it("projects only allowed fields before data reaches the dashboard or Studio", () => {
    const rows = ledgerPledges([pledge({
      contributor: "Private Supporter", description: "private@example.test",
      order_id: "private-order", capture_id: "private-capture",
    })]);
    expect(JSON.stringify(rows)).not.toMatch(/private/i);
    expect(JSON.stringify(pledgeStudioData(rows))).not.toMatch(/private/i);
  });
});
