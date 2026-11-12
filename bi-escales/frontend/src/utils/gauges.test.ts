import { describe, expect, it } from "vitest";
import { buildGaugeRows, gaugePercent, sumAmount } from "../utils/gauges";
import type { PublicPledge } from "../api/types";

describe("buildGaugeRows", () => {
  it("agrège par jalon et calcule les jauges", () => {
    const pledges: PublicPledge[] = [
      {
        id: "a",
        status: "authorized",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "20.00",
        description: "x",
        milestone_id: "dep-mayotte",
      },
      {
        id: "b",
        status: "captured",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "60.00",
        description: "y",
        milestone_id: "dep-mayotte",
      },
      {
        id: "c",
        status: "voided",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "1.00",
        description: "z",
        milestone_id: "other",
      },
    ];
    const rows = buildGaugeRows(pledges);
    expect(rows).toHaveLength(2);
    const main = rows.find((r) => r.milestone_id === "dep-mayotte");
    expect(main?.authorized_count).toBe(1);
    expect(main?.captured_count).toBe(1);
    expect(gaugePercent(main!, "authorized")).toBe(50);
  });
});

describe("buildGaugeRows with gifts to a stop", () => {
  const row = (id: string, kind: string, status: PublicPledge["status"], amount: string): PublicPledge => ({
    id, kind, status, intent: "AUTHORIZE", currency: "EUR", amount_eur: amount, description: id, milestone_id: "dep-brest",
  });

  it("puts a stop's gifts on their own line, right after the stop's other pledges", () => {
    const rows = buildGaugeRows([
      row("g1", "stop_gift", "authorized", "17.35"),
      row("m1", "mile", "captured", "20.00"),
      row("g2", "stop_gift", "voided", "5.00"),
      row("c1", "common_fund", "captured", "10.00"),
    ]);
    expect(rows.map((r) => [r.milestone_id, r.kind ?? null])).toEqual([
      ["dep-brest", null],
      ["dep-brest", "stop_gift"],
    ]);
    expect(rows[0]).toMatchObject({ captured_count: 2, captured_total_eur: 30, authorized_count: 0 });
    expect(rows[1]).toMatchObject({ authorized_count: 1, authorized_total_eur: 17.35, captured_count: 0, voided_count: 1 });
  });
});

describe("sumAmount", () => {
  it("n'additionne pas les montants non-EUR dans le total EUR", () => {
    const pledges: PublicPledge[] = [
      {
        id: "eur",
        status: "authorized",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "25.00",
        description: "x",
        milestone_id: "m",
      },
      {
        id: "usd",
        status: "authorized",
        intent: "AUTHORIZE",
        currency: "USD",
        amount_eur: "99.00",
        description: "y",
        milestone_id: "m",
      },
    ];
    expect(sumAmount(pledges, "authorized")).toBe(25);
  });
});
