import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { legSamplePoints, reviewLeg, reviewPlan, seasonFromAtlas } from "./planReview.js";

const LEG = {
  from: "Ajaccio (Corse)", to: "Fort-de-France (Martinique)", departIso: "2026-05-27T08:00:00Z", arriveIso: "2026-06-24T10:00:00Z",
  daysAtSea: 26.8, holdDays: 3, fromNm: 1820, toNm: 6973, legNm: 5153, month: 6,
  zees: [{ mrgid: 5677, name: "French EEZ", gold: true, poe: ["Ajaccio"] }, { mrgid: 8, name: "Barbados EEZ", gold: false, poe: [] }],
  ampCount: 2, pearls: { known: 400, unknown: 10 },
  flags: [{ kind: "formalities", names: ["Barbados EEZ"] }],
};

describe("planReview — revue de plan par règles", () => {
  it("reads the season from the atlas cache, counts missing cells honestly", () => {
    const lookup = (lat, lon, month) => (lat > 30 ? { point: { rose: { gale_pct: 18 }, cyclone: { nearby: 2 } } } : null);
    const s = seasonFromAtlas(LEG, [{ lat: 41, lon: 8 }, { lat: 15, lon: -60 }], lookup);
    assert.deepEqual(s, { galePct: 18, cyclones: 2, cells: 1, missing: 1 });
    assert.deepEqual(seasonFromAtlas(LEG, [{ lat: 1, lon: 1 }], () => null), { galePct: null, cyclones: null, cells: 0, missing: 1 });
  });

  it("puts the leg into words: badges, notes, level — nothing invented", () => {
    const r = reviewLeg(LEG, { galePct: 18, cyclones: 2, cells: 3, missing: 0 }, "fr");
    assert.equal(r.departIso, LEG.departIso);
    assert.equal(r.title, "Ajaccio (Corse) → Fort-de-France (Martinique)");
    assert.equal(r.to, "Fort-de-France (Martinique)");
    assert.equal(r.dates, "27 mai → 24 juin");
    const kinds = r.badges.map((b) => b.kind);
    assert.deepEqual(kinds, ["sea", "rest", "zee", "amp", "gale", "cyclone"]);
    assert.equal(r.badges.find((b) => b.kind === "sea").text, "5153 nm · 26.8 j de mer");
    assert.equal(r.badges.find((b) => b.kind === "zee").text, "2 ZEE · 1 Gold");
    const fromServer = reviewLeg({ ...LEG, daysAtSea: 11, legNm: 1920 }, null, "fr");
    assert.equal(fromServer.badges.find((b) => b.kind === "sea").text, "1920 nm · 11 j de mer");
    assert.equal(fromServer.daysAtSea, 11);
    assert.equal(r.badges.find((b) => b.kind === "gale").level, "alert");
    assert.match(r.notes[0], /Formalités à vérifier : Barbados EEZ/);
    assert.match(r.notes[1], /Saison ventée .* 18 % ≥ 15 %/);
    assert.equal(r.level, "alert");
    assert.equal(r.alertCount, 2, "gale + cyclone, pas de chiffre inventé");
    assert.equal(reviewLeg({ ...LEG, alertCount: 11, flags: [] }, { galePct: 1, cyclones: 0, cells: 1, missing: 0 }, "fr").alertCount, 11);
    // No atlas yet: one honest badge, no gale / cyclone claim.
    const cold = reviewLeg(LEG, { galePct: null, cyclones: null, cells: 0, missing: 5 }, "en");
    assert.ok(cold.badges.some((b) => b.text === "season: atlas not loaded"));
    assert.ok(!cold.badges.some((b) => b.kind === "gale" || b.kind === "cyclone"));
    // A long leg without rest at the end is flagged.
    const tired = reviewLeg({ ...LEG, holdDays: 0, flags: [] }, null, "fr");
    assert.equal(tired.badges.find((b) => b.kind === "rest").text, "pas de repos prévu");
    assert.equal(tired.level, "watch");
  });

  it("samples the clock inside the leg's sea miles and reviews every leg", () => {
    const clock = { vertices: Array.from({ length: 40 }, (_, i) => ({ sailNm: i * 200, lat: 40 - i, lon: -i, tHours: i * 24 })) };
    const pts = legSamplePoints(clock, LEG, 5);
    assert.equal(pts.length, 5);
    assert.ok(pts.every((p) => p.lat <= 40 - 9 && p.lat >= 40 - 35));
    const out = reviewPlan({ legs: [LEG, { ...LEG, from: "X", to: "Y", zees: [], flags: [], ampCount: 0, holdDays: 2 }] }, clock, () => null, "fr");
    assert.equal(out.length, 2);
    assert.equal(out[1].level, "ok");
  });

  it("porte antiShipping sans l'inventer ni l'ajouter aux badges", () => {
    const quiet = reviewLeg(LEG, null, "fr");
    assert.equal(quiet.antiShipping, null);
    const hot = reviewLeg({ ...LEG, flags: [], antiShipping: { score: 0.4, lanes: ["Gibraltar"] } }, null, "fr");
    assert.deepEqual(hot.antiShipping, { score: 0.4, lanes: ["Gibraltar"] });
    assert.ok(!hot.badges.some((b) => b.kind === "lanes"));
    const empty = reviewLeg({ ...LEG, flags: [], antiShipping: { score: 1, lanes: [] } }, null, "en");
    assert.equal(empty.antiShipping, null);
  });
});

describe("planReview — season source", () => {
  it("prefers the server's atlas reading, falls back to the client cache, stays honest when both are empty", async () => {
    const { seasonForLeg } = await import("./planReview.js");
    const served = { ...LEG, season: { galePct: 22, cyclones: 1, cells: 3, missing: 0, month: 6 } };
    assert.deepEqual(seasonForLeg(served, { vertices: [] }, () => null), { galePct: 22, cyclones: 1, cells: 3, missing: 0 });
    const clock = { vertices: [{ sailNm: 2000, lat: 40, lon: -5, tHours: 1 }] };
    const local = seasonForLeg({ ...LEG, season: { cells: 0, missing: 3 } }, clock, () => ({ point: { rose: { gale_pct: 9 }, cyclone: { nearby: 0 } } }));
    assert.equal(local.galePct, 9);
    assert.equal(seasonForLeg({ ...LEG, season: { cells: 0, missing: 3 } }, clock, () => null).cells, 0);
  });
});
