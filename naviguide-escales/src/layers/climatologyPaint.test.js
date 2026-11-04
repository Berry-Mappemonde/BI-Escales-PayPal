import { describe, it } from "node:test";
import assert from "node:assert/strict";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import { climoCaptionText, layerPopupHtml, pointPopupHtml, roseSvg, waveColor } from "./climatologyPaint.js";

function translate(dict) {
  return (key, vars = {}) => {
    const str = dict[key] ?? key;
    return Object.entries(vars).reduce(
      (s, [k, v]) => s.replaceAll(`{${k}}`, String(v ?? "")),
      str,
    );
  };
}

const tEn = translate(en);
const tFr = translate(fr);

function captionSize(html) {
  const style = html.match(/data-testid="climatology-caption"[^>]*style="([^"]*)"/);
  assert.ok(style, "légende climatologie");
  assert.doesNotMatch(style[1], /monospace/);
  const size = Number((style[1].match(/font-size:\s*(\d+(?:\.\d+)?)px/) || [])[1]);
  assert.ok(size >= 12, `taille ${size} px`);
  return style[1];
}

const wind = {
  month: 5,
  wind_speed_knots: 16,
  wind_direction_from_deg: 55,
  vector_mean_knots: 14,
  vector_mean_from_deg: 60,
  directions_from: [{ dir_deg: 45, pct: 40 }],
  calm_pct: 4,
  gale_pct: 1,
  sample_count: 200,
};

describe("climatologyPaint", () => {
  it("paints a rose and a readable climatology caption", () => {
    const svg = roseSvg({
      wind_direction_from_deg: 55,
      wind_speed_knots: 16,
      directions_from: [{ dir_deg: 45, pct: 40 }],
    });
    assert.match(svg, /<svg/);
    const html = layerPopupHtml("wind", wind, tEn);
    assert.equal(climoCaptionText(5, tEn), "Climatology — monthly average (May), not a forecast");
    assert.match(html, /Climatology — monthly average \(May\), not a forecast/);
    assert.match(html, /data-testid="climatology-popup"/);
    assert.match(html, /data-testid="climatology-caption"/);
    captionSize(html);
    assert.doesNotMatch(html, /kind:/);
    assert.doesNotMatch(html, /font-size:\s*9px/);
    assert.doesNotMatch(html, /GRIB/i);
  });

  it("légende française du même mois, sans code kind", () => {
    const html = layerPopupHtml("wind", wind, tFr);
    assert.equal(climoCaptionText(5, tFr), "Climatologie — moyenne mensuelle (mai), pas une prévision");
    assert.match(html, /Climatologie — moyenne mensuelle \(mai\), pas une prévision/);
    captionSize(html);
    assert.doesNotMatch(html, /kind:/);
    assert.doesNotMatch(html, /GRIB/i);
  });

  it("ne nomme pas janvier quand le mois est absent", () => {
    assert.equal(climoCaptionText(null, tFr), "Climatologie — moyenne mensuelle, pas une prévision");
    assert.equal(climoCaptionText(undefined, tEn), "Climatology — monthly average, not a forecast");
    assert.doesNotMatch(climoCaptionText(Number.NaN, tFr), /janvier/);
    assert.doesNotMatch(climoCaptionText("", tEn), /January/);
    assert.match(pointPopupHtml({ kind: "climatology" }, tFr), /pas une prévision/);
    assert.doesNotMatch(pointPopupHtml({ kind: "climatology" }, tFr), /janvier/);
  });

  it("uses distinct P50 / P90 colours", () => {
    assert.notEqual(waveColor(2.8, "p90"), waveColor(2.8, "p50"));
    const point = pointPopupHtml({
      kind: "climatology",
      month: 5,
      wind_atlas: { most_likely: { speed_knots: 16, dir_deg: 55 } },
      wave: { hs_p50_m: 1.4, hs_p90_m: 2.8 },
      current: { speed_knots: 0.4 },
    }, tEn);
    assert.match(point, /Hs P50 1.4/);
    assert.match(point, /Hs P90 2.8/);
    assert.match(point, /Climatology — monthly average \(May\), not a forecast/);
    captionSize(point);
    assert.doesNotMatch(point, /kind:/);
    assert.doesNotMatch(point, /GRIB/i);
    const pointFr = pointPopupHtml({ kind: "climatology", month: 5 }, tFr);
    assert.match(pointFr, /Climatologie — moyenne mensuelle \(mai\), pas une prévision/);
    assert.doesNotMatch(pointFr, /kind:/);
  });
});

describe("pointPopupHtml — atlas coupé", () => {
  it("affiche le vent de zone, signalé comme repli, au lieu d'une case vide", () => {
    const where = { lat: 46.15, lon: -1.16, month: 10 };
    for (const data of [{ kind: "unavailable" }, null]) {
      const html = pointPopupHtml(data, tFr, where);
      assert.match(html, /vent \d+ kn \/ \d+°/);
      assert.match(html, /data-testid="climatology-zone-fallback"/);
      assert.match(html, /vent de zone en repli/);
    }
  });

  it("ne remplace jamais une vraie valeur d'atlas par le repli", () => {
    const html = pointPopupHtml({ kind: "climatology", wave: { hs_p50_m: 1.4 } }, tFr, { lat: 46, lon: -1, month: 10 });
    assert.match(html, /Hs P50 1.4 m/);
    assert.doesNotMatch(html, /climatology-zone-fallback/);
    assert.doesNotMatch(pointPopupHtml({ kind: "unavailable" }, tFr), /climatology-zone-fallback/);
  });
});
