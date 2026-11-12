import { describe, expect, it } from "vitest";
import { treasurerStopOverview } from "./treasurerStopOverview.js";

const schedule = {
  export: {
    escales: [
      { milestone_id: "dep-saint-maur", name: "Saint-Maur", arrival_iso: "2026-11-12T08:00:00Z" },
      { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" },
      { milestone_id: "dep-ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: "2026-11-29T02:00:00Z" },
      { milestone_id: "dep-papeete", name: "Papeete", arrival_iso: "2027-03-12T15:00:00Z" },
    ],
  },
  legs: [
    { id: "leg-saint-maur-to-la-rochelle", from_name: "Saint-Maur", to_name: "La Rochelle", departure_iso: "2026-11-12T08:00:00Z", arrival_iso: "2026-11-12T12:00:00Z" },
    { id: "leg-la-rochelle-to-ajaccio-corse", from_name: "La Rochelle", to_name: "Ajaccio (Corse)", departure_iso: "2026-11-14T08:00:00Z", arrival_iso: "2026-11-29T02:00:00Z" },
  ],
};
const pledge = (milestone_id, status, amount_eur = "20.00") => ({ id: `${milestone_id}-${status}-${amount_eur}`, milestone_id, status, amount_eur });
const NOW = "2026-11-12T13:00:00Z"; // Saint-Maur and La Rochelle reached, Ajaccio under way, Papeete ahead

describe("treasurerStopOverview", () => {
  it("says which stops the boat has reached, by the same rule as the stop sheet", () => {
    const view = treasurerStopOverview(schedule, NOW, [], []);
    expect(Object.fromEntries(Object.entries(view).map(([id, row]) => [id, row.status]))).toEqual({
      "dep-saint-maur": "arrived",
      "dep-la-rochelle": "arrived",
      "dep-ajaccio-corse": "upcoming",
      "dep-papeete": "upcoming",
    });
  });

  it("marks a stop under way once the boat has left for it", () => {
    const view = treasurerStopOverview(schedule, "2026-11-20T00:00:00Z", [], []);
    expect(view["dep-ajaccio-corse"].status).toBe("en_route");
  });

  it("marks a cancelled stop, whatever the clock says", () => {
    const view = treasurerStopOverview(schedule, NOW, [{ id: "dep-la-rochelle", evidence: [], meta: { cancelled: true } }], []);
    expect(view["dep-la-rochelle"].status).toBe("cancelled");
    expect(view["dep-la-rochelle"].due).toBe(false);
  });

  it("counts the held pledges of each stop and their total", () => {
    const view = treasurerStopOverview(schedule, NOW, [], [
      pledge("dep-la-rochelle", "authorized", "20.00"),
      pledge("dep-la-rochelle", "authorized", "1.50"),
      pledge("dep-ajaccio-corse", "vaulted", "60,00"),
      pledge("dep-ajaccio-corse", "captured", "30.00"),
      pledge("dep-ajaccio-corse", "voided", "30.00"),
      pledge("dep-ajaccio-corse", "refunded", "30.00"),
    ]);
    expect(view["dep-la-rochelle"]).toMatchObject({ held: 2, heldEur: 21.5 });
    expect(view["dep-ajaccio-corse"]).toMatchObject({ held: 1, heldEur: 60 });
    expect(view["dep-papeete"]).toMatchObject({ held: 0, heldEur: 0 });
  });

  it("calls held pledges due for capture only where the boat has arrived", () => {
    const view = treasurerStopOverview(schedule, NOW, [], [pledge("dep-la-rochelle", "authorized"), pledge("dep-ajaccio-corse", "authorized")]);
    expect(view["dep-la-rochelle"].due).toBe(true);
    expect(view["dep-ajaccio-corse"].due).toBe(false);
    expect(view["dep-saint-maur"].due).toBe(false); // arrived, nothing held
  });

  it("does not count cabin pledges, which belong to a leg", () => {
    const view = treasurerStopOverview(schedule, NOW, [], [pledge("leg-la-rochelle-to-ajaccio-corse", "vaulted", "80.00")]);
    expect(Object.values(view).every((row) => row.held === 0)).toBe(true);
    expect(view["leg-la-rochelle-to-ajaccio-corse"]).toBeUndefined();
  });

  it("gives no status when the clock is unknown, and still counts the pledges", () => {
    const view = treasurerStopOverview(schedule, null, null, [pledge("dep-la-rochelle", "authorized")]);
    expect(view["dep-la-rochelle"]).toEqual({ status: null, held: 1, heldEur: 20, due: false });
  });

  it("is empty for an empty schedule and tolerates missing lists", () => {
    expect(treasurerStopOverview({ export: { escales: [] }, legs: [] }, NOW, undefined, undefined)).toEqual({});
    expect(treasurerStopOverview(null, NOW, [], [])).toEqual({});
  });
});
