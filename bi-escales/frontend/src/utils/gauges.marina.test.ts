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
        platform_fee_eur: "3.00",
        marina_net_eur: "27.00",
        marina_payout_status: "success",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].berth_bookings).toBe(2);
    expect(rows[0].gross_eur).toBe(60);
    expect(rows[0].platform_fees_eur).toBe(3);
    expect(rows[0].marina_net_eur).toBe(27);
    expect(rows[0].fees_simulated).toBe(false);
    expect(rows[0].marina_payout_status).toBe("success");
  });

  it("ignore les frais tant que la capture n’est pas faite", () => {
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
        platform_fee_eur: "3.00",
        marina_net_eur: "27.00",
        platform_fee_simulated: true,
      },
    ]);
    expect(rows[0].platform_fees_eur).toBe(0);
    expect(rows[0].marina_net_eur).toBe(0);
    expect(rows[0].fees_simulated).toBe(false);
  });
});
