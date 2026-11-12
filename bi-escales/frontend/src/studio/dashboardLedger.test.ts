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

  it("keeps a stop's held gifts on a line of their own, apart from its pledges and the common fund", () => {
    const rows = ledgerPledges([
      pledge({ kind: "mile", milestone_id: "dep-brest", status: "captured", amount_eur: "20.00" }),
      pledge({ kind: "stop_gift", milestone_id: "dep-brest", target_id: "dep-brest", status: "authorized", amount_eur: "17.35" }),
      pledge({ kind: "stop_gift", milestone_id: "dep-brest", target_id: "dep-brest", status: "vaulted", amount_eur: "50.00" }),
      pledge({ kind: "common_fund", milestone_id: "", target_id: "fonds-commun", amount_eur: "5.00" }),
    ]);
    const names = { "dep-brest": "Brest" };
    const groups = groupLedger(rows, "target", (row) => fundingLabel(row, names, "en"));
    expect(groups.map(({ type, label, count, captured, authorized, vaulted }) => [type, label, count, captured, authorized, vaulted])).toEqual([
      ["stop", "Brest", 1, 2000, 0, 0],
      // Held and saved, nothing captured: a gift is not money received before arrival.
      ["gift", "Brest", 2, 0, 1735, 5000],
      ["common", "Common fund", 1, 500, 0, 0],
    ]);
    const byType = groupLedger(rows, "type", (row) => row.type);
    expect(byType.map((group) => group.id)).toEqual(["stop", "gift", "common"]);
  });

  it("files the real stop gifts read from test2 under their stops", () => {
    // GET /api/escales/pledges on test2, 12 Nov 2026 (demo shape): the server stores the target as the stop slug.
    const real = [
      { id: "81ad32287e1d4c1e9f22927f627c66a4", kind: "stop_gift", status: "created", milestone_id: "dep-la-rochelle", target_id: "la-rochelle", amount_eur: "1.00", payment_mode: "AUTHORIZE", currency: "EUR" },
      { id: "f766b7926e0242afa4d1ae1559d38ea5", kind: "stop_gift", status: "created", milestone_id: "dep-ajaccio-corse", target_id: "ajaccio-corse", amount_eur: "1000.00", payment_mode: "AUTHORIZE", currency: "EUR" },
      { id: "4926582e2b734c1098796b6f26cbe79b", kind: "stop_gift", status: "refunded", milestone_id: "dep-ajaccio-corse", target_id: "ajaccio-corse", amount_eur: "1.00", payment_mode: "AUTHORIZE", currency: "EUR" },
    ] as PublicPledge[];
    const names = { "dep-la-rochelle": "La Rochelle", "dep-ajaccio-corse": "Ajaccio (Corse)" };
    const groups = groupLedger(ledgerPledges(real), "target", (row) => fundingLabel(row, names, "en"));
    expect(groups.map(({ type, label, count, captured, authorized, refunded }) => [type, label, count, captured, authorized, refunded])).toEqual([
      // Not yet approved in PayPal: counted, but neither held nor received.
      ["gift", "La Rochelle", 1, 0, 0, 0],
      ["gift", "Ajaccio (Corse)", 2, 0, 0, 100],
    ]);
  });

  it("names the gift type in both languages", () => {
    const [row] = ledgerPledges([pledge({ kind: "stop_gift", status: "authorized" })]);
    expect(row.type).toBe("gift");
    expect(fundingLabel(row, { "dep-brest": "Brest" }, "fr")).toBe("Brest");
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
