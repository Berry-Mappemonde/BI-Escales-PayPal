import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  aggregatePointFeatures,
  pointInBounds,
  quantizedCatalogBbox,
  visibleFeatureCollection,
} from "./spatialFeatures.js";

const point = (lon, lat, name = "") => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lon, lat] },
  properties: { name },
});

describe("spatialFeatures", () => {
  it("gère une bbox qui franchit l’antiméridien", () => {
    const bounds = { west: 170, south: -20, east: -170, north: 20 };
    assert.equal(pointInBounds(175, 0, bounds), true);
    assert.equal(pointInBounds(-175, 0, bounds), true);
    assert.equal(pointInBounds(0, 0, bounds), false);
  });

  it("retient les points et tracés visibles", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        point(1, 1, "visible"),
        point(20, 20, "hors carte"),
        { type: "Feature", geometry: { type: "LineString", coordinates: [[-2, 0], [2, 0]] }, properties: {} },
      ],
    };
    const result = visibleFeatureCollection(fc, { west: -5, south: -5, east: 5, north: 5 });
    assert.equal(result.features.length, 2);
  });

  it("aligne les points de la copie monde affichée", () => {
    const result = visibleFeatureCollection(
      { type: "FeatureCollection", features: [point(175, 0, "Fidji")] },
      { west: -200, south: -10, east: -160, north: 10 },
    );
    assert.equal(result.features[0].geometry.coordinates[0], -185);
  });

  it("borne les pôles de la bbox catalogue à faible zoom", () => {
    const bbox = quantizedCatalogBbox(
      { west: -450, south: -180, east: 450, north: 180 },
      2,
    );
    assert.equal(bbox, "-450.000,-90.000,450.000,90.000");
  });

  it("borne les pôles après quantification à zoom fractionnaire", () => {
    const [, south, , north] = quantizedCatalogBbox(
      { west: 0, south: -95.459, east: 318.198, north: 0 },
      3.5,
    ).split(",").map(Number);
    assert.equal(south, -90);
    assert.equal(north, 0);
  });

  it("borne les marqueurs par agrégation écran", () => {
    const features = Array.from({ length: 100 }, (_, index) => point(index / 100, index / 100));
    const aggregated = aggregatePointFeatures(features, (lon, lat) => ({ x: lon * 100, y: lat * 100 }), {
      budget: 8,
      minCellPx: 20,
    });
    assert.ok(aggregated.length <= 8);
    assert.equal(aggregated.reduce((sum, feature) => sum + (feature.properties.clusterCount || 1), 0), 100);
  });

  it("une cellule regroupée ne porte pas de nom en dur (la fiche le traduit)", () => {
    const features = Array.from({ length: 10 }, (_, index) => point(index / 1000, index / 1000, `P${index}`));
    const aggregated = aggregatePointFeatures(features, (lon, lat) => ({ x: lon * 100, y: lat * 100 }), {
      budget: 1,
      minCellPx: 50,
    });
    const cluster = aggregated.find((feature) => (feature.properties.clusterCount || 1) > 1);
    assert.ok(cluster);
    assert.equal(cluster.properties.name, undefined);
    assert.equal(cluster.properties.title, undefined);
    assert.doesNotMatch(JSON.stringify(cluster.properties), /regroup/);
  });

  it("une cellule regroupée ne porte ni le site, ni le téléphone, ni le lien du premier point", () => {
    const features = Array.from({ length: 10 }, (_, index) => ({
      ...point(index / 1000, index / 1000, `P${index}`),
      properties: { name: `P${index}`, naviguideCatalogId: `marinas:${index}`, website: "https://example.org/p0", telephone: "+33 5 46 00 00 00", url: "https://example.org/u0", source_urls: ["https://example.org/s0"] },
    }));
    const aggregated = aggregatePointFeatures(features, (lon, lat) => ({ x: lon * 100, y: lat * 100 }), { budget: 1, minCellPx: 50 });
    const cluster = aggregated.find((feature) => (feature.properties.clusterCount || 1) > 1);
    assert.ok(cluster);
    for (const key of ["website", "telephone", "url", "source_urls"]) assert.equal(cluster.properties[key], undefined, key);
    assert.ok(cluster.properties.naviguideCatalogId);
  });
});
