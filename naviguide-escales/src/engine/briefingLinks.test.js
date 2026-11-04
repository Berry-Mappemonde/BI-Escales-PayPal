import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  LAYER_FOR_KIND,
  briefingEntities,
  canFocus,
  displayName,
  entityLinks,
  googleMapsUrl,
  humanAtonName,
  layerForEntity,
  placeLabel,
  segmentBriefing,
} from "./briefingLinks.js";
import { narrateIci, narrateIciSegments } from "./iciBriefing.js";

const here = dirname(fileURLToPath(import.meta.url));

const LA_ROCHELLE = {
  at: { lat: 46.1541, lon: -1.167 },
  zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true, territory: "metropole" },
  poe: [
    { name: "La Rochelle - La Pallice", nm: 1.6, lat: 46.16, lon: -1.22, url: "https://www.douane.gouv.fr/la-rochelle" },
    { name: "Les Sables-d'Olonne - Port", nm: 58.8, lat: 46.49, lon: -1.79, url: "https://www.douane.gouv.fr/sables" },
  ],
  amp: [
    { name: "Pertuis Charentais - Filets", nm: 3.6, lat: 46.1, lon: -1.2, visit_url: "https://www.paysdelaloire.fr/amp", manager_url: "https://dirm.sud-atlantique.developpement-durable.gouv.fr", site_id: "FR9102015" },
  ],
  projects: [{ name: "Echo-Mer", nm: 0.7, lat: 46.15, lon: -1.16, url: "https://fondationdelamer.org/echo-mer" }],
  nearby: {
    marinas: [
      { name: "Bassin des Tamaris", nm: 0.3, lat: 46.152, lon: -1.164, url: null },
      { name: "Port des Minimes", nm: 0.4, lat: 46.146, lon: -1.166, url: "https://www.portlarochelle.com" },
    ],
    capitaineries: [
      { name: "Capitainerie", nm: 0.6, lat: 46.15, lon: -1.17, source: "osm-overpass" },
      { name: "Capitainerie", nm: 11.1, lat: 46.0, lon: -1.3, source: "osm-overpass" },
    ],
    wpi: [{ name: "La Rochelle", nm: 0.7, lat: 46.16, lon: -1.15, url: null }],
    anchorages: [{ name: "ZMFR GPM de La Rochelle", nm: 5.7, lat: 46.1, lon: -1.25, source: "osm-overpass" }],
  },
  science: {
    nearby: [
      { name: "Cadastre napoléonien de La Rochelle 1811", nm: 0.8, lat: 46.15, lon: -1.16, url: "https://sextant.ifremer.fr/record/abc", source: "sextant" },
      { name: "RiOMar-VOG 2024", nm: 5.2, lat: 46.1, lon: -1.2, url: "https://csr.seadatanet.org/report/x", source: "csr" },
    ],
  },
  aton: { source: "osm-overpass", nearby: [{ name: "Fort Boyard", nm: 9.5, lat: 45.999, lon: -1.214, kind: "light" }] },
  satellites: null,
  weather: null,
  emodnet: null,
  review: null,
  climatology: null,
  sources: { bi: "ok", zee: "marineregions" },
};

describe("briefingLinks — entities in writing order", () => {
  it("lists PoE → AMP → projects → marinas → capitaineries → WPI → science → anchorages → AtoN, capped like listPlaces", () => {
    const kinds = briefingEntities(LA_ROCHELLE).map((e) => e.kind);
    assert.deepEqual(kinds, [
      "poe", "poe", "amp", "project", "marina", "marina", "capitainerie", "capitainerie",
      "wpi", "science", "science", "anchorage", "aton",
    ]);
    assert.deepEqual(briefingEntities(null), []);
    const many = { nearby: { marinas: Array.from({ length: 6 }, (_, i) => ({ name: `M${i}`, lat: 1, lon: 2 })) } };
    assert.equal(briefingEntities(many).length, 3);
  });

  it("keeps coordinates, distance and a clean URL; AMP falls back to visit_url", () => {
    const [poe, , amp] = briefingEntities(LA_ROCHELLE);
    assert.equal(poe.lat, 46.16);
    assert.equal(poe.url, "https://www.douane.gouv.fr/la-rochelle");
    assert.equal(amp.url, "https://www.paysdelaloire.fr/amp");
    assert.equal(briefingEntities({ poe: [{ name: "X", url: "javascript:alert(1)", lat: 1, lon: 1 }] })[0].url, null);
  });
});

describe("briefingLinks — sheets and layers", () => {
  it("official site first, Google Maps for real places only", () => {
    const es = briefingEntities(LA_ROCHELLE);
    const minimes = es.find((e) => e.name === "Port des Minimes");
    assert.deepEqual(entityLinks(minimes).map((l) => l.kind), ["site", "maps"]);
    assert.equal(entityLinks(minimes)[0].host, "portlarochelle.com");
    const tamaris = es.find((e) => e.name === "Bassin des Tamaris");
    assert.deepEqual(entityLinks(tamaris).map((l) => l.kind), ["maps"]);
    assert.equal(entityLinks(tamaris)[0].href, googleMapsUrl(46.152, -1.164));
    const sextant = es.find((e) => e.source === "sextant");
    assert.deepEqual(entityLinks(sextant).map((l) => l.kind), ["site"]);
    assert.equal(googleMapsUrl(46.152, -1.164), "https://www.google.com/maps/search/?api=1&query=46.15200%2C-1.16400");
    assert.equal(googleMapsUrl(null, 1), null);
  });

  it("names the BI layer to switch on, science by source", () => {
    const es = briefingEntities(LA_ROCHELLE);
    assert.equal(layerForEntity(es.find((e) => e.kind === "marina")), "marinas");
    assert.equal(layerForEntity(es.find((e) => e.kind === "poe")), "poe");
    assert.equal(layerForEntity(es.find((e) => e.source === "sextant")), "sextant");
    assert.equal(layerForEntity(es.find((e) => e.source === "csr")), "csr");
    assert.equal(layerForEntity(es.find((e) => e.kind === "aton")), "aton");
    assert.equal(LAYER_FOR_KIND.science, null);
    assert.equal(canFocus(es[0]), true);
    assert.equal(canFocus({ name: "no coords" }), false);
  });
});

describe("briefingLinks — segmentation never rewrites the text", () => {
  it("joins back to the exact narrateIci() text and links every written place", () => {
    for (const lang of ["fr", "en"]) {
      const text = narrateIci(LA_ROCHELLE, lang);
      const segments = narrateIciSegments(LA_ROCHELLE, lang);
      assert.equal(segments.map((s) => s.text).join(""), text);
      const linked = segments.filter((s) => s.entity);
      const places = linked.filter((s) => s.entity.kind !== "source");
      assert.equal(places.length, briefingEntities(LA_ROCHELLE).length, `${lang}: every place is linked`);
      assert.deepEqual(linked.map((s) => s.entity.kind).slice(0, 4), ["poe", "poe", "amp", "project"]);
    }
  });

  it("maps duplicate names to the right item, in order", () => {
    const text = "Ports : capitaineries Capitainerie (0.6 nm), Capitainerie (11.1 nm).";
    const ents = briefingEntities(LA_ROCHELLE).filter((e) => e.kind === "capitainerie");
    const segs = segmentBriefing(text, ents);
    const linked = segs.filter((s) => s.entity);
    assert.equal(linked.length, 2);
    assert.equal(linked[0].entity.nm, 0.6);
    assert.equal(linked[1].entity.nm, 11.1);
    assert.equal(segs.map((s) => s.text).join(""), text);
  });

  it("skips names the text does not contain and survives an empty text", () => {
    assert.deepEqual(segmentBriefing("", briefingEntities(LA_ROCHELLE)), []);
    const segs = segmentBriefing("Rien ici.", [{ name: "Ailleurs", lat: 1, lon: 2 }]);
    assert.deepEqual(segs, [{ text: "Rien ici." }]);
    assert.deepEqual(narrateIciSegments(null), []);
  });
});

describe("briefing links — UI contract", () => {
  const sidebar = readFileSync(join(here, "..", "components", "Sidebar.jsx"), "utf8");
  const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
  const controller = readFileSync(join(here, "..", "map", "MapSceneController.js"), "utf8");
  const dossier = readFileSync(join(here, "..", "hooks", "useIciDossier.js"), "utf8");

  it("renders names as map buttons and sheets as safe external links, text untouched", () => {
    assert.match(sidebar, /function BriefingText\(/);
    assert.match(sidebar, /onClick=\{\(\) => onFocus\(e\)\}/);
    assert.match(sidebar, /target="_blank"/);
    assert.match(sidebar, /rel="noopener noreferrer"/);
    assert.match(sidebar, /data-testid="briefing-entity"/);
    assert.match(sidebar, /data-testid="briefing-source-link"/);
    assert.match(sidebar, /data-testid="briefing"/);
    assert.match(sidebar, /briefingSeeOnMap|briefingOfficialSheet|briefingGoogleMaps|briefingSourceLink/);
    assert.match(sidebar, /iciBriefingSegments\?\.length/);
    assert.match(dossier, /briefingSegments/);
  });

  it("App switches the layer on and fits boat + place through the scene API; no GET /ici, no chat", () => {
    assert.match(app, /const handleBriefingFocus = useCallback/);
    assert.match(app, /layerForEntity\(entity\)/);
    assert.match(app, /sceneApiRef\.current\?\.briefing\?\.focus\(entity, boat\)/);
    assert.match(app, /onBriefingFocus=\{handleBriefingFocus\}/);
    assert.match(controller, /focusBriefingPlace\(place, boat\)/);
    assert.match(controller, /pane: "briefing-focus"/);
    assert.match(controller, /fitBounds\(bounds\.pad/);
    assert.match(controller, /this\.callbacks\.onManualNavigation\?\.\(\)/);
    const focusFn = controller.slice(controller.indexOf("focusBriefingPlace(place, boat) {"), controller.indexOf("clearBriefingFocus() {"));
    assert.doesNotMatch(focusFn, /fetch\(|\/ici|story/);
  });
});

describe("briefingLinks — names a skipper reads", () => {
  it("turns OSM seamark types into words, keeps real names", () => {
    assert.equal(humanAtonName("buoy_lateral"), "bouée latérale");
    assert.equal(humanAtonName("buoy_special_purpose", "en"), "special buoy");
    assert.equal(humanAtonName("light_minor"), "feu");
    assert.equal(humanAtonName("Fort Boyard"), "Fort Boyard");
    assert.equal(humanAtonName("some_new_type"), "some new type");
  });

  it("cuts very long dataset titles, and the linked segment uses the same label", () => {
    const long = "Identification of SARS-CoV-2 variants by MiSeq sequencing in sewers using passive sampling";
    const label = displayName(long);
    assert.ok(label.length <= 73 && label.endsWith("…"));
    assert.equal(displayName("Port des Minimes"), "Port des Minimes");
    const d = { science: { nearby: [{ name: long, nm: 8.5, lat: 46.8, lon: 1.6, url: "https://sextant.ifremer.fr/x", source: "sextant" }] },
      aton: { source: "osm-overpass", nearby: [{ name: "buoy_lateral", nm: 19.5, lat: 47.1, lon: -2.2 }] } };
    const text = narrateIci(d, "fr");
    assert.match(text, /bouée latérale \(19,5 nm\)/);
    assert.doesNotMatch(text, /buoy_lateral|\(sextant\)|sextant\.ifremer/);
    const linked = narrateIciSegments(d, "fr").filter((s) => s.entity);
    assert.deepEqual(linked.map((s) => s.text), [label, "OpenStreetMap", "bouée latérale"]);
    assert.equal(placeLabel("aton", { name: "buoy_lateral" }), "bouée latérale");
  });
});
