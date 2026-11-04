import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  FALLBACK_EXPEDITION_KNOTS,
  airHopSeconds,
  expeditionBoatKnots,
  filmDurationPill,
  filmShownEstimateSeconds,
  filmSpeedProfileState,
  filmVariantAbsent,
  formatFilmClock,
  nmPerSecond,
  trueWindAngle,
} from "./playSpeeds.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("expeditionBoatKnots", () => {
  it("averages downwind speed (BS), else VMG, else 7 kt", () => {
    assert.equal(expeditionBoatKnots(null), FALLBACK_EXPEDITION_KNOTS);
    assert.ok(Math.abs(expeditionBoatKnots({
      vmg_summary: { 12: { downwind: { vmg: 8 } }, 16: { downwind: { vmg: 10 } } },
    }) - 9) < 1e-9);
    assert.ok(Math.abs(expeditionBoatKnots({
      vmg_summary: { 12: { downwind: { speed: 8.3, vmg: 7.8 } }, 16: { downwind: { speed: 9.4, vmg: 8.9 } } },
    }) - 8.85) < 1e-9);
  });
});

describe("nmPerSecond", () => {
  it("real = knots / 3600; fast = Atlantic / 20 s", () => {
    assert.ok(Math.abs(nmPerSecond("real", { boatKnots: 7.2, atlanticNm: 3600 }) - 7.2 / 3600) < 1e-9);
    assert.equal(nmPerSecond("fast", { boatKnots: 7, atlanticNm: 3600 }), 180);
    assert.equal(nmPerSecond("read", { boatKnots: 7, atlanticNm: 3600 }), 15);
    assert.ok(Math.abs(nmPerSecond("normal", { boatKnots: 7, atlanticNm: 3600 }) - 3600 / 70) < 1e-9);
    assert.ok(nmPerSecond("read", { boatKnots: 7, atlanticNm: 3600 }) < nmPerSecond("normal", { boatKnots: 7, atlanticNm: 3600 }));
  });
});

describe("airHopSeconds", () => {
  it("stays visible on every profile, longer in real", () => {
    assert.ok(airHopSeconds("real") > airHopSeconds("read"));
    assert.ok(airHopSeconds("read") > airHopSeconds("fast"));
    assert.ok(airHopSeconds("fast") >= 1.5);
  });
});

describe("FM1 — pilules 2:30 / 3:00", () => {
  const full = {
    150: { chars: 5025, estimatedSeconds: 335 },
    180: { estimatedSeconds: 335 },
    0: { chars: 5025, estimatedSeconds: 335 },
  };
  const ready = {
    150: { chars: 2250, estimatedSeconds: 150 },
    180: { chars: 2600, estimatedSeconds: 173 },
    0: { chars: 5025, estimatedSeconds: 335 },
  };

  it("grise seulement une variante absente, et l'estimée suit le choix", () => {
    assert.equal(filmVariantAbsent(150, null), false);
    assert.equal(filmVariantAbsent(150, ready), false);
    assert.equal(filmVariantAbsent(150, { 150: { estimatedSeconds: 160 } }), false);
    assert.equal(filmVariantAbsent(150, full), true);
    assert.equal(filmVariantAbsent(180, { 0: { estimatedSeconds: 335 } }), true);
    assert.equal(filmDurationPill({ seconds: 150, active: false, estimates: full }).grey, true);
    assert.equal(filmDurationPill({ seconds: 150, active: false, estimates: full }).titleKey, "fm1VariantAbsent");
    assert.equal(filmDurationPill({ seconds: 150, active: true, estimates: ready }).disabled, true);
    assert.equal(filmDurationPill({ seconds: 150, active: false, estimates: ready }).grey, false);
    assert.equal(filmShownEstimateSeconds(0, full, 0), 335);
    assert.equal(formatFilmClock(335), "5:35");
    assert.equal(filmShownEstimateSeconds(150, full, 0), 335);
    assert.equal(filmShownEstimateSeconds(150, ready, 0), 150);
    assert.equal(filmShownEstimateSeconds(180, null, 195), 195);
    const absent = filmSpeedProfileState({ durationSeconds: 150, estimates: full });
    assert.equal(absent.grey, true);
    assert.equal(absent.titleKey, "fm1VariantAbsent");
    assert.equal(absent.estimateClock, "5:35");
    const chosen = filmSpeedProfileState({ durationSeconds: 180, estimates: ready });
    assert.equal(chosen.grey, false);
    assert.equal(chosen.estimateSeconds, 173);
    const profile = readFileSync(join(here, "../components/FilmSpeedProfile.jsx"), "utf8");
    assert.match(profile, /filmSpeedProfileState/);
    assert.match(profile, /fm1VariantAbsent|speed\.titleKey/);
  });
});

describe("trueWindAngle", () => {
  it("clamps to 0–180", () => {
    assert.equal(trueWindAngle(90, 90), 0);
    assert.equal(trueWindAngle(0, 180), 180);
    assert.equal(trueWindAngle(10, 350), 20);
  });
});
