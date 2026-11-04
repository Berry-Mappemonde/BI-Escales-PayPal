import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  COASTAL_SUGGEST_RULE,
  COMFORTS,
  COMFORT_TABLE,
  COMFORT_WIND_CAP_KT,
  DEFAULT_ORDERS,
  DEFAULT_PROFILE,
  EXPERT_FIELDS,
  EXPERT_IDS,
  HORIZONS_H,
  PROFILES,
  PROFILE_TABLE,
  STORAGE_KEY,
  clampExpert,
  clearSavedOrders,
  depthPhrase,
  exampleLine,
  lookaheadBudget,
  ordersLine,
  planningSpeedFor,
  POLAR_EFFICIENCY,
  readBoat,
  readSavedOrders,
  resolveOrders,
  sanitizeSaved,
  skipperSnapshot,
  SMALL_BOAT_LOA_M,
  suggestProfileForBoat,
  thresholdValues,
  thresholdsForEvent,
  writeSavedOrders,
} from "./skipperOrders.js";
import {
  CURRENT_SHIFT_KN,
  DEPTH_ALERT_M,
  GALE_HOLD_KT,
  GALE_KT,
  GROUP_NM,
  HS_ALERT_M,
  HS_SHIFT_M,
  MARINA_REFUGE_NM,
  RAIN_3H_MM,
  RAIN_MM_H,
  ROUTE_SAMPLE_NM,
  WIND_SHIFT_DEG,
  WIND_SHIFT_KT,
} from "./eventRules.js";
import { SUIVRE_LOOKAHEAD_H } from "./iciAlong.js";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "skipperOrders.js"), "utf8");
const LLM_SOURCES = new Set(["beaufort", "wmo", "metoffice", "usage", "derive", "ui"]);

function memStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    dump: () => Object.fromEntries(map),
  };
}

const berryPolar = {
  expedition_id: "berry-mappemonde-2026",
  boat_name: "Leopard 46",
  vmg_summary: {
    8: { downwind: { speed: 6.0 } },
    10: { downwind: { speed: 8.0 } },
    12: { downwind: { speed: 10.0 } },
    16: { downwind: { speed: 12.0 } },
  },
};

describe("skipperOrders — source contract", () => {
  it("is pure: no HTTP, no chat, no Nemotron / Tavily, no runtime formula", () => {
    assert.doesNotMatch(src, /fetch\(|Nemotron|Tavily|Token Factory|POST \/polar\/chat/);
    assert.doesNotMatch(src, /0\.30?\s*\*\s*(loa|L\b)/i);
    assert.doesNotMatch(src, /max\(\s*12\b/);
    assert.match(src, /Cruise = today's E1 constants/);
  });
});

describe("three profiles, one number per threshold", () => {
  it("exposes coastal | cruise | ocean and defaults to cruise", () => {
    assert.deepEqual([...PROFILES], ["coastal", "cruise", "ocean"]);
    assert.equal(DEFAULT_PROFILE, "cruise");
    assert.equal(DEFAULT_ORDERS.profile, "cruise");
    assert.equal(resolveOrders(null).profile, "cruise");
    assert.equal(resolveOrders({ profile: "tableur" }).profile, "cruise");
    assert.equal(resolveOrders({ profile: "ocean" }).profile, "ocean");
  });

  it("cruise equals today's E1 constants (tests E1 stay green)", () => {
    const v = DEFAULT_ORDERS.values;
    assert.equal(v.hsAlertM, HS_ALERT_M);
    assert.equal(v.depthAlertM, DEPTH_ALERT_M);
    assert.equal(v.windShiftKt, WIND_SHIFT_KT);
    assert.equal(v.windShiftDeg, WIND_SHIFT_DEG);
    assert.equal(v.galeKt, GALE_KT);
    assert.equal(v.galeHoldKt, GALE_HOLD_KT);
    assert.equal(v.hsShiftM, HS_SHIFT_M);
    assert.equal(v.currentShiftKn, CURRENT_SHIFT_KN);
    assert.equal(v.rainMmH, RAIN_MM_H);
    assert.equal(v.rain3hMm, RAIN_3H_MM);
    assert.equal(v.marinaRefugeNm, MARINA_REFUGE_NM);
    assert.equal(v.groupNm, GROUP_NM);
    assert.equal(v.routeSampleNm, ROUTE_SAMPLE_NM);
    assert.equal(v.suivreLookaheadH, SUIVRE_LOOKAHEAD_H);
  });

  it("writes the Hs / depth cells as single numbers per profile", () => {
    assert.equal(PROFILE_TABLE.coastal.hsAlertM, 2.5);
    assert.equal(PROFILE_TABLE.cruise.hsAlertM, 3.5);
    assert.equal(PROFILE_TABLE.ocean.hsAlertM, 5.0);
    assert.equal(PROFILE_TABLE.coastal.depthAlertM, 8);
    assert.equal(PROFILE_TABLE.cruise.depthAlertM, 15);
    assert.equal(PROFILE_TABLE.ocean.depthAlertM, 5);
    assert.equal(PROFILE_TABLE.coastal.depthLabel, "plateau");
    assert.equal(PROFILE_TABLE.cruise.depthLabel, "plateau");
    assert.equal(PROFILE_TABLE.ocean.depthLabel, "talonnage");
    assert.equal(PROFILE_TABLE.ocean.windShiftKt, 16);
    assert.equal(PROFILE_TABLE.coastal.windShiftKt, 6);
  });

  it("every threshold has exactly one numeric value and a known source", () => {
    for (const profile of PROFILES) {
      const o = resolveOrders({ profile });
      const ids = new Set();
      for (const t of o.thresholds) {
        assert.equal(typeof t.value, "number", `${profile}.${t.id}`);
        assert.ok(!ids.has(t.id), `duplicate ${t.id}`);
        ids.add(t.id);
        assert.ok(!("alt" in t) && !("formula" in t) && !("fallback" in t));
        assert.ok(LLM_SOURCES.has(t.source) || t.source === "engine", `${t.id}: ${t.source}`);
      }
    }
  });

  it("gale 34 / hold 28 kn are Beaufort, locked and identical in the three profiles", () => {
    for (const profile of PROFILES) {
      const o = resolveOrders({ profile });
      const gale = o.thresholds.find((t) => t.id === "galeKt");
      const hold = o.thresholds.find((t) => t.id === "galeHoldKt");
      assert.equal(gale.value, 34);
      assert.equal(hold.value, 28);
      assert.equal(gale.source, "beaufort");
      assert.equal(gale.locked, true);
      assert.equal(hold.locked, true);
    }
  });

  it("planning speed = the polar read at the wind of the moment (GRIB in Suivre, climatology in Simulation)", () => {
    const polar = {
      boat_name: "Leopard 46",
      vmg_summary: { 12: { downwind: { speed: 8 } } },
      raw: { twa_rows: [60, 90, 120, 150], tws_cols: [6, 10, 14, 20], matrix: [[4, 6, 7, 8], [5, 7, 8.5, 10], [4.5, 6.5, 8, 10], [3.5, 5, 7, 9]] },
    };
    const still = resolveOrders({ profile: "cruise" }, { polar, mode: "suivre" });
    assert.equal(still.boat.source.planningKn, "polar", "sans vent : la VMG portant, comme avant");
    assert.equal(still.values.planningKn, 8);
    const grib = resolveOrders({ profile: "cruise" }, { polar, mode: "suivre", wind: { tws: 10, twd: 0, heading: 90, kind: "grib" } });
    assert.equal(grib.boat.source.planningKn, "grib");
    assert.equal(grib.values.planningKn, 6, "TWA 90°, 10 kn → 7 × 0,85 = 6 kn");
    assert.deepEqual(grib.boat.planningWind, { twa: 90, tws: 10 });
    assert.match(grib.thresholds.find((t) => t.id === "planningKn").rule, /polaire × vent GRIB \(10 kn, TWA 90°\)/);
    assert.ok(grib.budget.maxNm < still.budget.maxNm, "l'anticipation suit la vitesse : 36 h × 6 kn");
    const climo = resolveOrders({ profile: "cruise" }, { polar, mode: "simulation", wind: { tws: 20, twd: 180, heading: 30, kind: "climatology" } });
    assert.equal(climo.boat.source.planningKn, "climatology");
    assert.equal(climo.values.planningKn, 7.7, "TWA 150°, 20 kn → 9 × 0,85 = 7,7 kn");
    // A calm reads 0 in the table: the skipper still plans at the floor.
    const calm = resolveOrders({ profile: "cruise" }, { polar, mode: "suivre", wind: { tws: 0, twd: 0, heading: 90, kind: "grib" } });
    assert.equal(calm.values.planningKn, 3);
    // No polar table (VMG summary only): wind is ignored, VMG speaks.
    const summaryOnly = resolveOrders({ profile: "cruise" }, { polar: { vmg_summary: polar.vmg_summary }, wind: { tws: 10, twd: 0, heading: 90 } });
    assert.equal(summaryOnly.boat.source.planningKn, "polar");
  });

  it("revue du 19 sept. : the skipper may move the gale (Expert) and type the boat's length / draft", () => {
    const o = resolveOrders({ profile: "cruise", expert: { galeKt: 30, galeHoldKt: 32 }, boat: { loaM: 12, draftM: 2.1 } });
    assert.equal(o.values.galeKt, 30);
    assert.equal(o.values.galeHoldKt, 26, "the hold always sits 4 kn under a gale typed too high");
    const gale = o.thresholds.find((t) => t.id === "galeKt");
    assert.equal(gale.source, "expert");
    assert.equal(gale.locked, false);
    assert.equal(o.boat.loaM, 12);
    assert.equal(o.boat.draftM, 2.1);
    assert.equal(o.boat.source.loa, "skipper");
    assert.equal(o.boat.source.draft, "skipper");
    // Bounds keep the engine sane; the polar still names the boat.
    const wild = resolveOrders({ profile: "cruise", boat: { loaM: 400, draftM: -2 } }, { polar: { boat_name: "Leopard 46", loa_m: 14 } });
    assert.equal(wild.boat.loaM, 60);
    assert.equal(wild.boat.draftM, 1.4, "a negative draft is ignored: the polar / default speaks");
    assert.equal(wild.boat.name, "Leopard 46");
  });

  it("marks the ocean wind step as WMO squall, the others as usage", () => {
    assert.equal(resolveOrders({ profile: "ocean" }).thresholds.find((t) => t.id === "windShiftKt").source, "wmo");
    assert.equal(resolveOrders({ profile: "cruise" }).thresholds.find((t) => t.id === "windShiftKt").source, "usage");
  });

  it("carries the resolved Hs rule for the LLM, never a formula", () => {
    const hs = resolveOrders({ profile: "cruise" }).thresholds.find((t) => t.id === "hsAlertM");
    assert.equal(hs.value, 3.5);
    assert.match(hs.rule, /Croisière E1 3,5 m/);
    assert.doesNotMatch(hs.rule, /0,30|×\s*L/);
  });

  it("thresholdValues falls back to cruise when orders are missing", () => {
    assert.equal(thresholdValues(null).hsAlertM, 3.5);
    assert.equal(thresholdValues({}).depthAlertM, 15);
    assert.equal(thresholdValues(resolveOrders({ profile: "coastal" })).hsAlertM, 2.5);
  });
});

describe("rain is Suivre only", () => {
  it("disables rain / refuge in simulation with the reason, keeps them in suivre", () => {
    const sim = resolveOrders({ profile: "cruise" }, { mode: "simulation" });
    assert.equal(sim.rainEnabled, false);
    assert.equal(sim.rainReason, "simulation_no_rain");
    const rain = sim.thresholds.find((t) => t.id === "rainMmH");
    assert.equal(rain.value, 4);
    assert.equal(rain.enabled, false);
    assert.equal(rain.reason, "simulation_no_rain");

    const suivre = resolveOrders({ profile: "cruise" }, { mode: "suivre" });
    assert.equal(suivre.rainEnabled, true);
    assert.equal(suivre.thresholds.find((t) => t.id === "marinaRefugeNm").enabled, true);
  });
});

describe("lookahead budget — the horizon never lies (§2.6)", () => {
  it("derives nm = H × kn and pearls = ceil(nm / 12) for 24 / 36 / 48 h", () => {
    const coastal = lookaheadBudget(resolveOrders({ profile: "coastal" }));
    assert.deepEqual(
      [coastal.hours, coastal.planningKn, coastal.maxNm, coastal.maxPearls],
      [24, 5, 120, 10],
    );
    const cruise = lookaheadBudget(resolveOrders({ profile: "cruise" }));
    assert.deepEqual(
      [cruise.hours, cruise.planningKn, cruise.maxNm, cruise.maxPearls],
      [36, 7, 252, 21],
    );
    const ocean = lookaheadBudget(resolveOrders({ profile: "ocean" }));
    assert.deepEqual(
      [ocean.hours, ocean.planningKn, ocean.maxNm, ocean.maxPearls],
      [48, 7, 336, 28],
    );
  });

  it("follows a fast polar: 48 h × 10 kn = 480 nm / 40 pearls, never the old 350 / 24 cap", () => {
    const fast = { ...berryPolar, vmg_summary: { 12: { downwind: { speed: 10 } } } };
    const b = lookaheadBudget(resolveOrders({ profile: "ocean" }, { polar: fast }));
    assert.equal(b.planningKn, 10);
    assert.equal(b.maxNm, 480);
    assert.equal(b.maxPearls, 40);
    assert.ok(b.maxNm > 350);
    assert.ok(b.maxPearls > 24);
  });

  it("exposes the derived numbers as thresholds with source derive", () => {
    const o = resolveOrders({ profile: "ocean" });
    const nm = o.thresholds.find((t) => t.id === "suivreLookaheadMaxNm");
    const pearls = o.thresholds.find((t) => t.id === "maxPearlsSuivre");
    assert.equal(nm.value, 336);
    assert.equal(nm.source, "derive");
    assert.equal(pearls.value, 28);
    assert.equal(pearls.source, "derive");
  });

  it("falls back to the cruise budget without orders", () => {
    assert.equal(lookaheadBudget(null).maxNm, 252);
    assert.equal(lookaheadBudget(undefined).maxPearls, 21);
  });
});

describe("boat is read from the polar, never typed", () => {
  it("reads the name and planning speed from the polar, Berry defaults for L / draft", () => {
    const o = resolveOrders({ profile: "cruise" }, { polar: berryPolar });
    assert.equal(o.boat.name, "Leopard 46");
    assert.equal(o.boat.loaM, 14);
    assert.equal(o.boat.draftM, 1.4);
    assert.equal(o.boat.planningKn, 9);
    assert.equal(o.boat.source.loa, "default");
    assert.equal(o.boat.source.planningKn, "polar");
    assert.equal(o.values.planningKn, 9);
    assert.equal(o.budget.maxNm, 324);
  });

  it("uses the profile speed when the polar has no VMG table", () => {
    const o = resolveOrders({ profile: "coastal" }, { polar: { boat_name: "Dinghy" } });
    assert.equal(o.boat.planningKn, null);
    assert.equal(o.values.planningKn, 5);
    assert.equal(o.boat.source.planningKn, "profile");
  });

  it("proposes coastal for a small polar (L < 11 m or draft < 1.1 m) without forcing it", () => {
    const small = readBoat({ boat_name: "First 31.7", loa_m: 9.6, draft_m: 1.9 });
    assert.deepEqual(suggestProfileForBoat(small), { profile: "coastal", reason: "small_loa" });
    const o = resolveOrders({ profile: "cruise" }, { polar: { boat_name: "First 31.7", loa_m: 9.6 } });
    assert.equal(o.profile, "cruise");
    assert.equal(o.suggest?.profile, "coastal");
    assert.equal(resolveOrders({ profile: "coastal" }, { polar: { loa_m: 9.6 } }).suggest, null);
  });

  it("never proposes on the Berry defaults (nothing was read)", () => {
    assert.equal(suggestProfileForBoat(readBoat(null)), null);
    assert.equal(resolveOrders({ profile: "cruise" }, { polar: berryPolar }).suggest, null);
  });
});

describe("thresholdsForEvent → used", () => {
  it("cites only the ids that made the event switch, one value per id", () => {
    const o = resolveOrders({ profile: "cruise" }, { mode: "suivre" });
    assert.deepEqual(thresholdsForEvent("wind-gale", o).map((u) => u.id), ["galeKt", "galeHoldKt"]);
    assert.deepEqual(
      thresholdsForEvent("marina-refuge", o).map((u) => u.id),
      ["rainMmH", "rain3hMm", "marinaRefugeNm"],
    );
    assert.deepEqual(thresholdsForEvent("depth-alert", o).map((u) => u.id), ["depthAlertM"]);
    assert.deepEqual(thresholdsForEvent("wind-shift", o).map((u) => u.id), ["windShiftKt", "windShiftDeg"]);
    assert.deepEqual(thresholdsForEvent("zee-enter", o), []);
    for (const u of thresholdsForEvent("wx-alert", o)) {
      assert.equal(typeof u.value, "number");
      assert.ok(LLM_SOURCES.has(u.source));
    }
  });

  it("gives the LLM the resolved Hs number and its rule", () => {
    const used = thresholdsForEvent("hs-shift", resolveOrders({ profile: "cruise" }), { hs: 3.6, alert: true });
    const hs = used.find((u) => u.id === "hsAlertM");
    assert.deepEqual(
      { id: hs.id, value: hs.value, unit: hs.unit, source: hs.source },
      { id: "hsAlertM", value: 3.5, unit: "m", source: "usage" },
    );
    assert.match(hs.rule, /Croisière E1 3,5 m/);
    const quiet = thresholdsForEvent("hs-shift", resolveOrders({ profile: "cruise" }), { dHs: 1.2, alert: false });
    assert.deepEqual(quiet.map((u) => u.id), ["hsShiftM"]);
  });

  it("never cites rain in simulation", () => {
    const sim = resolveOrders({ profile: "cruise" }, { mode: "simulation" });
    assert.deepEqual(thresholdsForEvent("marina-refuge", sim), []);
    assert.ok(!thresholdsForEvent("wx-alert", sim).some((u) => u.id.startsWith("rain")));
    const suivre = resolveOrders({ profile: "cruise" }, { mode: "suivre" });
    assert.ok(thresholdsForEvent("wx-alert", suivre, { rain: true }).some((u) => u.id === "rainMmH"));
  });

  it("freezes a skipper snapshot in the plan's JSON shape", () => {
    const snap = skipperSnapshot("hs-shift", resolveOrders({ profile: "cruise" }, { polar: berryPolar }), { alert: true });
    assert.equal(snap.profile, "cruise");
    assert.equal(snap.profile_phrase, "Ordres Berry — croisière.");
    assert.equal(snap.comfort, "normal");
    assert.deepEqual(snap.boat, { name: "Leopard 46", loaM: 14, draftM: 1.4 });
    assert.ok(snap.used.some((u) => u.id === "hsAlertM" && u.value === 3.5));
    assert.ok(!("tavily" in snap) && !("nvidia" in snap));
  });
});

describe("phrases FR / EN", () => {
  it("writes the living example under two lines, with the skipper's numbers", () => {
    const o = resolveOrders({ profile: "cruise" });
    const fr = exampleLine(o, { tws: 18, hs: 1.4 }, "fr");
    assert.equal(fr, "Vent ici 18 kn — je me tais. À 34 kn je parle. Mer 1,4 m — sous 3,5 m.");
    const en = exampleLine(o, { tws: 18, hs: 1.4 }, "en");
    assert.equal(en, "Wind here 18 kn — I stay quiet. At 34 kn I speak. Sea 1.4 m — under 3.5 m.");
    assert.ok(!fr.includes("\n"));
  });

  it("changes with the profile, gale does not", () => {
    const ocean = exampleLine(resolveOrders({ profile: "ocean" }), { tws: 36, hs: 4.2 }, "fr");
    assert.match(ocean, /coup de vent, je parle/);
    assert.match(ocean, /Mer 4,2 m — sous 5,0 m/);
    const coastal = exampleLine(resolveOrders({ profile: "coastal" }), { tws: 12, hs: 2.7, depthM: 6 }, "fr");
    assert.match(coastal, /au-dessus de 2,5 m, je parle/);
    assert.match(coastal, /Fond 6 m — sous 8 m, on approche du plateau/);
  });

  it("stays honest without a bag: a null is unknown, never 0 kn / 0 m", () => {
    const o = resolveOrders({ profile: "cruise" });
    const none = "Pas encore de sac ici. Je parle à 34 kn, mer 3,5 m, fond 15 m.";
    assert.equal(exampleLine(o, {}, "fr"), none);
    assert.equal(exampleLine(o, null, "fr"), none);
    assert.equal(exampleLine(o, { tws: null, hs: null, depthM: null }, "fr"), none);
    assert.equal(exampleLine(o, { tws: undefined, hs: "", depthM: null }, "fr"), none);
    assert.equal(exampleLine(o, { tws: null, hs: 1.4 }, "fr"), "Mer 1,4 m — sous 3,5 m.");
    assert.equal(exampleLine(o, { tws: 0, hs: null }, "fr"), "Vent ici 0 kn — je me tais. À 34 kn je parle.");
  });

  it("writes the cyan orders line and the depth phrase per profile", () => {
    assert.equal(ordersLine(resolveOrders({ profile: "cruise" }), "fr"), "Ordres : croisière · Hs 3,5 m · fond 15 m");
    assert.equal(ordersLine(resolveOrders({ profile: "ocean" }), "en"), "Orders: offshore · Hs 5.0 m · depth 5 m");
    assert.match(depthPhrase(12, resolveOrders({ profile: "cruise" }), "fr"), /^On approche du plateau : 12 m sondés, sous 15 m\./);
    assert.match(depthPhrase(4, resolveOrders({ profile: "ocean" }), "fr"), /^Risque de talonner : 4 m sondés, sous 5 m\./);
    assert.match(depthPhrase(4, resolveOrders({ profile: "ocean" }), "en"), /^Grounding risk/);
  });
});

describe("persistence — tab + localStorage, same key since v1", () => {
  it("uses the v1 key; stores the character, and S6 / S7 knobs only when they differ", () => {
    assert.equal(STORAGE_KEY, "ng.sim.skipperOrders.v1");
    const mem = memStorage();
    assert.equal(writeSavedOrders(mem, { profile: "ocean", loaM: 9, draftM: 1 }), true);
    assert.deepEqual(JSON.parse(mem.dump()[STORAGE_KEY]), { profile: "ocean" });
    assert.deepEqual(readSavedOrders(mem), { profile: "ocean" });
    assert.equal(writeSavedOrders(mem, { profile: "ocean", comfort: "hard", horizonH: 24, expert: { galePct: 20, loaM: 9 } }), true);
    assert.deepEqual(readSavedOrders(mem), { profile: "ocean", comfort: "hard", horizonH: 24, expert: { galePct: 20 } });
    assert.equal(writeSavedOrders(mem, { profile: "ocean", boat: { loaM: 9, draftM: "nope" } }), true);
    assert.deepEqual(readSavedOrders(mem), { profile: "ocean", boat: { loaM: 9 } });
    // normal comfort, unknown horizon, empty expert are not written (v1 shape stays)
    assert.deepEqual(sanitizeSaved({ profile: "cruise", comfort: "normal", horizonH: 30, expert: { nope: 1 } }), { profile: "cruise" });
  });

  it("returns cruise when nothing or garbage is stored, and reset clears", () => {
    assert.equal(readSavedOrders(memStorage()), null);
    assert.equal(resolveOrders(readSavedOrders(memStorage())).profile, "cruise");
    const bad = memStorage({ [STORAGE_KEY]: "{not json" });
    assert.equal(readSavedOrders(bad), null);
    const mem = memStorage({ [STORAGE_KEY]: JSON.stringify({ profile: "coastal" }) });
    assert.equal(clearSavedOrders(mem), true);
    assert.equal(readSavedOrders(mem), null);
    assert.equal(readSavedOrders(null), null);
    assert.equal(writeSavedOrders(null, { profile: "ocean" }), true);
  });
});

describe("POLAR_EFFICIENCY on planningSpeedFor", () => {
  const raw = {
    twa_rows: [60, 90, 120, 150],
    tws_cols: [6, 10, 14, 20],
    matrix: [[4, 6, 7, 8], [5, 7, 8.5, 10], [4.5, 6.5, 8, 10], [3.5, 5, 7, 9]],
  };

  it("defaults to 0.85 and multiplies the polar table", () => {
    assert.equal(POLAR_EFFICIENCY, 0.85);
    const p = planningSpeedFor({ raw }, { tws: 10, twd: 0, heading: 90, kind: "grib" });
    assert.equal(p.kn, 6);
    assert.equal(p.source, "grib");
    assert.equal(p.twa, 90);
  });

  it("keeps the 3 kn floor after the efficiency factor", () => {
    const p = planningSpeedFor({ raw }, { tws: 0, twd: 0, heading: 90, kind: "grib" });
    assert.equal(p.kn, 3);
  });
});

describe("S6 — Comfort: soft / normal / hard", () => {
  it("exposes three steps; normal changes nothing (v1 numbers stay)", () => {
    assert.deepEqual([...COMFORTS], ["soft", "normal", "hard"]);
    const normal = resolveOrders({ profile: "cruise", comfort: "normal" });
    assert.deepEqual(normal.values, DEFAULT_ORDERS.values);
    assert.equal(resolveOrders({ profile: "cruise", comfort: "tableur" }).comfort, "normal");
  });

  it("moves only the notable wind and one notch of Hs — never the gale, never depth", () => {
    for (const profile of PROFILES) {
      const base = resolveOrders({ profile });
      const soft = resolveOrders({ profile, comfort: "soft" });
      const hard = resolveOrders({ profile, comfort: "hard" });
      assert.equal(soft.values.hsAlertM, Math.round((base.values.hsAlertM - 0.5) * 10) / 10);
      assert.equal(hard.values.hsAlertM, Math.round((base.values.hsAlertM + 0.5) * 10) / 10);
      assert.equal(hard.values.windShiftDeg, base.values.windShiftDeg + 15);
      assert.equal(soft.values.windShiftKt, Math.max(base.values.windShiftKt - 2, base.values.windShiftResetKt));
      for (const o of [soft, hard]) {
        assert.equal(o.values.galeKt, 34);
        assert.equal(o.values.galeHoldKt, 28);
        assert.equal(o.values.depthAlertM, base.values.depthAlertM);
        assert.equal(o.values.hsShiftM, base.values.hsShiftM);
        assert.equal(o.values.rainMmH, base.values.rainMmH);
      }
    }
    assert.equal(COMFORT_TABLE.hard.windShiftKt, 4);
    assert.equal(COMFORT_TABLE.soft.hsAlertM, -0.5);
  });

  it("caps the coastal / cruise wind step under the WMO squall; ocean may go above", () => {
    assert.equal(COMFORT_WIND_CAP_KT, 16);
    assert.ok(resolveOrders({ profile: "cruise", comfort: "hard" }).values.windShiftKt <= 16);
    assert.ok(resolveOrders({ profile: "coastal", comfort: "hard" }).values.windShiftKt <= 16);
    assert.equal(resolveOrders({ profile: "ocean", comfort: "hard" }).values.windShiftKt, 20);
  });

  it("tells the LLM that comfort spoke, and the cyan line names it", () => {
    const hard = resolveOrders({ profile: "cruise", comfort: "hard" });
    const hs = hard.thresholds.find((t) => t.id === "hsAlertM");
    assert.match(hs.rule, /confort dur/);
    assert.equal(hs.source, "usage");
    assert.equal(skipperSnapshot("hs-shift", hard, { alert: true }).comfort, "hard");
    assert.equal(ordersLine(hard, "fr"), "Ordres : croisière · dur · Hs 4,0 m · fond 15 m");
    assert.equal(ordersLine(DEFAULT_ORDERS, "fr"), "Ordres : croisière · Hs 3,5 m · fond 15 m");
    assert.equal(hard.comfortPhrase.fr, "Je laisse passer plus.");
  });
});

describe("S6 — horizon knob: the horizon never lies", () => {
  it("offers 24 / 36 / 48 h and the budget follows the chosen H", () => {
    assert.deepEqual([...HORIZONS_H], [24, 36, 48]);
    const o = resolveOrders({ profile: "cruise", horizonH: 48 }, { mode: "suivre" });
    assert.equal(o.knobs.horizonH, 48);
    assert.equal(o.knobs.horizonDefaultH, 36);
    assert.equal(o.budget.hours, 48);
    assert.equal(o.budget.maxNm, 336);
    assert.equal(o.budget.maxPearls, 28);
    assert.equal(o.values.suivreLookaheadH, 48);
    assert.equal(o.thresholds.find((t) => t.id === "suivreLookaheadH").rule, "horizon choisi par le skipper");
    assert.equal(lookaheadBudget(o).maxNm, 336);
  });

  it("ignores an unknown horizon and falls back to the profile's", () => {
    assert.equal(resolveOrders({ profile: "ocean", horizonH: 30 }).knobs.horizonH, 48);
    assert.equal(resolveOrders({ profile: "coastal" }).budget.hours, 24);
  });
});

describe("S7 — Expert drawer: a few numbers, clamped, cited as expert", () => {
  it("lists only engine numbers the detectors really read, never the gale", () => {
    assert.ok(EXPERT_IDS.length >= 10);
    assert.ok(EXPERT_IDS.includes("galeKt") && EXPERT_IDS.includes("galeHoldKt"), "revue du 19 sept. : le coup de vent se règle");
    assert.ok(!EXPERT_IDS.includes("hsAlertM") && !EXPERT_IDS.includes("depthAlertM"));
    const here = dirname(fileURLToPath(import.meta.url));
    const engine = readFileSync(join(here, "eventRules.js"), "utf8")
      + readFileSync(join(here, "iciAlong.js"), "utf8")
      + readFileSync(join(here, "displayJudge.js"), "utf8")
      + readFileSync(join(here, "..", "hooks", "useIciDossier.js"), "utf8");
    for (const id of EXPERT_IDS) {
      assert.match(engine, new RegExp(`\\b${id}\\b`), `${id} is read by the engine`);
      assert.ok(EXPERT_FIELDS[id].min < EXPERT_FIELDS[id].max);
    }
  });

  it("clamps to the bounds and drops garbage", () => {
    assert.equal(clampExpert("galePct", 99), 50);
    assert.equal(clampExpert("galePct", "12"), 12);
    assert.equal(clampExpert("galePct", ""), null);
    assert.equal(clampExpert("galePct", null), null);
    assert.equal(clampExpert("loaM", 9), null);
    assert.equal(clampExpert("currentIgnoreKn", 0.05), 0.1);
  });

  it("overrides the profile number, flags source expert, and the LLM gets that value", () => {
    const o = resolveOrders({ profile: "cruise", expert: { marinaRefugeNm: 60, galePct: 25 } }, { mode: "suivre" });
    assert.equal(o.values.marinaRefugeNm, 60);
    assert.equal(o.values.galePct, 25);
    const t = o.thresholds.find((x) => x.id === "marinaRefugeNm");
    assert.equal(t.source, "expert");
    assert.match(t.rule, /Expert/);
    const used = thresholdsForEvent("marina-refuge", o, {});
    assert.equal(used.find((u) => u.id === "marinaRefugeNm").value, 60);
    assert.equal(used.find((u) => u.id === "marinaRefugeNm").source, "expert");
    assert.deepEqual(o.expert, { marinaRefugeNm: 60, galePct: 25 });
    assert.equal(ordersLine(o, "fr"), "Ordres : croisière · Hs 3,5 m · fond 15 m · 2 expert");
  });

  it("without expert the numbers are the profile's and thresholdValues stays E1 for cruise", () => {
    assert.deepEqual(resolveOrders({ profile: "cruise", expert: {} }).expert, {});
    assert.equal(thresholdValues(resolveOrders({ profile: "cruise", expert: { nope: 3 } })).galePct, 15);
  });
});

describe("coastal phrase, Hs and depth, advice under 12 m", () => {
  it("keeps the coastal phrase and the Hs 2,5 m · fond 8 m line", () => {
    assert.equal(PROFILE_TABLE.coastal.phrase.fr, "Je parle tôt.");
    assert.equal(PROFILE_TABLE.coastal.phrase.en, "I speak early.");
    assert.equal(PROFILE_TABLE.coastal.hsAlertM, 2.5);
    assert.equal(PROFILE_TABLE.coastal.depthAlertM, 8);
    const line = ordersLine(resolveOrders({ profile: "coastal" }), "fr");
    assert.match(line, /Hs 2,5 m · fond 8 m/);
    const panel = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "components", "SkipperOrdersPanel.jsx"), "utf8");
    assert.match(panel, /data-testid="skipper-phrase"/);
    assert.match(panel, /orders\.phrase\.fr/);
    assert.match(panel, /fond \$\{T\.depthAlertM\} m/);
    assert.match(panel, /data-testid="skipper-orders-line"/);
  });

  it("advises coastal for a polar shorter than 12 m", () => {
    assert.equal(SMALL_BOAT_LOA_M, 12);
    assert.equal(COASTAL_SUGGEST_RULE, "Côtier conseillé pour < 12 m");
    const under = readBoat({ boat_name: "First 36", loa_m: 11.5, draft_m: 1.9 });
    assert.deepEqual(suggestProfileForBoat(under), { profile: "coastal", reason: "small_loa" });
    const atLimit = readBoat({ boat_name: "Twelve", loa_m: 12, draft_m: 1.9 });
    assert.equal(suggestProfileForBoat(atLimit), null);
    const fr = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "i18n", "fr.js"), "utf8");
    assert.match(fr, /skipperCoastalRule:\s*"Côtier conseillé pour < 12 m"/);
  });
});
