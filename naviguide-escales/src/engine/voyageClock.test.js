import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { flattenRoute, mapEscalesOnRoute } from "./routePlayhead.js";
import { clockTickLabels } from "./seaTime.js";
import {
  AIR_CALENDAR_HOURS,
  DEFAULT_PORT_DAYS,
  DEFAULT_T0_ISO,
  simulationT0Iso,
  OFFICIAL_VOYAGE_ID,
  SAINT_MAUR_LAND_HOURS,
  buildVoyageClock,
  clockTickLabelsFromClock,
  filmBarTicks,
  formatFilmClockLine,
  formatCivilDate,
  formatStopoverDate,
  rebaseIso,
  resolveStoryT0,
  lookupVoyageClock,
  formatDepartureDate,
  normalizeUtcTime,
  parseFrenchDepartureDate,
  parseDepartureUtc,
  portHoldHours,
  sampleClockAtHours,
  sampleClockAtTime,
  splitDepartureUtc,
} from "./voyageClock.js";

const CAYENNE = [-52.3533, 4.9333];
const HALIFAX = [-63.5652, 44.6488];
const SPM = [-56.1628, 46.7761];

function atlanticFlat() {
  return flattenRoute([
    { nonMaritime: true, coords: [[1.6358, 46.8075], [-1.167, 46.1541]] },
    {
      nonMaritime: false,
      coords: [
        [-1.167, 46.1541],
        [-12, 35],
        [-20, 25],
        [-25, 15],
        [-40, 14.8],
        [-55, 14.7],
        [-61.0731, 14.5887],
      ],
    },
  ]);
}

function atlanticMarks(flat) {
  return mapEscalesOnRoute([
    { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: "f" },
    { name: "La Rochelle", lat: 46.1541, lon: -1.167, flag: "f" },
    { name: "Fort-de-France (Martinique)", lat: 14.5887, lon: -61.0731, flag: "f" },
  ], flat);
}

function clockFor(t0, extras = {}) {
  const flat = atlanticFlat();
  const marks = atlanticMarks(flat);
  return {
    flat,
    marks,
    clock: buildVoyageClock({
      flat,
      marks,
      t0,
      polarRaw: null,
      startAt: "la-rochelle",
      ...extras,
    }),
  };
}

function fdfMark(clock) {
  return clock.marks.find((m) => /Fort-de-France/i.test(m.name));
}

describe("voyageClock Atlantique", () => {
  it("March vs July, same nm: Fort-de-France arrivalIso differs", () => {
    const mar = clockFor("2026-03-15T08:00:00.000Z").clock;
    const jul = clockFor("2026-07-15T08:00:00.000Z").clock;
    assert.equal(mar.kind, "climatology");
    assert.equal(jul.kind, "climatology");
    const a = fdfMark(mar);
    const b = fdfMark(jul);
    assert.ok(a && b);
    assert.notEqual(a.iso, b.iso);
    const gapH = Math.abs(Date.parse(a.iso) - Date.parse(b.iso)) / 3600000;
    assert.ok(gapH > 48, `écart Fort-de-France ${gapH} h`);
  });

  it("t0 = 15 June 08:00, La Rochelle → Fort-de-France departure > 15 June", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const fdf = fdfMark(clock);
    assert.ok(fdf);
    assert.ok(Date.parse(fdf.iso) > Date.parse("2026-06-15T08:00:00.000Z"));
  });

  it("without polar: climatology source, no crash", () => {
    const { clock } = clockFor("2026-06-01T08:00:00.000Z");
    assert.equal(clock.kind, "climatology");
    assert.ok(clock.vertices.length > 3);
    assert.ok(clock.vertices.every((v) => Number.isFinite(v.tHours)));
    const sea = clock.vertices.find((v) => v.vehicle === "main" && v.speedKnots > 0);
    assert.ok(sea);
    assert.equal(sea.kind, "climatology");
    assert.ok("model" in sea);
    assert.ok("leadHours" in sea);
  });

  it("sampleClockAtTime: waiting if now < t0", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const waiting = sampleClockAtTime(clock, "2026-06-14T08:00:00.000Z");
    assert.equal(waiting.status, "waiting");
    assert.ok(waiting.countdownHours > 23);
    const live = sampleClockAtTime(clock, "2026-06-15T20:00:00.000Z");
    assert.equal(live.status, "live");
    assert.equal(live.kind, "climatology");
  });
});

describe("voyageClock quais et hops", () => {
  it("2-day quay: 48 h gap in iso at constant filmNm", () => {
    const flat = flattenRoute([
      { coords: [[-1.2, 46.1], [-20, 20], [-40, 15]] },
    ]);
    const marks = [
      { name: "La Rochelle", lat: 46.1, lon: -1.2, nm: 0, filmNm: 0, index: 0 },
      { name: "Escale Test", lat: 20, lon: -20, nm: flat.points[1].cumNm, filmNm: flat.points[1].filmCum, index: 1 },
      { name: "Fort-de-France (Martinique)", lat: 15, lon: -40, nm: flat.totalNm, filmNm: flat.totalFilmNm, index: flat.points.length - 1 },
    ];
    const clock = buildVoyageClock({
      flat,
      marks,
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
      portDays: { laRochelle: 0, saintMaur: 0, halifax: 0, default: 2 },
    });
    const mid = clock.marks.find((m) => m.name === "Escale Test");
    assert.ok(mid);
    assert.equal(mid.holdHours, 48);
    const pair = clock.vertices.filter((v) => Math.abs(v.filmNm - mid.filmNm) < 1e-6);
    assert.ok(pair.length >= 2);
    const gap = pair[pair.length - 1].tHours - pair[0].tHours;
    assert.ok(Math.abs(gap - 48) < 1e-6);
    const arrival = lookupVoyageClock(clock, mid.filmNm, { atQuay: false });
    const leave = lookupVoyageClock(clock, mid.filmNm, { atQuay: true });
    assert.ok(Math.abs(leave.tHours - arrival.tHours - 48) < 1e-6);
    assert.equal(arrival.filmNm, leave.filmNm);
    const atQuay = sampleClockAtHours(clock, mid.tHours + 1);
    assert.equal(atQuay.atQuay, true);
    assert.equal(atQuay.speedKnots, 0);
    assert.equal(atQuay.vehicle, "quay");
  });

  it("air hop: +8 h, speedKnots null", () => {
    const flat = flattenRoute([
      { coords: [[-52.36, 4.92], CAYENNE] },
      { coords: [HALIFAX, SPM] },
    ]);
    const clock = buildVoyageClock({
      flat,
      marks: [],
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
    });
    const plane = clock.vertices.find((v) => v.vehicle === "plane");
    assert.ok(plane);
    assert.equal(plane.speedKnots, null);
    const before = clock.vertices[clock.vertices.indexOf(plane) - 1];
    assert.ok(Math.abs(plane.tHours - before.tHours - AIR_CALENDAR_HOURS) < 1e-6);
  });

  it("startAt saint-maur: first dt without a polar", () => {
    const { clock } = clockFor("2026-06-01T08:00:00.000Z", { startAt: "saint-maur" });
    const lr = clock.marks.find((m) => /La Rochelle/i.test(m.name));
    assert.ok(lr);
    assert.ok(Math.abs(lr.tHours - SAINT_MAUR_LAND_HOURS) < 1e-6);
    const land = clock.vertices.find((v) => v.vehicle === "land" && v.filmNm > 0);
    assert.ok(land);
    assert.equal(land.speedKnots, null);
  });
});

describe("voyageClock antimeridian", () => {
  it("tHours is monotonic across the antimeridian", () => {
    const flat = flattenRoute([
      { coords: [[179.2, -15], [179.8, -15], [-179.8, -15], [-179.2, -15]] },
    ]);
    const clock = buildVoyageClock({
      flat,
      marks: [],
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
    });
    let prev = -1;
    for (const v of clock.vertices) {
      assert.ok(v.tHours >= prev - 1e-9, `tHours ${v.tHours} < ${prev}`);
      prev = v.tHours;
    }
    assert.ok(clock.vertices.at(-1).tHours > 0);
  });
});

describe("voyageClock contrat B0", () => {
  it("each vertex carries kind + seaHours (same schema as the server)", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const keys = [
      "filmNm", "sailNm", "lat", "lon", "bearing", "tHours", "iso",
      "speedKnots", "windKnots", "twa", "month", "vehicle", "kind", "seaHours",
    ];
    assert.ok(clock.vertices.length > 0);
    for (const k of keys) {
      assert.ok(k in clock.vertices[0], `manque ${k}`);
    }
    assert.ok(clock.vertices.every((v) => v.kind === "climatology"));
  });

  it("windAt atlas replaces the zone as soon as the pack answers", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z", {
      windAt: () => ({
        speedKnots: 22,
        dirFromDeg: 80,
        kind: "climatology",
        source: "atlas",
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        hsP50: 1.2,
        hsP90: 2.6,
        currentKn: 0.3,
      }),
    });
    const sea = clock.vertices.find((v) => v.vehicle === "main" && v.speedKnots > 0);
    assert.ok(sea);
    assert.equal(sea.kind, "climatology");
    assert.equal(sea.source, "atlas");
    assert.equal(sea.hsP90, 2.6);
    assert.equal(clock.atlasSource, "atlas");
    assert.notEqual(sea.kind, "forecast");
  });
});

describe("parseDepartureUtc", () => {
  it("compose un ISO UTC depuis date + heure", () => {
    assert.equal(parseDepartureUtc("2026-03-15", "08:00"), "2026-03-15T08:00:00.000Z");
    assert.deepEqual(splitDepartureUtc("2026-06-01T08:00:00.000Z"), { date: "2026-06-01", time: "08:00" });
  });

  it("impose le format de saisie français et une heure UTC modifiable", () => {
    assert.equal(formatDepartureDate("2026-05-15"), "15/05/2026");
    assert.equal(parseFrenchDepartureDate("15/05/2026"), "2026-05-15");
    assert.equal(parseFrenchDepartureDate("15/15/2026"), null);
    assert.equal(parseFrenchDepartureDate("31/02/2026"), null);
    assert.equal(normalizeUtcTime("14:30"), "14:30");
    assert.equal(normalizeUtcTime("24:00"), null);
    assert.equal(
      parseDepartureUtc(parseFrenchDepartureDate("15/05/2026"), normalizeUtcTime("14:30")),
      "2026-05-15T14:30:00.000Z",
    );
  });
});

describe("U0 horloge officielle", () => {
  it("t0 = 15 mai 2026 08:00 UTC, pas le 1er juin", () => {
    assert.equal(DEFAULT_T0_ISO, "2026-05-15T08:00:00.000Z");
    assert.equal(simulationT0Iso(new Date("2026-09-17T20:46:00.000Z")), "2026-09-17T08:00:00.000Z");
    const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../App.jsx"), "utf8");
    const clockHook = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../hooks/useVoyageClock.js"), "utf8");
    assert.match(clockHook, /DEFAULT_T0_ISO/);
    assert.match(clockHook, /simulationT0Iso\(\)/);
    assert.match(clockHook, /mode === "suivre" \? DEFAULT_T0_ISO : simT0/);
    assert.match(clockHook, /setT0: setSimT0/);
    assert.match(clockHook, /resetToToday/);
    assert.match(app, /mode: suivreBerry \? "suivre" : SERVER_MODE_TRACER/);
    assert.match(app, /voyage\.resetToToday\(\)/);
    assert.doesNotMatch(app, /voyage\.setT0\(simulationT0Iso\(\)\)/);
    assert.doesNotMatch(app, /voyage\.setT0\(DEFAULT_T0_ISO\)/);
    assert.equal(OFFICIAL_VOYAGE_ID, "berry-mappemonde-2026-officiel");
    assert.deepEqual(splitDepartureUtc(DEFAULT_T0_ISO), { date: "2026-05-15", time: "08:00" });
    assert.deepEqual(splitDepartureUtc(""), { date: "2026-05-15", time: "08:00" });
  });

  it("escales Bmap = 3 jours à quai (pas 2)", () => {
    assert.equal(DEFAULT_PORT_DAYS.default, 3);
    assert.equal(portHoldHours("Ajaccio"), 72);
    assert.equal(portHoldHours("Cayenne"), 72);
    assert.equal(portHoldHours("Papeete"), 72);
    assert.equal(portHoldHours("Mata Utu"), 72);
    assert.equal(portHoldHours("Halifax"), 24);
    const { clock } = clockFor(DEFAULT_T0_ISO);
    assert.equal(clock.t0, DEFAULT_T0_ISO);
    const fdf = fdfMark(clock);
    assert.ok(fdf);
    assert.equal(fdf.holdHours, 72);
  });
});

describe("clockTickLabelsFromClock", () => {
  it("un seul J : celui du HUD, pas un milieu à 50 % du film", () => {
    const { clock } = clockFor(DEFAULT_T0_ISO);
    const last = lookupVoyageClock(clock, clock.vertices.at(-1).filmNm);
    const midFilm = last.filmNm * 0.5;
    const mid = lookupVoyageClock(clock, midFilm);
    const live = lookupVoyageClock(clock, last.filmNm * 0.47);
    const ticks = clockTickLabelsFromClock(clock, "fr", {
      filmNm: live.filmNm,
      sailNm: live.sailNm,
      seaHours: live.seaHours,
    });
    assert.equal(ticks.length, 3);
    assert.equal(ticks[0].label.includes("j"), false);
    assert.equal(ticks[2].label.includes("j"), false);
    const hudJ = `j${Math.floor(live.seaHours / 24)}`;
    assert.match(ticks[1].label, new RegExp(hudJ));
    const midJ = `j${Math.floor(mid.seaHours / 24)}`;
    if (midJ !== hudJ) {
      assert.equal(ticks[1].label.includes(midJ), false);
    }
  });

  it("EN : le J du HUD s'écrit dN, pas jN", () => {
    const { clock } = clockFor(DEFAULT_T0_ISO);
    const last = lookupVoyageClock(clock, clock.vertices.at(-1).filmNm);
    const live = lookupVoyageClock(clock, last.filmNm * 0.47);
    const ticks = clockTickLabelsFromClock(clock, "en", {
      filmNm: live.filmNm,
      sailNm: live.sailNm,
      seaHours: live.seaHours,
    });
    const hudD = `d${Math.floor(live.seaHours / 24)}`;
    assert.match(ticks[1].label, new RegExp(hudD));
    assert.equal(ticks[1].label.includes(`j${Math.floor(live.seaHours / 24)}`), false);
  });
});

describe("filmBarTicks", () => {
  it("sans horloge : aucune graduation (pas de fallback J)", () => {
    assert.deepEqual(filmBarTicks(null), []);
    assert.deepEqual(filmBarTicks({ vertices: [] }), []);
  });

  it("HUD et tick courant partagent le même J — le fallback 7 kt diverge", () => {
    const { clock } = clockFor(DEFAULT_T0_ISO);
    const last = lookupVoyageClock(clock, clock.vertices.at(-1).filmNm);
    const live = lookupVoyageClock(clock, last.filmNm * 0.47);
    const ticks = filmBarTicks(clock, "fr", {
      filmNm: live.filmNm,
      sailNm: live.sailNm,
      seaHours: live.seaHours,
    });
    const line = formatFilmClockLine({
      sailNm: live.sailNm,
      seaHours: live.seaHours,
      iso: live.iso,
      lang: "fr",
    });
    const clockJ = `j${Math.floor(live.seaHours / 24)}`;
    assert.match(ticks[1].label, new RegExp(clockJ));
    assert.match(line, new RegExp(clockJ));
    const fallback = clockTickLabels({
      playheadTotal: last.filmNm,
      sailTotalNm: last.sailNm,
      knots: 20,
      scale: "both",
    });
    const fallbackJ = fallback[2].label.match(/j(\d+)/)?.[1];
    const clockDay = String(Math.floor(live.seaHours / 24));
    assert.ok(fallbackJ);
    assert.notEqual(fallbackJ, clockDay);
  });

  it("SimulationFilmBar n’affiche plus ticks ni profil vent", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../components/SimulationFilmBar.jsx"),
      "utf8",
    );
    assert.equal(src.includes("clockTickLabels"), false);
    assert.equal(src.includes("filmBarTicks"), false);
    assert.equal(src.includes("FilmSpeedProfile"), false);
    assert.equal(src.includes("film-clock-ticks"), false);
  });
});

describe("Régime sur l’échantillon", () => {
  it("propage regime / sources / spread", () => {
    const clock = {
      t0: "2026-05-15T08:00:00.000Z",
      vertices: [
        {
          filmNm: 0, sailNm: 0, lat: 46.15, lon: -1.16, bearing: 250,
          tHours: 0, iso: "2026-05-15T08:00:00.000Z", speedKnots: 7.4,
          windKnots: 14, twa: 90, month: 5, vehicle: "main", seaHours: 0,
          kind: "hindcast", regime: "hindcast", sources: ["om-era5", "cmems-wind"], spread: 1.5,
        },
        {
          filmNm: 20, sailNm: 20, lat: 46.0, lon: -2.0, bearing: 250,
          tHours: 3, iso: "2026-05-15T11:00:00.000Z", speedKnots: 7.4,
          windKnots: 14, twa: 90, month: 5, vehicle: "main", seaHours: 3,
          kind: "hindcast", regime: "hindcast", sources: ["om-era5"], spread: 1.5,
        },
      ],
    };
    const s = sampleClockAtHours(clock, 1);
    assert.equal(s.regime, "hindcast");
    assert.deepEqual(s.sources, ["om-era5", "cmems-wind"]);
    assert.equal(s.spread, 1.5);
  });

  it("barre film expose data-testid clock-regime", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../components/SimulationFilmBar.jsx"),
      "utf8",
    );
    assert.match(src, /data-testid="clock-regime"/);
  });

  it("sampleClockAtHours : vitesse du pas courant, pas interpolée", () => {
    const clock = {
      t0: "2026-05-15T08:00:00.000Z",
      vertices: [
        {
          filmNm: 0, sailNm: 0, lat: 46.15, lon: -1.16, bearing: 250,
          tHours: 0, iso: "2026-05-15T08:00:00.000Z", speedKnots: 6,
          windKnots: 10, twa: 90, month: 5, vehicle: "main", seaHours: 0,
          kind: "hindcast", regime: "hindcast",
        },
        {
          filmNm: 20, sailNm: 20, lat: 46.0, lon: -2.0, bearing: 250,
          tHours: 4, iso: "2026-05-15T12:00:00.000Z", speedKnots: 10,
          windKnots: 16, twa: 90, month: 5, vehicle: "main", seaHours: 4,
          kind: "hindcast", regime: "hindcast",
        },
      ],
    };
    const mid = sampleClockAtHours(clock, 2);
    assert.equal(mid.speedKnots, 10);
    assert.notEqual(mid.speedKnots, 8);
  });
});

describe("Voile hors avion", () => {
  it("n'ajoute pas les milles du saut avion à sailNm", () => {
    const flat = {
      points: [
        { lat: 4.9, lon: -52.3, cumNm: 1000, filmCum: 1000, jump: false },
        { lat: 44.6, lon: -63.6, cumNm: 2500, filmCum: 2580, jump: true },
        { lat: 44.7, lon: -63.8, cumNm: 2530, filmCum: 2610, jump: false },
      ],
      totalNm: 2530,
      totalFilmNm: 2610,
    };
    const clock = buildVoyageClock({
      flat,
      marks: [],
      t0: "2026-06-15T08:00:00.000Z",
      startAt: "saint-maur",
    });
    const plane = clock.vertices.find((v) => v.vehicle === "plane");
    assert.ok(plane);
    assert.equal(plane.sailNm, 1000);
    assert.equal(plane.tHours, AIR_CALENDAR_HOURS);
    const seaAfter = clock.vertices.filter((v) => v.vehicle === "main" && v.sailNm > 1000);
    assert.ok(seaAfter.length);
    assert.equal(Math.max(...seaAfter.map((v) => v.sailNm)), 1030);
  });
});

describe("formatStopoverDate", () => {
  it("shows arrival and departure in English, preserving the French date label", () => {
    const arrival = "2026-05-15T08:00:00Z";
    assert.equal(formatStopoverDate(arrival, 16 * 24, "en"), "15–31 May");
    assert.equal(formatStopoverDate(arrival, 16 * 24, "fr"), formatCivilDate(arrival, "fr"));
  });

  it("formats a month boundary without exposing an ISO date", () => {
    assert.equal(formatStopoverDate("2026-05-31T08:00:00Z", 48, "en"), "31 May–2 Jun");
  });
});

describe("formatFilmClockLine", () => {
  it("compose nm · j · date UTC", () => {
    const line = formatFilmClockLine({
      sailNm: 4210,
      seaHours: 18 * 24 + 2,
      iso: "2026-07-03T14:00:00.000Z",
      lang: "fr",
    });
    assert.match(line, /4[\s ]?210 nm/);
    assert.match(line, /j18/);
    assert.match(line, /3 juil\. 2026 · 14:00 UTC/);
  });

  it("rebaseIso décale d’un an sans inventer le jour", () => {
    assert.equal(
      rebaseIso("2026-05-15T08:00:00.000Z", DEFAULT_T0_ISO, "2025-05-15T08:00:00.000Z"),
      "2025-05-15T08:00:00.000Z",
    );
    assert.equal(rebaseIso("2026-05-24T08:00:00.000Z", DEFAULT_T0_ISO, DEFAULT_T0_ISO), "2026-05-24T08:00:00.000Z");
    assert.equal(resolveStoryT0("2025-05-15T08:00:00.000Z"), "2025-05-15T08:00:00.000Z");
    assert.equal(resolveStoryT0("pas-une-date"), DEFAULT_T0_ISO);
  });
});
