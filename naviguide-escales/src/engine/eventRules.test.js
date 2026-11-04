import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  detectEvents,
  emptyEventMemory,
  nearestHarbour,
  readWind,
  smallestAngleDeg,
  sumRainHours,
  WIND_SHIFT_KT,
  GALE_KT,
  RAIN_MM_H,
} from "./eventRules.js";
import { resolveOrders } from "./skipperOrders.js";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "eventRules.js"), "utf8");

function bag(extra = {}) {
  return {
    zee: extra.zee === undefined ? { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true } : extra.zee,
    poe: extra.poe || [],
    amp: extra.amp || [],
    nearby: extra.nearby || { marinas: [], capitaineries: [], wpi: [] },
    weather: extra.weather ?? null,
    climatology: extra.climatology ?? null,
    emodnet: extra.emodnet ?? null,
    depthOffshore: extra.depthOffshore ?? null,
  };
}

function forecastWind(tws, twd = 240, extra = {}) {
  return {
    kind: "forecast",
    model: "GFS 0.25°",
    wind: { kind: "forecast", speedKnots: tws, dirFromDeg: twd },
    wave: extra.hs != null ? { kind: "forecast", hs: extra.hs } : null,
    current: extra.current || null,
  };
}

function climoWind(tws, twd = 55, extra = {}) {
  return {
    kind: "climatology",
    source: "atlas",
    month: 6,
    point: {
      kind: "climatology",
      wind_atlas: { most_likely: { speed_knots: tws, dir_deg: twd } },
      wave: extra.wave || null,
      current: extra.current || null,
    },
    rose: extra.galePct != null ? { gale_pct: extra.galePct } : undefined,
  };
}

function run(steps, { mode = "suivre", along = null, startMem } = {}) {
  let memory = startMem || emptyEventMemory("LR→Ajaccio");
  let prev = undefined;
  let last = { events: [], memory };
  for (const step of steps) {
    const { at, ctx = {} } = step;
    last = detectEvents({
      at,
      prev,
      along,
      ctx: { mode, legId: "LR→Ajaccio", cumNm: 0, clockMin: 0, ...ctx },
      memory,
    });
    memory = last.memory;
    prev = at;
  }
  return last;
}

function types(result) {
  return result.events.map((e) => e.type);
}

describe("eventRules helpers", () => {
  it("smallest angle wraps around 360", () => {
    assert.equal(smallestAngleDeg(350, 10), 20);
    assert.equal(smallestAngleDeg(10, 50), 40);
    assert.equal(smallestAngleDeg(null, 10), null);
  });

  it("sums GRIB rain over the next 3 hours", () => {
    const samples = [
      { t: "2026-05-15T08:00:00Z", rainMm: 2 },
      { t: "2026-05-15T09:00:00Z", rainMm: 5 },
      { t: "2026-05-15T10:00:00Z", rainMm: 4 },
      { t: "2026-05-15T14:00:00Z", rainMm: 9 },
    ];
    assert.equal(sumRainHours(samples, "2026-05-15T08:00:00Z", 3), 11);
    assert.equal(sumRainHours([], "2026-05-15T08:00:00Z", 3), null);
  });

  it("picks the closest harbour, preferring the along-track list", () => {
    const dossier = bag({
      nearby: { marinas: [{ name: "Côté", nm: 8 }], capitaineries: [], wpi: [] },
    });
    const along = { harbours: [{ name: "Sur le trait", nm: 12 }] };
    assert.equal(nearestHarbour(dossier, along).name, "Sur le trait");
    assert.equal(nearestHarbour(dossier, null).name, "Côté");
    assert.equal(nearestHarbour(bag(), null), null);
  });

  it("does not mix forecast wind with climatology", () => {
    const follow = readWind(bag({ weather: forecastWind(12, 200) }), { mode: "suivre" });
    const sim = readWind(bag({ climatology: climoWind(16, 55) }), { mode: "simulation" });
    assert.equal(follow.kind, "forecast");
    assert.equal(sim.kind, "climatology");
    const mixed = readWind(bag({ weather: forecastWind(12) }), { mode: "simulation" });
    assert.equal(mixed, null);
  });

  it("keeps tavily and nvidia null and never calls a provider", () => {
    assert.match(src, /tavily: null/);
    assert.match(src, /nvidia: null/);
    assert.doesNotMatch(src, /Token Factory|enqueueStory|Nemotron/);
    assert.match(src, /No Tavily \/ NVIDIA/);
  });
});

describe("detectEvents ZEE / AMP", () => {
  it("first bag does not emit zee-enter (prev undefined)", () => {
    const r = run([{ at: bag() }]);
    assert.deepEqual(types(r), []);
  });

  it("needs two consecutive bags before zee-enter", () => {
    const france = bag();
    const spain = bag({ zee: { name: "Spanish Exclusive Economic Zone", mrgid: 8462 } });
    const once = run([{ at: france }, { at: spain }]);
    assert.deepEqual(types(once), []);
    const twice = run([{ at: france }, { at: spain }, { at: spain }]);
    assert.deepEqual(types(twice), ["zee-enter"]);
    assert.equal(twice.events[0].payload.zee.mrgid, 8462);
    assert.equal(twice.events[0].payload.tavily, null);
    assert.equal(twice.events[0].payload.nvidia, null);
  });

  it("does not repeat the same mrgid on the same leg", () => {
    const france = bag();
    const spain = bag({ zee: { name: "Spanish Exclusive Economic Zone", mrgid: 8462 } });
    const r = run([
      { at: france },
      { at: spain },
      { at: spain },
      { at: spain },
    ]);
    assert.deepEqual(types(r), []);
  });

  it("emits zee-exit once when mrgid becomes null", () => {
    const france = bag();
    const high = bag({ zee: null });
    const r = run([{ at: france }, { at: high }]);
    assert.deepEqual(types(r), ["zee-exit"]);
    const again = run([{ at: france }, { at: high }, { at: high }]);
    assert.deepEqual(types(again), []);
  });

  it("confirms amp-enter on the second bag, not the first sighting", () => {
    const empty = bag({ amp: [] });
    const amp = {
      name: "Pertuis",
      site_id: "ps-1",
      nm: 8,
      visit_url: "https://parc-marin.fr/visite",
      manager_url: "https://parc-marin.fr",
    };
    const once = run([{ at: empty }, { at: bag({ amp: [amp] }) }]);
    assert.deepEqual(types(once), []);
    const twice = run([
      { at: empty },
      { at: bag({ amp: [amp] }) },
      { at: bag({ amp: [amp] }) },
    ]);
    assert.deepEqual(types(twice), ["amp-enter"]);
    assert.equal(twice.events[0].payload.visitable, true);
  });

  it("skips marine events during an air hop", () => {
    const france = bag();
    const spain = bag({ zee: { name: "Spain", mrgid: 8462 } });
    const r = run(
      [{ at: france }, { at: spain }, { at: spain }],
      { startMem: emptyEventMemory("air") },
    );
    const air = detectEvents({
      at: spain,
      prev: france,
      ctx: { mode: "suivre", airHop: true, legId: "air" },
      memory: emptyEventMemory("air"),
    });
    assert.deepEqual(types(air), []);
    assert.ok(r);
  });
});

describe("detectEvents wind / current / Hs", () => {
  it("fires wind-shift at +8 kt same kind", () => {
    const a = bag({ weather: forecastWind(10, 240) });
    const b = bag({ weather: forecastWind(10 + WIND_SHIFT_KT, 240) });
    const r = run(
      [{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 4 } }],
    );
    assert.deepEqual(types(r), ["wind-shift"]);
    assert.equal(r.events[0].payload.kind, "forecast");
    assert.equal(r.events[0].payload.dTws, 8);
  });

  it("does not invent a wind-shift by mixing GFS and atlas", () => {
    const a = bag({ weather: forecastWind(10, 240), climatology: climoWind(10, 240) });
    const b = bag({ weather: forecastWind(10, 240), climatology: climoWind(22, 240) });
    const follow = run([{ at: a }, { at: b }], { mode: "suivre" });
    assert.ok(!types(follow).includes("wind-shift"));
  });

  it("holds gale until TWS drops under 28 kt", () => {
    const a = bag({ weather: forecastWind(20, 200) });
    const b = bag({ weather: forecastWind(GALE_KT, 200) });
    const c = bag({ weather: forecastWind(30, 200) });
    const d = bag({ weather: forecastWind(20, 200) });
    const first = run([{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 5 } }]);
    assert.ok(types(first).includes("wind-gale"));
    const hold = run([
      { at: a, ctx: { cumNm: 0 } },
      { at: b, ctx: { cumNm: 5 } },
      { at: c, ctx: { cumNm: 10 } },
    ]);
    assert.ok(!types(hold).includes("wind-gale"));
    const reset = run([
      { at: a, ctx: { cumNm: 0 } },
      { at: b, ctx: { cumNm: 5 } },
      { at: d, ctx: { cumNm: 12 } },
      { at: b, ctx: { cumNm: 30 } },
    ]);
    assert.ok(types(reset).includes("wind-gale"));
  });

  it("fires current-shift on inversion, ignores both < 0.3 kn", () => {
    const lowA = bag({
      weather: {
        kind: "forecast",
        current: { kind: "forecast", speedKnots: 0.1, dirToDeg: 10, source: "noaa-rtofs" },
      },
    });
    const lowB = bag({
      weather: {
        kind: "forecast",
        current: { kind: "forecast", speedKnots: 0.2, dirToDeg: 200, source: "noaa-rtofs" },
      },
    });
    const quiet = run([{ at: lowA }, { at: lowB }]);
    assert.ok(!types(quiet).includes("current-shift"));

    const a = bag({
      weather: {
        kind: "forecast",
        current: { kind: "forecast", speedKnots: 0.8, dirToDeg: 10, source: "noaa-rtofs" },
      },
    });
    const b = bag({
      weather: {
        kind: "forecast",
        current: { kind: "forecast", speedKnots: 0.9, dirToDeg: 190, source: "noaa-rtofs" },
      },
    });
    const flip = run([{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 3 } }]);
    assert.deepEqual(types(flip), ["current-shift"]);
    assert.equal(flip.events[0].payload.invert, true);
  });

  it("fires hs-shift at 3.5 m", () => {
    const a = bag({ weather: forecastWind(12, 200, { hs: 1.2 }) });
    const b = bag({ weather: forecastWind(12, 200, { hs: 3.5 }) });
    const r = run([{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 4 } }]);
    assert.ok(types(r).includes("hs-shift"));
    assert.ok(types(r).includes("wx-alert"));
    assert.equal(r.events.find((e) => e.type === "hs-shift").payload.alert, true);
  });
});

describe("detectEvents wx / marina / depth", () => {
  it("Suivre + rain ≥ 4 + port → marina-refuge and wx-alert", () => {
    const at = bag({
      nearby: { marinas: [{ name: "Port des Minimes", nm: 6 }], capitaineries: [], wpi: [] },
    });
    const r = run([
      { at, ctx: { rainMm: RAIN_MM_H + 2, cumNm: 10, clockMin: 60 } },
    ]);
    assert.ok(types(r).includes("wx-alert"));
    assert.ok(types(r).includes("marina-refuge"));
    const marina = r.events.find((e) => e.type === "marina-refuge");
    assert.equal(marina.payload.harbour.name, "Port des Minimes");
    assert.equal(marina.payload.tavily, null);
  });

  it("Suivre + rain without harbour → wx-alert only", () => {
    const r = run([{ at: bag(), ctx: { rainMm: 6 } }]);
    assert.deepEqual(types(r), ["wx-alert"]);
  });

  it("Simulation never emits marina-refuge from rain", () => {
    const at = bag({
      nearby: { marinas: [{ name: "Minimes", nm: 4 }], capitaineries: [], wpi: [] },
      climatology: climoWind(12, 80),
    });
    const r = run(
      [{ at, ctx: { rainMm: 12, rain3hMm: 20 } }],
      { mode: "simulation" },
    );
    assert.ok(!types(r).includes("marina-refuge"));
    assert.ok(!types(r).includes("wx-alert"));
  });

  it("Simulation can still alert on climatology gale", () => {
    const a = bag({ climatology: climoWind(16, 80, { galePct: 4 }) });
    const b = bag({ climatology: climoWind(16, 80, { galePct: 18 }) });
    const r = run(
      [{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 4 } }],
      { mode: "simulation" },
    );
    assert.ok(types(r).includes("wind-gale"));
    assert.ok(types(r).includes("wx-alert"));
    assert.ok(!types(r).includes("marina-refuge"));
  });

  it("depth-alert on EMODnet DTM under 15 m", () => {
    const r = run([{
      at: bag({ emodnet: { kind: "observation", bathy: { depth_m: 12.4 } } }),
      ctx: { cumNm: 20 },
    }]);
    assert.deepEqual(types(r), ["depth-alert"]);
    assert.equal(r.events[0].payload.source, "emodnet");
    assert.equal(r.events[0].kind, "observation");
  });
});

describe("skipper orders drive the thresholds (S2)", () => {
  const coastal = resolveOrders({ profile: "coastal" }, { mode: "suivre" });
  const cruise = resolveOrders({ profile: "cruise" }, { mode: "suivre" });
  const ocean = resolveOrders({ profile: "ocean" }, { mode: "suivre" });

  it("without orders every event is detected under Cruise and says so", () => {
    const a = bag({ weather: forecastWind(12, 200, { hs: 1.2 }) });
    const b = bag({ weather: forecastWind(12, 200, { hs: 3.5 }) });
    const r = run([{ at: a, ctx: { cumNm: 0 } }, { at: b, ctx: { cumNm: 4 } }]);
    const hs = r.events.find((e) => e.type === "hs-shift");
    assert.equal(hs.skipper.profile, "cruise");
    assert.ok(hs.skipper.used.some((u) => u.id === "hsAlertM" && u.value === 3.5));
    assert.equal(hs.payload.alertM, 3.5);
  });

  it("Coastal speaks at 2.5 m where Cruise stays quiet; Ocean waits for 5 m", () => {
    const a = bag({ weather: forecastWind(12, 200, { hs: 1.9 }) });
    const b = bag({ weather: forecastWind(12, 200, { hs: 2.7 }) });
    const steps = (orders) => [{ at: a, ctx: { cumNm: 0, orders } }, { at: b, ctx: { cumNm: 4, orders } }];
    const quiet = run(steps(cruise));
    assert.ok(!types(quiet).includes("hs-shift"));
    const early = run(steps(coastal));
    const hs = early.events.find((e) => e.type === "hs-shift");
    assert.ok(hs, "coastal fires hs-shift");
    assert.equal(hs.payload.alert, true);
    assert.equal(hs.payload.alertM, 2.5);
    assert.equal(hs.skipper.profile, "coastal");
    assert.ok(hs.skipper.used.some((u) => u.id === "hsAlertM" && u.value === 2.5));
    const oceanBig = run([
      { at: bag({ weather: forecastWind(12, 200, { hs: 2.0 }) }), ctx: { cumNm: 0, orders: ocean } },
      { at: bag({ weather: forecastWind(12, 200, { hs: 4.6 }) }), ctx: { cumNm: 4, orders: ocean } },
    ]);
    const oh = oceanBig.events.find((e) => e.type === "hs-shift");
    assert.ok(oh, "ocean still notes the +2.6 m shift");
    assert.equal(oh.payload.alert, false, "4.6 m is under the 5.0 m Ocean alert");
    assert.ok(!types(oceanBig).includes("wx-alert"));
  });

  it("Coastal speaks at +6 kn where Cruise waits for +8 kn (denser pills on the same leg)", () => {
    const a = bag({ weather: forecastWind(10, 240) });
    const plus6 = bag({ weather: forecastWind(16, 240) });
    const cruise6 = run([{ at: a, ctx: { cumNm: 0, orders: cruise } }, { at: plus6, ctx: { cumNm: 4, orders: cruise } }]);
    assert.ok(!types(cruise6).includes("wind-shift"));
    const coastal6 = run([{ at: a, ctx: { cumNm: 0, orders: coastal } }, { at: plus6, ctx: { cumNm: 4, orders: coastal } }]);
    const ws = coastal6.events.find((e) => e.type === "wind-shift");
    assert.ok(ws, "coastal fires wind-shift at +6 kn");
    assert.ok(ws.skipper.used.some((u) => u.id === "windShiftKt" && u.value === 6 && u.source === "usage"));
  });

  it("Ocean ignores the +8 kn step and needs the WMO +16 kn squall", () => {
    const a = bag({ weather: forecastWind(10, 240) });
    const plus8 = bag({ weather: forecastWind(18, 240) });
    const plus16 = bag({ weather: forecastWind(26, 240) });
    const cruise8 = run([{ at: a, ctx: { cumNm: 0, orders: cruise } }, { at: plus8, ctx: { cumNm: 4, orders: cruise } }]);
    assert.ok(types(cruise8).includes("wind-shift"));
    const ocean8 = run([{ at: a, ctx: { cumNm: 0, orders: ocean } }, { at: plus8, ctx: { cumNm: 4, orders: ocean } }]);
    assert.ok(!types(ocean8).includes("wind-shift"));
    const ocean16 = run([{ at: a, ctx: { cumNm: 0, orders: ocean } }, { at: plus16, ctx: { cumNm: 4, orders: ocean } }]);
    const ws = ocean16.events.find((e) => e.type === "wind-shift");
    assert.ok(ws);
    assert.ok(ws.skipper.used.some((u) => u.id === "windShiftKt" && u.value === 16 && u.source === "wmo"));
  });

  it("gale 34 kn is identical in the three profiles", () => {
    const a = bag({ weather: forecastWind(20, 200) });
    const b = bag({ weather: forecastWind(34, 200) });
    for (const orders of [coastal, cruise, ocean]) {
      const r = run([{ at: a, ctx: { cumNm: 0, orders } }, { at: b, ctx: { cumNm: 5, orders } }]);
      const gale = r.events.find((e) => e.type === "wind-gale");
      assert.ok(gale, `${orders.profile} fires wind-gale at 34 kn`);
      assert.deepEqual(
        gale.skipper.used.map((u) => [u.id, u.value, u.source]),
        [["galeKt", 34, "beaufort"], ["galeHoldKt", 28, "beaufort"]],
      );
    }
    const under = bag({ weather: forecastWind(33, 200) });
    for (const orders of [coastal, cruise, ocean]) {
      const r = run([{ at: a, ctx: { cumNm: 0, orders } }, { at: under, ctx: { cumNm: 5, orders } }]);
      assert.ok(!types(r).includes("wind-gale"));
    }
  });

  it("depth: Coastal shelf at 8 m, Cruise shelf at 15 m, Ocean grounding at 5 m", () => {
    const at12 = bag({ emodnet: { kind: "observation", bathy: { depth_m: 12.4 } } });
    const at6 = bag({ emodnet: { kind: "observation", bathy: { depth_m: 6.2 } } });
    const at4 = bag({ emodnet: { kind: "observation", bathy: { depth_m: 4.1 } } });
    const one = (at, orders) => run([{ at, ctx: { cumNm: 20, orders } }]);
    assert.deepEqual(types(one(at12, cruise)), ["depth-alert"]);
    assert.equal(one(at12, cruise).events[0].payload.label, "plateau");
    assert.deepEqual(types(one(at12, coastal)), []);
    assert.deepEqual(types(one(at6, coastal)), ["depth-alert"]);
    assert.equal(one(at6, coastal).events[0].payload.alertM, 8);
    assert.deepEqual(types(one(at6, ocean)), []);
    const ground = one(at4, ocean).events[0];
    assert.equal(ground.type, "depth-alert");
    assert.equal(ground.payload.label, "talonnage");
    assert.deepEqual(ground.skipper.used.map((u) => [u.id, u.value]), [["depthAlertM", 5]]);
  });

  it("Simulation never cites rain, Suivre refuge follows the profile radius", () => {
    const at = bag({
      nearby: { marinas: [{ name: "Port des Minimes", nm: 20 }], capitaineries: [], wpi: [] },
    });
    const cruiseSim = resolveOrders({ profile: "cruise" }, { mode: "simulation" });
    const sim = run([{ at, ctx: { rainMm: 9, cumNm: 10, clockMin: 60, orders: cruiseSim } }], { mode: "simulation" });
    assert.ok(!types(sim).includes("marina-refuge"));
    const far = run([{ at, ctx: { rainMm: 9, cumNm: 10, clockMin: 60, orders: coastal } }]);
    assert.ok(!types(far).includes("marina-refuge"), "20 nm is beyond the 15 nm coastal refuge");
    const near = run([{ at, ctx: { rainMm: 9, cumNm: 10, clockMin: 60, orders: cruise } }]);
    const refuge = near.events.find((e) => e.type === "marina-refuge");
    assert.ok(refuge);
    assert.deepEqual(refuge.skipper.used.map((u) => u.id), ["rainMmH", "rain3hMm", "marinaRefugeNm"]);
    assert.ok(refuge.skipper.used.every((u) => typeof u.value === "number"));
  });

  it("keeps the Cruise export constants for the tests of E1", () => {
    assert.equal(cruise.values.hsAlertM, 3.5);
    assert.equal(cruise.values.depthAlertM, 15);
    assert.equal(cruise.values.windShiftKt, WIND_SHIFT_KT);
    assert.equal(cruise.values.galeKt, GALE_KT);
    assert.equal(cruise.values.rainMmH, RAIN_MM_H);
  });
});
