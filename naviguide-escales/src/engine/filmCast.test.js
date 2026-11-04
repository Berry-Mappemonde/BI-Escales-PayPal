import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { flattenRoute } from "./routePlayhead.js";
import {
  AIR_FILM_NM,
  detectAirEpisodes,
  interpolateCast,
  filmNmToSailNm,
  mergeEpisodeMarks,
  sailNmToFilmNm,
} from "./filmCast.js";
import { filmLegContext, mapEscalesOnRoute } from "./routePlayhead.js";
import { routeFromOfficial } from "../utils/routeFromOfficial.js";

const CAYENNE = [-52.3533, 4.9333];
const HALIFAX = [-63.5652, 44.6488];
const SPM = [-56.1628, 46.7761];

const STOPS = [
  { name: "Cayenne (Guyane)", lat: 4.9333, lon: -52.3533, flag: "f" },
  { name: "Halifax (Nouvelle-Écosse)", lat: 44.6488, lon: -63.5652, flag: "" },
  { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)", lat: 46.7761, lon: -56.1628, flag: "f" },
];

function guyaneFlat() {
  return flattenRoute([
    { coords: [[-52.36, 4.92], CAYENNE] },
    { coords: [HALIFAX, SPM] },
    { coords: [SPM, HALIFAX] },
    { coords: [CAYENNE, [-52.4, 4.8]] },
  ]);
}

describe("detectAirEpisodes", () => {
  it("paire Cayenne → Halifax → retour Cayenne", () => {
    const flat = guyaneFlat();
    assert.equal(flat.episodes.length, 1);
    assert.ok(Math.abs(flat.totalFilmNm - flat.totalNm - 2 * AIR_FILM_NM) < 1e-6);
    assert.ok(flat.totalNm > 200);
    const [ep] = detectAirEpisodes(flat.points);
    assert.ok(Math.abs(ep.park.lat - 4.9333) < 0.05);
    assert.ok(Math.abs(ep.hub.lat - 44.65) < 0.05);
    assert.ok(Math.abs(ep.via.lat - 46.78) < 0.1);
  });
});

describe("interpolateCast Guyane", () => {
  it("keeps the boat in Cayenne, plane then relay boat, then return", () => {
    const flat = guyaneFlat();
    const [ep] = flat.episodes;
    const airOutMid = (flat.points[ep.ja - 1].filmCum + flat.points[ep.ja].filmCum) / 2;
    const sideMid = (flat.points[ep.ja].filmCum + flat.points[ep.jb - 1].filmCum) / 2;
    const airBackMid = (flat.points[ep.jb - 1].filmCum + flat.points[ep.jb].filmCum) / 2;

    const out = interpolateCast(flat, airOutMid, { stops: STOPS });
    assert.equal(out.phase, "air-out");
    assert.equal(out.vehicle, "plane");
    assert.ok(out.main.visible);
    assert.ok(out.plane.visible);
    assert.equal(out.side.visible, false);
    assert.ok(Math.abs(out.main.lat - 4.9333) < 0.05);
    assert.ok(out.plane.lat > 10);
    assert.ok(out.plane.lat < 40);
    assert.equal(out.fromName, "Cayenne (Guyane)");
    assert.equal(out.toName, "Halifax (Nouvelle-Écosse)");

    const side = interpolateCast(flat, sideMid, { stops: STOPS });
    assert.equal(side.phase, "side-sail");
    assert.ok(side.side.visible);
    assert.equal(side.plane.visible, false);
    assert.ok(Math.abs(side.main.lat - 4.9333) < 0.05);
    assert.ok(side.side.lat > 44);
    assert.match(side.fromName, /Halifax|Saint-Pierre/);
    assert.match(side.toName, /Halifax|Saint-Pierre/);

    const back = interpolateCast(flat, airBackMid, { stops: STOPS });
    assert.equal(back.phase, "air-return");
    assert.ok(back.plane.visible);
    assert.equal(back.side.visible, false);
    assert.ok(Math.abs(back.main.lat - 4.9333) < 0.05);
    assert.equal(back.fromName, "Halifax (Nouvelle-Écosse)");
    assert.equal(back.toName, "Cayenne (Guyane)");

    const after = interpolateCast(flat, flat.totalFilmNm, { stops: STOPS });
    assert.equal(after.phase, "sail");
    assert.equal(after.plane.visible, false);
    assert.equal(after.side.visible, false);
    assert.ok(after.main.lat < 4.93);

    const before = interpolateCast(flat, 0, { stops: STOPS });
    assert.equal(before.phase, "sail");
    assert.equal(before.plane.visible, false);
  });

  it("converts film ↔ sail without counting the plane in sea nm", () => {
    const flat = guyaneFlat();
    const [ep] = flat.episodes;
    const airMid = (flat.points[ep.ja - 1].filmCum + flat.points[ep.ja].filmCum) / 2;
    assert.ok(Math.abs(filmNmToSailNm(flat, airMid) - flat.points[ep.ja - 1].cumNm) < 1e-6);
    const cayenneSail = flat.points[ep.ja - 1].cumNm;
    const filmAtQuay = sailNmToFilmNm(flat, cayenneSail);
    assert.ok(Math.abs(filmAtQuay - flat.points[ep.ja - 1].filmCum) < 1e-6);
  });
});

describe("mergeEpisodeMarks", () => {
  it("re-inserts Cayenne after SPM for the HUD toward Papeete", () => {
    const flat = guyaneFlat();
    const marks = mergeEpisodeMarks(mapEscalesOnRoute(STOPS, flat), flat, STOPS);
    const cayenneMarks = marks.filter((m) => /Cayenne/i.test(m.name));
    assert.ok(cayenneMarks.length >= 2);
    const after = interpolateCast(flat, flat.totalFilmNm, { stops: STOPS });
    const hud = filmLegContext({
      marks,
      nm: after.sailNm,
      sample: after.main,
      totalNm: flat.totalNm,
      boatKnots: 8,
      cast: after,
    });
    assert.match(hud.fromStop, /Cayenne/);
  });
});

describe("route officielle Berry", () => {
  it("one Guiana air episode and the main boat does not cross the Atlantic", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const raw = JSON.parse(readFileSync(join(here, "../../public/route.geojson"), "utf8"));
    const { segments, stops } = routeFromOfficial(raw);
    const flat = flattenRoute(segments);
    assert.ok(flat.episodes.length >= 1);
    const ep = flat.episodes[0];
    assert.ok(Math.abs(ep.park.lat - 4.93) < 0.4, `park ${ep.park.lat}`);
    assert.ok(Math.abs(ep.hub.lat - 44.65) < 0.6, `hub ${ep.hub.lat}`);
    const out = interpolateCast(flat, (flat.points[ep.ja - 1].filmCum + flat.points[ep.ja].filmCum) / 2, { stops });
    assert.equal(out.phase, "air-out");
    assert.ok(Math.abs(out.main.lat - ep.park.lat) < 1e-6);
    assert.ok(out.plane.lat > 8);
    const side = interpolateCast(flat, (flat.points[ep.ja].filmCum + flat.points[ep.jb - 1].filmCum) / 2, { stops });
    assert.equal(side.phase, "side-sail");
    assert.ok(Math.abs(side.main.lat - ep.park.lat) < 1e-6);
    assert.ok(side.side.lat > 43);
  });
});
