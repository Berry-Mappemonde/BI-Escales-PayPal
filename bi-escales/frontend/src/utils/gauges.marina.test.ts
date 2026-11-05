import { describe, expect, it } from "vitest";
import { buildMarinaDashboardRows } from "./gauges";

describe("buildMarinaDashboardRows", () => {
  it("agrège les promesses berth par escale", () => {
    const rows = buildMarinaDashboardRows([
      {
        id: "b1",
        status: "authorized",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "30.00",
        description: "berth",
        milestone_id: "dep-mayotte",
        kind: "berth",
      },
      {
        id: "b2",
        status: "captured",
        intent: "AUTHORIZE",
        currency: "EUR",
        amount_eur: "30.00",
        description: "berth",
        milestone_id: "dep-mayotte",
        kind: "berth",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].berth_bookings).toBe(2);
    expect(rows[0].gross_eur).toBe(60);
  });
});
