import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildLocalCustomBriefing, coastNameNear } from "./customRouteBriefing.js";
import { featuresToSegments, legsDistanceNm } from "./geo.js";

const laRochelleBrest = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "La Teste" },
      geometry: { type: "Point", coordinates: [-1.14, 44.63] },
    },
    {
      type: "Feature",
      properties: { name: "Ouessant" },
      geometry: { type: "Point", coordinates: [-5.1, 48.46] },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-1.14, 44.63],
          [-5.1, 48.46],
        ],
      },
    },
  ],
};

describe("buildLocalCustomBriefing", () => {
  it("rejects a collection that is too short", () => {
    assert.equal(
      buildLocalCustomBriefing({
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-1, 46] } }],
      }),
      null,
    );
  });

  it("describes the drawn route, not Berry, with executive_briefing", () => {
    const plan = buildLocalCustomBriefing(laRochelleBrest, "fr");
    assert.ok(plan.executive_briefing.includes("Route personnalisée"));
    assert.ok(plan.executive_briefing.includes("tracée à la main"));
    assert.ok(plan.executive_briefing.includes("La Teste"));
    assert.ok(plan.executive_briefing.includes("Ouessant"));
    assert.ok(plan.executive_briefing.includes("44.63°N"));
    assert.ok(!/papeete|saint-maur|halifax/i.test(plan.executive_briefing));
    assert.ok(!/la rochelle/i.test(plan.executive_briefing));
    assert.equal(plan.localFallback, true);
    assert.match(plan.executive_briefing, /\d+ NM/);
  });

  it("version anglaise", () => {
    const plan = buildLocalCustomBriefing(laRochelleBrest, "en");
    assert.ok(plan.executive_briefing.includes("Custom route"));
    assert.ok(plan.executive_briefing.includes("La Teste"));
    assert.doesNotMatch(plan.executive_briefing, /could not be reached|assistant de briefing/i);
  });

  it("Au large de Nouadhibou, le sac nomme la Mauritanie", () => {
    assert.equal(coastNameNear(18.2, -17.8, "fr"), "Mauritanie");
    assert.equal(coastNameNear(17.6, -16.9, "en"), "Mauritania");
    assert.equal(coastNameNear(46.15, -1.16, "fr"), "");
    const plan = buildLocalCustomBriefing({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { name: "A" },
          geometry: { type: "Point", coordinates: [-17.8, 18.2] },
        },
        {
          type: "Feature",
          properties: { name: "B" },
          geometry: { type: "Point", coordinates: [-16.9, 17.6] },
        },
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates: [[-17.8, 18.2], [-16.9, 17.6]] },
        },
      ],
    }, "fr");
    assert.match(plan.executive_briefing, /Mauritanie/);
    assert.ok(!/Bourgenay|Saint-Maur|La Rochelle/i.test(plan.executive_briefing));
  });
});

describe("briefing local : jambes et distance", () => {
  const many = Array.from({ length: 185 }, (_, i) => [-1.14 - i * 0.02, 44.63 + i * 0.02]);
  const twoPoints = {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { nm: 6461.4 }, geometry: { type: "LineString", coordinates: many } },
      { type: "Feature", properties: { name: "A" }, geometry: { type: "Point", coordinates: many[0] } },
      { type: "Feature", properties: { name: "B" }, geometry: { type: "Point", coordinates: many.at(-1) } },
    ],
  };

  it("2 points donnent 1 segment, pas un par sommet", () => {
    const plan = buildLocalCustomBriefing(twoPoints, "fr");
    assert.match(plan.summary, /2 points, 1 segment,/);
    assert.doesNotMatch(plan.summary, /184 segments/);
    assert.match(buildLocalCustomBriefing(twoPoints, "en").summary, /2 points, 1 segment,/);
  });

  it("la distance est celle du cadre de tracé (longueur de chaque jambe)", () => {
    const plan = buildLocalCustomBriefing(twoPoints, "fr");
    assert.match(plan.summary, /environ 6461 NM/);
    assert.equal(Math.round(legsDistanceNm(featuresToSegments(twoPoints))), 6461);
  });

  it("sans longueur de jambe, la distance suit les sommets", () => {
    const legs = featuresToSegments(laRochelleBrest);
    assert.equal(legs[0].nm, undefined);
    assert.ok(legsDistanceNm(legs) > 200 && legsDistanceNm(legs) < 300);
  });
});
