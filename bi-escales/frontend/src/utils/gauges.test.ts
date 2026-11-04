import { describe, expect, it } from "vitest";
import { buildGaugeRows, gaugePercent } from "../utils/gauges";
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
