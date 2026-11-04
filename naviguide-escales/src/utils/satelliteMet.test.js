import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import {
  formatBearingCardinal,
  formatCardinal,
  formatCellLabel,
  formatMetNumber,
  formatMetTime,
} from "./satelliteMet.js";

const SAT_KEYS = [
  "windSpeedKmh", "windSpeedMs", "waveDirection",
  "currentSpeedKmh", "currentSpeedMs", "currentDirection",
  "satelliteLat", "satelliteLon", "satelliteIssued",
  "satelliteSource", "satelliteCycle", "satelliteCell",
  "satelliteEstimated", "satelliteCopernicus",
  "satelliteCardinal", "cardinalSSE", "cardinalNE", "cardinalNNE",
];
const here = dirname(fileURLToPath(import.meta.url));

describe("satelliteMet", () => {
  it("keeps a cardinal next to the degree", () => {
    assert.equal(formatCardinal(162.5), "SSE");
    assert.equal(formatCardinal(34.5), "NE");
    assert.equal(formatBearingCardinal(67.5), "ENE · 67.5°");
    assert.equal(formatBearingCardinal(202.9), "SSO · 202.9°");
    assert.equal(formatBearingCardinal(202.9, "en"), "SSW · 202.9°");
    assert.equal(formatCardinal(312, "en"), "NW");
    assert.equal(formatBearingCardinal(undefined), "");
  });

  it("renders a dedicated cardinal row for waves and currents", () => {
    const panel = readFileSync(join(here, "../components/SatelliteMetPanel.jsx"), "utf8");
    assert.match(panel, /satelliteCardinal/);
    assert.match(panel, /mean_wave_direction/);
    assert.match(panel, /direction_deg/);
    assert.match(panel, /WindDirectionArrow/);
  });

  it("drops trailing zeros on numbers", () => {
    assert.equal(formatMetNumber(13.1, 1), "13.1");
    assert.equal(formatMetNumber(4, 2), "4");
  });

  it("formats the issued time in UTC", () => {
    assert.match(formatMetTime("2026-09-17T20:07:09.022172Z"), /2026-09-17 20:07 UTC/);
  });

  it("labels the cache cell", () => {
    assert.equal(
      formatCellLabel({ lat: 46.875, lon: 1.625, deg: 0.25 }),
      "46.875, 1.625 (0.25°)",
    );
  });

  it("has satellite labels in FR and EN", () => {
    for (const k of SAT_KEYS) {
      assert.equal(typeof fr[k], "string", `fr.${k}`);
      assert.equal(typeof en[k], "string", `en.${k}`);
    }
  });

  it("keeps the three satellite tabs and the met panel in App", () => {
    const app = readFileSync(join(here, "../App.jsx"), "utf8");
    assert.match(app, /SatelliteMetPanel/);
    assert.match(app, /windTab/);
    assert.match(app, /wavesTab/);
    assert.match(app, /currentsTab/);
  });
});
