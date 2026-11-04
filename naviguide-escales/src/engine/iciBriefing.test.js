import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TERRITORIAL_SEA_NM, cleanStoryText, formatIciReason, hereWithoutFalseHighSeas, highSeasRuledOut, nearestStop, nearestStopNm, replayHereFrame, climatologySentence, climatologyShownOnBanner, highSeasClaimAllowed, narrateIci, narrateIciSegments, phraseForEvent, pickFilmPhrase } from "./iciBriefing.js";
import { filmZeeBucket } from "./filmZeeStep.js";
import { KNOWN_SOURCES, SOURCE_URLS, segmentSources } from "./briefingLinks.js";

const here = dirname(fileURLToPath(import.meta.url));

const FORBIDDEN = /Ports\s*\/\s*Sécurité|AgentPanel|\/agents\/|Cruisers|Nemotron|Tavily/i;

describe("formatIciReason", () => {
  it("ne laisse pas passer overpass_unavailable en brut", () => {
    assert.match(formatIciReason("overpass_unavailable", "fr"), /Overpass/i);
    assert.match(formatIciReason("outside_us_enc;overpass_unavailable", "en"), /Outside NOAA ENC/i);
    assert.doesNotMatch(formatIciReason("overpass_unavailable", "fr"), /overpass_unavailable/);
  });
});

describe("narrateIci", () => {
  it("describes outside_us_enc as missing NOAA ENC coverage in both languages", () => {
    const dossier = { aton: { reason: "outside_us_enc" } };
    assert.match(narrateIci(dossier, "en"), /Outside NOAA ENC \(US charts\) coverage/);
    assert.match(narrateIci(dossier, "fr"), /Hors couverture des cartes NOAA \(ENC US\)/);
  });

  it("tells the bag at La Rochelle, not the whole map", () => {
    const text = narrateIci({
      zee: {
        name: "French Exclusive Economic Zone",
        mrgid: 5677,
        territory: "france_metropolitaine",
        gold: true,
      },
      poe: [
        { name: "La Rochelle", nm: 1.2, url: "https://www.douane.gouv.fr/la-rochelle" },
        { name: "Rochefort", nm: 18 },
      ],
      amp: [{ name: "Pertuis charentais", nm: 8 }],
      projects: [{ name: "Récif sentinelle", nm: 12 }],
      nearby: {
        marinas: [{ name: "Port des Minimes", nm: 2 }],
        capitaineries: [{ name: "Capitainerie La Rochelle", nm: 1 }],
        wpi: [{ name: "LA ROCHELLE", nm: 1.1 }],
      },
      science: {
        nearby: [
          { name: "Pertuis charentais bathymétrie", source: "sextant", nm: 6, url: "https://sextant.ifremer.fr/x" },
          { name: "6901234", source: "argo", kind: "argo_float", wmo: "6901234", nm: 18 },
        ],
      },
      polar: { boat: "Leopard 46", speedKnots: 7.2, etaHours: 42 },
      marks: [{ kind: "leg", from: "La Rochelle", to: "Fort-de-France", vehicle: "main" }],
      event: { type: "zee-enter", name: "French Exclusive Economic Zone", mrgid: 5677 },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");

    assert.match(text, /Le bateau navigue dans/);
    assert.match(text, /formalités d’entrée passent par des ports officiels/);
    assert.match(text, /La Rochelle/);
    assert.match(text, /Ports d’entrée officiels les plus proches : La Rochelle \(1,2 nm\)/);
    assert.match(text, /Fiches d’entrée : douane\.gouv\.fr/);
    assert.doesNotMatch(text, /https:\/\/www\.douane\.gouv\.fr\/la-rochelle/);
    assert.match(text, /À 8 milles de Pertuis charentais/);
    assert.match(text, /Pertuis/);
    assert.match(text, /On vient d’entrer/);
    assert.match(text, /Cap sur Fort-de-France[^.]*depuis La Rochelle/);
    assert.match(text, /7,2 nœuds/);
    assert.match(text, /de mer/);
    assert.doesNotMatch(text, /Polaire chargée|Polar loaded/);
    assert.match(text, /Données scientifiques disponibles autour du bateau/);
    assert.match(text, /Pertuis charentais bathymétrie \(6 nm\)/);
    assert.match(text, /6901234 \(18 nm\)/);
    assert.doesNotMatch(text, /\(sextant\)|\(argo\)|sextant\.ifremer\.fr/); // source + host live in the link
    assert.doesNotMatch(text, FORBIDDEN);
    assert.doesNotMatch(text, /4500|mappemonde entière|toute la carte/i);
  });

  it("does not call a sea leg overland just because the boat is in port", () => {
    const text = narrateIci({
      zee: { name: "À terre (France)", mrgid: null, gold: false, ashore: true },
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      polar: { boat: "Leopard 46", etaHours: 313.95 },
      marks: [{
        kind: "leg",
        from: "La Rochelle",
        to: "Ajaccio (Corse)",
        vehicle: "land",
      }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Cap sur Ajaccio \(Corse\) depuis La Rochelle/);
    assert.match(text, /13 jours de mer/);
    assert.doesNotMatch(text, /pas encore en mer/);
    assert.doesNotMatch(text, /313 h/);
  });

  it("treats Berry → La Rochelle as overland even if the ZEE bag is empty", () => {
    const text = narrateIci({
      zee: null,
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      polar: { etaHours: 4 },
      marks: [{
        kind: "leg",
        from: "Saint-Maur (Berry, Indre)",
        to: "La Rochelle",
        vehicle: "main",
      }],
      sources: { zee: "error" },
    }, "fr");
    assert.match(text, /Étape terrestre de Saint-Maur \(Indre\) vers La Rochelle/);
    assert.doesNotMatch(text, /Berry|Corse/);
    assert.match(text, /encore 4 h de route/);
    assert.match(text, /pas encore en mer/);
    assert.doesNotMatch(text, /encore 4 h de mer/);
  });

  it("calls Saint-Maur → La Rochelle overland, not sea time", () => {
    const id = "S2B_MSIL2A_20260914T105619_N0512_R094_T31TDM_20260914T145142";
    const text = narrateIci({
      zee: { name: "À terre (France)", mrgid: null, gold: false, ashore: true },
      poe: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      polar: { boat: "Leopard 46", etaHours: 4 },
      marks: [{
        kind: "leg",
        from: "Saint-Maur (Berry, Indre)",
        to: "La Rochelle",
        vehicle: "land",
      }],
      satellites: {
        kind: "observation",
        scene: { product: "sentinel-2-l2a", id, datetime: "2026-09-14T10:56:19Z" },
      },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Étape terrestre de Saint-Maur \(Indre\) vers La Rochelle/);
    assert.doesNotMatch(text, /Berry/);
    assert.match(text, /encore 4 h de route/);
    assert.match(text, /pas encore en mer/);
    assert.doesNotMatch(text, /encore 4 h de mer/);
    // the raw scene id no longer floods the box: satellite, tile and date are written instead
    assert.match(text, /Sentinel-2 \(S2B, tuile T31TDM\) du 14 septembre 2026 \(observation\)/);
    assert.doesNotMatch(text, new RegExp(id));
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("keeps the ICI briefing inside the sidebar box", () => {
    const sidebar = readFileSync(join(here, "../components/Sidebar.jsx"), "utf8");
    assert.match(sidebar, /ici-briefing/);
    assert.match(sidebar, /overflow-x-hidden/);
    assert.match(sidebar, /overflow-wrap:anywhere/);
  });

  it("says inland outside the EEZ without inventing ports of entry", () => {
    const text = narrateIci({
      zee: { name: "À terre (France)", mrgid: null, gold: false, ashore: true },
      poe: [],
      amp: [],
      projects: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /à terre/i);
    assert.match(text, /hors de toute ZEE/);
    assert.doesNotMatch(text, /Ports d’entrée officiels/);
  });

  it("null ZEE en erreur = ni haute mer ni erreur de nommage", () => {
    const text = narrateIci({
      zee: null,
      poe: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      sources: { zee: "error", bi: "ok" },
    }, "fr");
    // Missing EEZ data is not a « no EEZ here » answer.
    assert.doesNotMatch(text, /haute mer/i);
    assert.doesNotMatch(text, /pas pu nommer/);
    assert.doesNotMatch(text, /Marine Regions\/VLIZ n’a pas répondu/);
  });

  it("absent EEZ data never claims the high seas", () => {
    for (const lang of ["fr", "en"]) {
      const text = narrateIci({
        zee: null,
        poe: [],
        nearby: { marinas: [], capitaineries: [], wpi: [] },
        sources: { zee: null, bi: "ok" },
      }, lang);
      assert.doesNotMatch(text, /haute mer|high seas/i);
    }
  });

  it("unavailable EEZ lookup never claims the high seas", () => {
    for (const zee of [
      { name: null, mrgid: null, gold: false, unknown: true },
      { name: "Haute mer", mrgid: null, gold: false },
    ]) {
      const dossier = {
        zee,
        poe: [],
        nearby: { marinas: [], capitaineries: [], wpi: [] },
        sources: { zee: "unavailable", bi: "ok" },
      };
      assert.equal(highSeasClaimAllowed(dossier), false);
      assert.doesNotMatch(narrateIci(dossier, "fr"), /haute mer/i);
      assert.doesNotMatch(narrateIci(dossier, "en"), /high seas/i);
    }
  });

  it("near a known port: never the high seas, even with no EEZ found", () => {
    const base = {
      zee: { name: "Haute mer", mrgid: null, gold: false },
      sources: { zee: "vliz-local", bi: "ok" },
    };
    const ajaccio = {
      ...base,
      poe: [],
      nearby: { marinas: [{ name: "Port Tino Rossi", nm: 0.2 }], capitaineries: [], wpi: [] },
    };
    assert.equal(highSeasClaimAllowed(ajaccio), false);
    assert.doesNotMatch(narrateIci(ajaccio, "fr"), /haute mer/i);
    const poe = { ...base, poe: [{ name: "Ajaccio", nm: 3 }], nearby: { marinas: [], capitaineries: [], wpi: [] } };
    assert.equal(highSeasClaimAllowed(poe), false);
  });

  it("in the territorial sea (≤ 12 nm from a port): never the high seas", () => {
    const at = (nm) => ({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      poe: [],
      nearby: { marinas: [], capitaineries: [], wpi: [{ name: "Ajaccio", nm }] },
      sources: { zee: "vliz-local", bi: "ok" },
    });
    assert.equal(TERRITORIAL_SEA_NM, 12);
    assert.equal(highSeasClaimAllowed(at(11.9)), false);
    assert.doesNotMatch(narrateIci(at(11.9), "en"), /high seas/i);
    // Far offshore with a confirmed « no EEZ » answer it still says high seas.
    assert.equal(highSeasClaimAllowed(at(40)), true);
    assert.match(narrateIci(at(40), "en"), /high seas/i);
  });

  it("says high seas without inventing ports of entry", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      poe: [],
      amp: [],
      projects: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /haute mer/i);
    assert.doesNotMatch(text, /Ports d’entrée officiels/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("stays honest if Blue Intelligence is silent", () => {
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, territory: "france_metropolitaine", gold: false },
      poe: [],
      amp: [],
      projects: [],
      nearby: { marinas: [], capitaineries: [], wpi: [{ name: "LA ROCHELLE", nm: 1 }] },
      sources: { zee: "marineregions", bi: "unavailable" },
    }, "fr");
    assert.match(text, /Blue Intelligence n’ont pas répondu/);
    assert.match(text, /La Rochelle/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("Une perle mince ne raconte pas l’échec BI", () => {
    const thin = {
      pearl: "thin",
      thin: true,
      zee: { name: "Mauritanian Exclusive Economic Zone", mrgid: 8492 },
      poe: [],
      amp: [],
      projects: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      sources: { zee: "marineregions", bi: "unavailable" },
    };
    const text = narrateIci(thin, "fr");
    assert.doesNotMatch(text, /Blue Intelligence n’ont pas répondu/);
    assert.doesNotMatch(text, /ports WPI sont conservés/);
  });

  it("does not dump a list of projects", () => {
    const projects = Array.from({ length: 40 }, (_, i) => ({ name: `Projet ${i}`, nm: i + 1 }));
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      poe: [],
      amp: [],
      projects,
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Projet 0/);
    assert.doesNotMatch(text, /Projet 10/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("has an English story of the same bag", () => {
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, territory: "guyane", gold: true },
      poe: [{ name: "Cayenne", nm: 2 }],
      amp: [],
      projects: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      marks: [{ kind: "leg", from: "Cayenne", vehicle: "plane", phase: "air-out" }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "en");
    assert.match(text, /French Guiana/);
    assert.match(text, /at the dock/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("cites GEBCO when an offshore sounding is in the bag", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      poe: [],
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      depthOffshore: -3200,
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /GEBCO/);
    assert.match(text, /3200/);
    const silent = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      depthOffshore: 0,
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.doesNotMatch(silent, /GEBCO/);
  });

  it("tells the atlas point under the boat, not a forecast", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      climatology: {
        kind: "climatology",
        source: "atlas",
        month: 6,
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        point: {
          kind: "climatology",
          wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } },
          wave: { hs_p50_m: 1.4, hs_p90_m: 2.8, period_s: 4.1, dir_deg: 284.6 },
          current: { speed_knots: 0.4, direction_to_deg: 270 },
          cyclone: { crossings_if_leg: { count: 2 } },
        },
      },
      sources: { zee: "marineregions", bi: "ok", climatology: "atlas" },
    }, "fr");
    assert.equal(climatologyShownOnBanner({
      climatology: {
        kind: "climatology", source: "atlas", month: 6,
        point: { wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } } },
      },
    }), true);
    assert.doesNotMatch(text, /Climatologie de/);
    const climo = climatologySentence({
      climatology: {
        kind: "climatology",
        source: "atlas",
        month: 6,
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        point: {
          kind: "climatology",
          wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } },
          wave: { hs_p50_m: 1.4, hs_p90_m: 2.8, period_s: 4.1, dir_deg: 284.6 },
          current: { speed_knots: 0.4, direction_to_deg: 270 },
          cyclone: { crossings_if_leg: { count: 2 } },
        },
      },
    }, "fr");
    assert.match(climo, /Climatologie de/);
    assert.match(climo, /atlas Copernicus Marine/);
    assert.match(climo, /vent typique 16,2 kn/);
    assert.match(climo, /mer 1,4 m en moyenne, 2,8 m les jours agités \(P90\)/);
    assert.match(climo, /période 4,1 s/);
    assert.match(climo, /de ONO \(285°\)/);
    assert.match(climo, /courant 0,4/);
    assert.match(climo, /IBTrACS/);
    assert.doesNotMatch(climo, /forecast|GRIB/i);
  });

  it("tells visit vs manager, OSM moorings, AtoN, satellite observation and forecast weather", () => {
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      amp: [{
        name: "Pertuis charentais",
        nm: 8,
        visit_url: "https://parc-marin.fr/visite",
        manager_url: "https://parc-marin.fr",
      }],
      nearby: {
        marinas: [],
        capitaineries: [],
        wpi: [],
        anchorages: [{ name: "Mouillage des Minimes", nm: 1.2 }],
      },
      aton: { nearby: [{ name: "Feu des Minimes", nm: 0.8 }], source: "osm-overpass" },
      satellites: {
        kind: "observation",
        source: "cdse-stac",
        scene: {
          kind: "observation",
          product: "sentinel-2-l2a",
          id: "S2C_MSIL2A_X",
          datetime: "2026-09-12T11:06:31Z",
        },
        derived: {
          coastline: { value: null, reason: "not_generated" },
          sdb: { value: null, reason: "not_generated" },
        },
      },
      weather: {
        kind: "forecast",
        source: "openmeteo-gfs",
        model: "GFS 0.25° / GFS-Wave 0.25° (Open-Meteo)",
        wind: { kind: "forecast", speedKnots: 12.4, dirFromDeg: 280 },
        wave: { kind: "forecast", hs: 1.1, dirDeg: 270, periodS: 6.5 },
        current: { kind: "forecast", source: "noaa-rtofs", speedKnots: 0.58, dirToDeg: 247 },
        current_reason: null,
      },
      emodnet: {
        kind: "observation",
        bathy: { depth_m: 18.4 },
        seabed: { label: "sand" },
        cables: { nearby: false, reason: "no_feature_at_point" },
      },
      review: { zee: { gold_on: true }, amp: { gold_on: false } },
      climatology: {
        kind: "climatology",
        source: "atlas",
        month: 6,
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        rose: { stat: "rose", directions_from: [{ dir_deg: 45, pct: 22 }], calm_pct: 4, gale_pct: 1.5 },
        point: {
          kind: "climatology",
          wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } },
          current: { speed_knots: 0.4, direction_to_deg: 270 },
          cyclone: { nearby: 0 },
        },
      },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /À 8 milles de Pertuis charentais/);
    assert.doesNotMatch(text, /parc-marin\.fr/); // visit / manager pages are links now
    assert.match(text, /Mouillage des Minimes/);
    assert.match(text, /Balisage \(OpenStreetMap\) : Feu des Minimes/);
    assert.match(text, /Dernière image satellite \(CDSE\) : Sentinel-2/);
    assert.match(text, /\(observation\)/);
    assert.match(text, /pas encore calculé/);
    assert.doesNotMatch(text, /not_generated|sentinel-2-l2a/);
    assert.match(text, /Prévision météo/);
    assert.match(text, /vent 12,4 kn de O \(280°\)/);
    assert.match(text, /mer 1,1 m de O \(270°\), période 6,5 s/);
    assert.match(text, /courant 0,58 kn vers OSO \(247°\) \(NOAA\/RTOFS\)/);
    assert.match(text, /EMODnet/);
    assert.match(text, /18,4/);
    assert.doesNotMatch(text, /Climatologie de|rose des vents disponible/);
    const climo = climatologySentence({
      climatology: {
        kind: "climatology",
        source: "atlas",
        month: 6,
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        rose: { stat: "rose", directions_from: [{ dir_deg: 45, pct: 22 }], calm_pct: 4, gale_pct: 1.5 },
        point: {
          kind: "climatology",
          wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } },
          current: { speed_knots: 0.4, direction_to_deg: 270 },
          cyclone: { nearby: 0 },
        },
      },
    }, "fr");
    assert.match(climo, /rose des vents disponible/);
    assert.match(climo, /calme 4/);
    assert.match(climo, /courant 0,4 kn vers O \(270°\)/);
    assert.match(climo, /cyclones historiques \(IBTrACS\) : aucun à proximité/);
    assert.match(text, /formalités ZEE vérifiées, règles AMP non vérifiées/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("A rich pearl tells seabed and aids to navigation; weather, satellite and the sheet stay live-only", () => {
    const pearl = {
      pearl: "rich",
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677 },
      amp: [],
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      aton: { nearby: [{ name: "Feu des Minimes", nm: 0.8 }], source: "osm-overpass" },
      emodnet: { kind: "observation", bathy: { depth_m: 18.4 }, seabed: { label: "sand" }, cables: { nearby: false, reason: "no_feature_at_point" } },
      weather: { kind: null, reason: "not_in_along_pearl" },
      satellites: { kind: null, reason: "not_in_along_pearl" },
      review: { reason: "not_in_along_pearl" },
      sources: { zee: "marineregions", bi: "ok" },
    };
    const rich = narrateIci(pearl, "fr");
    assert.match(rich, /Balisage \(OpenStreetMap\) : Feu des Minimes/);
    assert.match(rich, /EMODnet/);
    assert.match(rich, /18,4/);
    assert.doesNotMatch(rich, /perle|pearl|météo|satellite|Sentinel|Gold|fiche de vérification/i);
    // A thin pearl (the server sends empty seabed / aids with a reason) says nothing about them.
    const thin = narrateIci({ ...pearl, pearl: "thin", aton: { nearby: [], reason: "not_in_along_pearl" }, emodnet: { reason: "not_in_along_pearl" } }, "fr");
    assert.doesNotMatch(thin, /EMODnet|18,4|Balisage/);
    assert.doesNotMatch(thin, /perle|pearl|météo|satellite/i);
  });

  it("says weather is loading while the shared pipeline is pending", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      weather: { kind: "forecast", status: "pending", refreshing: true, wind: null, wave: null },
      sources: { zee: "marineregions" },
    }, "fr");
    assert.match(text, /Prévision météo : chargement/);
    assert.doesNotMatch(text, /vide/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("does not invent a satellite scene when the product is missing", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      satellites: {
        kind: "observation",
        scene: null,
        reason: "cdse_stac_unavailable:HTTPStatusError",
        derived: { coastline: { value: null, reason: "not_generated" } },
      },
      weather: { kind: "forecast", wind: null, reason: "openmeteo_unavailable:HTTPStatusError" },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Aucune image satellite récente ici \(cdse_stac_unavailable/);
    assert.match(text, /Prévision météo/);
    assert.doesNotMatch(text, /Sentinel-2 L2A 20/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("says current null only when RTOFS is dead or off-grid", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      weather: {
        kind: "forecast",
        wind: { kind: "forecast", speedKnots: 8, dirFromDeg: 90 },
        current: null,
        current_reason: "off_grid",
      },
      sources: { zee: "marineregions" },
    }, "fr");
    assert.match(text, /courant : hors de la grille du modèle/);
    assert.doesNotMatch(text, /off_grid|null/);
    assert.doesNotMatch(text, /rtofs_not_ingested/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("says fonds null when EMODnet has a map footprint but no Folk class", () => {
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      emodnet: {
        kind: "observation",
        bathy: { depth_m: 2.3 },
        seabed: { label: null, reason: "no_substrate_class" },
        cables: { nearby: false, reason: "no_feature_at_point" },
      },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Fond \(EMODnet, observation\) : 2,3 m sur la carte ; nature du fond non classée ici/);
    assert.doesNotMatch(text, /no_substrate_class|DTM/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("cites kind on a wind-shift and never mentions Nemotron", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      event: {
        type: "wind-shift",
        payload: {
          tws: 18,
          twd: 240,
          dTws: 10,
          kind: "forecast",
          source: "GFS",
          tavily: null,
          nvidia: null,
        },
      },
      sources: { zee: "marineregions" },
    }, "fr");
    assert.match(text, /Vent 18 kn \/ 240°/);
    assert.match(text, /kind: forecast/);
    assert.match(text, /\+10 kn/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("tells a Suivre rain refuge from the pack, not a model", () => {
    const text = phraseForEvent({
      type: "marina-refuge",
      payload: {
        harbour: { name: "Port des Minimes", nm: 6 },
        rainMm: 6,
        kind: "forecast",
      },
    }, "fr");
    assert.match(text, /Pluie 6 mm\/h \(GFS\)/);
    assert.match(text, /Repli : Port des Minimes à 6 nm/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("pickFilmPhrase reads the bag filmPhrases in the UI language", () => {
    const bag = {
      filmPhrases: {
        "zee-enter": { fr: "Le 15 mai, les eaux espagnoles.", en: "On 15 May, Spanish waters." },
        "amp-enter:Cabrera": { fr: "Le 16 mai, le bateau entre dans l'aire marine protégée Cabrera." },
      },
    };
    assert.equal(
      pickFilmPhrase({ type: "zee-enter" }, bag, "fr"),
      "Le 15 mai, les eaux espagnoles.",
    );
    assert.equal(
      pickFilmPhrase({ type: "zee-enter" }, bag, "en"),
      "On 15 May, Spanish waters.",
    );
    assert.match(
      pickFilmPhrase({ type: "amp-enter", name: "Cabrera", payload: { amp: { name: "Cabrera" } } }, bag, "fr"),
      /Cabrera/,
    );
  });

  it("prefers the server film phrase over the local template", () => {
    const text = phraseForEvent({
      type: "zee-enter",
      name: "Spain",
      filmPhrase: "Le 15 mai, les eaux espagnoles.",
    }, "fr");
    assert.equal(text, "Le 15 mai, les eaux espagnoles.");
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("uses a ready story only on Rédigé; Brut keeps the film phrase", () => {
    const ev = {
      type: "zee-enter",
      name: "Spain",
      filmPhrase: "Le 15 mai, les eaux espagnoles.",
      phrase: "On vient d’entrer dans Spain.",
      story: { status: "ready", text: "Récit Super : on entre dans les eaux espagnoles." },
    };
    assert.equal(phraseForEvent(ev, "fr"), "Le 15 mai, les eaux espagnoles.");
    assert.equal(phraseForEvent(ev, "fr", { written: false }), "Le 15 mai, les eaux espagnoles.");
    assert.equal(phraseForEvent(ev, "fr", { written: true }), "Récit Super : on entre dans les eaux espagnoles.");
    assert.doesNotMatch(phraseForEvent(ev, "fr", { written: true }), FORBIDDEN);
  });

  it("a story about the machinery is cleaned, or replaced by the local phrase (revue du 19 sept.)", () => {
    const verbose = phraseForEvent({
      type: "poe-ahead",
      phrase: "Port d’entrée officiel devant : Porto-Vecchio (292 nm).",
      story: {
        status: "ready",
        text: "**Briefing nautique**\n\nLe port d’entrée officiel se situe à Porto-Vecchio, à 292,3 nm. "
          + "L’évènement est classé comme poe-ahead et porte l’identifiant poe-ahead:5682. "
          + "Il a été jugé now avec la raison playhead. Le navire, un Leopard 46 de 14 m et 1,4 m de tirant d’eau, est en croisière. "
          + "Aucune information supplémentaire sur la période ou un DOI n’est disponible.",
      },
    }, "fr", { written: true });
    assert.equal(verbose, "Le port d’entrée officiel se situe à Porto-Vecchio, à 292,3 nm.");
    const onlyMeta = phraseForEvent({
      type: "zee-exit",
      phrase: "Retour en haute mer — plus de ZEE à déclarer.",
      story: { status: "ready", text: "L’événement zee-exit est classé info. La décision a été prise immédiatement (juge)." },
    }, "fr", { written: true });
    assert.equal(onlyMeta, "Retour en haute mer — plus de ZEE à déclarer.");
    assert.equal(cleanStoryText(null), "");
  });

  it("tells a ZEE ahead on the track", () => {
    const text = phraseForEvent({
      type: "zee-ahead",
      whenNm: 40,
      name: "Spanish Exclusive Economic Zone",
      payload: { zee: { name: "Spanish Exclusive Economic Zone", mrgid: 5693 }, whenNm: 40 },
    }, "fr");
    assert.match(text, /Devant dans 40 nm/);
    assert.match(text, /les eaux espagnoles/);
    assert.doesNotMatch(text, /Exclusive Economic Zone/i);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("tells an AMP ahead on the track", () => {
    const text = phraseForEvent({
      type: "amp-ahead",
      whenNm: 40,
      payload: {
        amp: { name: "Cabrera", visitable: true },
        visitable: true,
        whenNm: 40,
      },
    }, "fr");
    assert.match(text, /AMP sur le trait dans 40 nm/);
    assert.match(text, /Cabrera/);
    assert.doesNotMatch(text, FORBIDDEN);
  });

  it("summarises a group digest", () => {
    const text = phraseForEvent({
      type: "group",
      digest: { fr: "Depuis cette jambe : zee-enter + amp-enter.", en: "Along this leg: zee-enter + amp-enter." },
      payload: { members: ["zee-enter", "amp-enter"] },
    }, "fr");
    assert.match(text, /zee-enter \+ amp-enter/);
  });

  it("says shelf or grounding with the skipper's depth threshold, never haut-fond for 15 m", () => {
    const shelf = phraseForEvent({
      type: "depth-alert",
      payload: { depthM: 12.4, source: "emodnet", alertM: 15, label: "plateau" },
    }, "fr");
    assert.match(shelf, /^On approche du plateau : 12\.4 m sondés, sous 15 m/);
    assert.doesNotMatch(shelf, /Haut-fond/);
    const ground = phraseForEvent({
      type: "depth-alert",
      payload: { depthM: 4.1, source: "gebco", alertM: 5, label: "talonnage" },
    }, "en");
    assert.match(ground, /^Grounding risk: 4\.1 m sounded, under 5 m/);
    const legacy = phraseForEvent({ type: "depth-alert", payload: { depthM: 9, source: "emodnet" } }, "fr");
    assert.match(legacy, /^Haut-fond 9 m/);
  });

  const NC = {
    zee: {
      name: "New Caledonia Exclusive Economic Zone",
      mrgid: 8312,
      territory: "nouvelle_caledonie",
      gold: true,
    },
    poe: [],
    sources: { zee: "marineregions", bi: "ok" },
  };
  const NC_FILM = {
    fr: "Le 12 octobre, les eaux de Nouvelle-Calédonie.",
    en: "On 12 October, the waters of New Caledonia.",
  };

  it("ouvre sur la phrase film de la ZEE, en français et en anglais", () => {
    const bag = { ...NC, filmPhrases: { "zee-enter": NC_FILM } };
    const fr = narrateIci(bag, "fr");
    assert.match(fr, /^Le 12 octobre, les eaux de Nouvelle-Calédonie\./);
    assert.match(fr, /Les formalités d’entrée passent par des ports officiels, listés ci-dessous\./);
    assert.equal((fr.match(/formalités/gi) || []).length, 1);
    assert.doesNotMatch(fr, /Le bateau navigue dans/);
    const en = narrateIci(bag, "en");
    assert.match(en, /^On 12 October, the waters of New Caledonia\./);
    assert.match(en, /Entry formalities go through official ports of entry, listed below\./);
    assert.equal((en.match(/formalit/gi) || []).length, 1);
    assert.doesNotMatch(en, /The boat is sailing in/);
  });

  it("sans filmPhrases, la fiche reste sur la phrase actuelle", () => {
    const fr = narrateIci(NC, "fr");
    assert.match(fr, /Le bateau navigue dans/);
    assert.match(fr, /formalités d’entrée passent par des ports officiels/);
    const en = narrateIci(NC, "en");
    assert.match(en, /The boat is sailing in/);
    assert.match(en, /Entry formalities go through official ports of entry/);
  });

  it("n'ajoute pas les formalités déjà dites par la phrase film", () => {
    const bag = {
      ...NC,
      filmPhrases: {
        "zee-enter": {
          fr: "Le 12 octobre, les eaux de Nouvelle-Calédonie. Les formalités d’entrée passent par Nouméa.",
          en: "On 12 October, the waters of New Caledonia. Entry formalities go through Nouméa.",
        },
      },
    };
    const fr = narrateIci(bag, "fr");
    assert.equal((fr.match(/formalités/gi) || []).length, 1);
    assert.doesNotMatch(fr, /listés ci-dessous/);
    const en = narrateIci(bag, "en");
    assert.equal((en.match(/formalit/gi) || []).length, 1);
    assert.doesNotMatch(en, /listed below/);
  });

  it("préfère zee-enter à zee-ahead et à zee-exit", () => {
    const fr = narrateIci({
      ...NC,
      filmPhrases: {
        "zee-exit": { fr: "Retour en haute mer — plus de ZEE à déclarer.", en: "Back on the high seas." },
        "zee-ahead": { fr: "Devant : les eaux fidjiennes.", en: "Ahead: Fijian waters." },
        "zee-enter": NC_FILM,
      },
    }, "fr");
    assert.match(fr, /^Le 12 octobre, les eaux de Nouvelle-Calédonie\./);
    assert.doesNotMatch(fr, /eaux fidjiennes|haute mer/);
  });

  it("ne recolle pas la ligne d'événement du même type", () => {
    const text = narrateIci({
      ...NC,
      filmPhrases: { "zee-enter": NC_FILM },
      event: {
        type: "zee-enter",
        name: "New Caledonia Exclusive Economic Zone",
        mrgid: 8312,
        filmPhrase: NC_FILM.fr,
      },
    }, "fr");
    assert.equal((text.match(/les eaux de Nouvelle-Calédonie/g) || []).length, 1);
    assert.doesNotMatch(text, /On vient d’entrer/);
    const other = narrateIci({
      ...NC,
      filmPhrases: { "zee-enter": NC_FILM },
      event: {
        type: "wind-shift",
        payload: { tws: 18, twd: 240, dTws: 10, kind: "forecast", source: "GFS" },
      },
    }, "fr");
    assert.match(other, /^Le 12 octobre, les eaux de Nouvelle-Calédonie\./);
    assert.match(other, /Vent 18 kn \/ 240°/);
  });

  it("prend la phrase film du port nommé, en français et en anglais", () => {
    const bag = {
      zee: {
        name: "New Caledonia Exclusive Economic Zone",
        mrgid: 8312,
        territory: "nouvelle_caledonie",
        gold: true,
      },
      poe: [{ name: "Nouméa", nm: 12 }],
      filmPhrases: {
        "poe-ahead:Nouméa": {
          fr: "Le 12 octobre, devant Nouméa.",
          en: "On 12 October, off Nouméa.",
        },
      },
      event: { type: "poe-ahead", name: "Nouméa", payload: { poe: { name: "Nouméa", nm: 12 } } },
      sources: { zee: "marineregions", bi: "ok" },
    };
    const fr = narrateIci(bag, "fr");
    assert.match(fr, /Le 12 octobre, devant Nouméa\./);
    assert.equal((fr.match(/devant Nouméa/g) || []).length, 1);
    assert.doesNotMatch(fr, /Port d’entrée officiel devant/);
    assert.doesNotMatch(fr, /Aucun port d’entrée officiel/);
    assert.doesNotMatch(fr, /Ports d’entrée officiels les plus proches/);
    const en = narrateIci(bag, "en");
    assert.match(en, /On 12 October, off Nouméa\./);
    assert.doesNotMatch(en, /Nearest official ports of entry/);
    assert.doesNotMatch(en, /No official port of entry is known/);
  });

  it("dit la phrase film du port d'entrée une seule fois", () => {
    const absence = "Aucun port d’entrée officiel n’est connu pour cette ZEE.";
    const absenceEn = "No official port of entry is known for this EEZ.";
    const bag = {
      zee: { name: "Spanish Exclusive Economic Zone", mrgid: 5693, gold: false },
      poe: [],
      filmPhrases: { "poe-ahead": { fr: absence, en: absenceEn } },
      event: { type: "poe-ahead", filmPhrase: absence },
      sources: { zee: "marineregions", bi: "ok" },
    };
    const fr = narrateIci(bag, "fr");
    assert.equal((fr.match(/Aucun port d’entrée officiel/g) || []).length, 1);
    const en = narrateIci(bag, "en");
    assert.equal((en.match(/No official port of entry is known/g) || []).length, 1);
  });

  it("en haute mer, seule une phrase zee-exit remplace la phrase actuelle", () => {
    const high = {
      zee: { name: "Haute mer", mrgid: null, gold: false },
      poe: [],
      sources: { zee: "marineregions", bi: "ok" },
    };
    assert.match(narrateIci(high, "fr"), /haute mer/i);
    const stale = narrateIci({
      ...high,
      filmPhrases: { "zee-enter": NC_FILM },
    }, "fr");
    assert.match(stale, /Le bateau est en haute mer/);
    assert.doesNotMatch(stale, /Nouvelle-Calédonie/);
    const exit = narrateIci({
      ...high,
      filmPhrases: {
        "zee-exit": {
          fr: "Retour en haute mer — plus de ZEE à déclarer.",
          en: "The boat is back on the high seas — no EEZ to clear.",
        },
      },
    }, "fr");
    assert.match(exit, /^Retour en haute mer — plus de ZEE à déclarer\./);
  });
});

const FULL_BAG = {
  zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true, territory: "france_metropolitaine" },
  poe: [{ name: "La Rochelle", nm: 1.2, url: "https://www.douane.gouv.fr/la-rochelle" }],
  amp: [{ name: "Pertuis charentais", nm: 8 }],
  nearby: { marinas: [{ name: "Port des Minimes", nm: 2 }], capitaineries: [], wpi: [] },
  aton: { nearby: [{ name: "Feu des Minimes", nm: 0.8 }], source: "osm-overpass" },
  satellites: {
    kind: "observation",
    source: "cdse-stac",
    scene: {
      product: "sentinel-2-l2a",
      id: "S2B_MSIL2A_20260914T105619_N0512_R094_T31TDM_20260914T145142",
      datetime: "2026-09-14T10:56:19Z",
    },
  },
  weather: {
    kind: "forecast",
    source: "openmeteo-gfs",
    model: "GFS 0.25° (Open-Meteo)",
    wind: { kind: "forecast", speedKnots: 12.4, dirFromDeg: 280 },
    current: { kind: "forecast", source: "noaa-rtofs", speedKnots: 0.58, dirToDeg: 247 },
  },
  emodnet: { kind: "observation", bathy: { depth_m: 18.4 }, seabed: { label: "sand" } },
  depthOffshore: -3200,
  climatology: {
    kind: "climatology",
    source: "atlas",
    month: 6,
    point: { wind_atlas: { most_likely: { speed_knots: 16.2, dir_deg: 55 } } },
  },
  polar: { boat: "Leopard 46", speedKnots: 7.2, etaHours: 42 },
  marks: [{ kind: "leg", from: "La Rochelle", to: "Fort-de-France", vehicle: "main" }],
  sources: { zee: "error", bi: "ok" },
};

function briefingSentences(text) {
  return text.split(/\n\n+|(?<=\.)\s+/).map((s) => s.trim()).filter(Boolean);
}

describe("Sources liées, pas de redite", () => {
  it("chaque source connue produit un lien", () => {
    const cited = KNOWN_SOURCES.join(" · ");
    const segs = segmentSources(cited);
    assert.equal(segs.map((s) => s.text).join(""), cited);
    for (const name of KNOWN_SOURCES) {
      const hit = segs.find((s) => s.text === name && s.entity);
      assert.ok(hit, `${name} doit produire un lien`);
      assert.equal(hit.entity.url, SOURCE_URLS[name]);
      assert.equal(hit.entity.kind, "source");
    }
    const live = narrateIciSegments(FULL_BAG, "fr");
    assert.equal(live.map((s) => s.text).join(""), narrateIci(FULL_BAG, "fr"));
    const linked = new Set(live.filter((s) => s.entity?.kind === "source").map((s) => s.text));
    for (const name of ["Open-Meteo", "NOAA/RTOFS", "EMODnet", "GEBCO", "Marine Regions/VLIZ", "OpenStreetMap", "douane.gouv.fr", "CDSE"]) {
      assert.ok(linked.has(name), `${name} cité dans le sac doit être un lien`);
    }
  });

  it("aucune phrase dupliquée dans un briefing complet ; polaire hors briefing, climatologie hors briefing", () => {
    const text = narrateIci(FULL_BAG, "fr");
    const sentences = briefingSentences(text);
    assert.equal(new Set(sentences).size, sentences.length, `doublon : ${sentences.join(" | ")}`);
    assert.doesNotMatch(text, /Polaire chargée|Polar loaded/);
    assert.equal(climatologyShownOnBanner(FULL_BAG), true);
    assert.doesNotMatch(text, /Climatologie de/);
    const silent = narrateIci({
      ...FULL_BAG,
      climatology: { source: "unavailable", month: 6 },
    }, "fr");
    assert.match(silent, /atlas de climatologie n’a pas répondu/);
    assert.equal((silent.match(/atlas de climatologie n’a pas répondu/g) || []).length, 1);
  });
});

describe("AmpSentence dans / à N milles", () => {
  it("dit « dans l'aire marine protégée » quand inside", () => {
    const text = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      amp: [{ name: "Strait of Bonifacio", inside: true, nm: 0, source: "polygon", siteId: "AIFRA7" }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Dans l'aire marine protégée Strait of Bonifacio/);
    assert.doesNotMatch(text, /À 0 milles/);
  });

  it("ajoute la circulation régulée quand le bateau traverse", () => {
    const text = narrateIci({
      zee: { name: "Spanish Exclusive Economic Zone", mrgid: 8462, gold: true },
      amp: [{ name: "Cabrera", inside: true, nm: 0, traffic: "regulated", entry: 2, speed: 3, source: "polygon" }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(text, /Dans l'aire marine protégée Cabrera \(circulation régulée\)/);
    const ev = phraseForEvent({
      type: "amp-enter",
      name: "Cabrera",
      payload: { amp: { name: "Cabrera", traffic: "regulated", inside: true }, inside: true },
    }, "fr");
    assert.match(ev, /On traverse Cabrera \(circulation régulée\)/);
  });

  it("dit « à N milles de » hors de l'aire, y compris le sac export", () => {
    const nearby = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      amp: [{ name: "Parc de Cabrera", inside: false, nm: 6, source: "polygon" }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(nearby, /À 6 milles de Parc de Cabrera/);
    const exported = narrateIci({
      zee: { name: "French Exclusive Economic Zone", mrgid: 5677, gold: true },
      amp: [{ name: "Pertuis charentais", nm: 8, source: "export" }],
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.match(exported, /À 8 milles de Pertuis charentais/);
    assert.doesNotMatch(exported, /Dans l'aire marine/);
  });
});

describe("iciBriefing — reason codes, no exception text", () => {
  it("translates unavailable and no_data and hides HTTPStatusError", () => {
    const text = narrateIci({
      zee: { name: "Haute mer", mrgid: null, gold: false },
      nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
      aton: { nearby: [], reason: "HTTPStatusError" },
      emodnet: { reason: "unavailable" },
      satellites: {
        kind: "observation",
        scene: null,
        reason: "no_data",
        derived: { coastline: { value: null, reason: "not_generated" } },
      },
      sources: { zee: "marineregions", bi: "ok" },
    }, "fr");
    assert.doesNotMatch(text, /HTTPStatusError/);
    assert.doesNotMatch(text, /_unavailable/);
    assert.match(text, /indisponible/);
    assert.match(text, /pas de donnée/);
  });
});


describe("jamais « haute mer » près d'un port ni hors de l'eau", () => {
  const SAINT_MAUR = { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358 };
  const LA_ROCHELLE = { name: "La Rochelle", lat: 46.1541, lon: -1.167 };
  const MARKS = [SAINT_MAUR, LA_ROCHELLE];
  const HIGH_SEAS_EN = "The boat is on the high seas: no exclusive economic zone, no entry formalities to plan.";
  const HIGH_SEAS_FR = "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir.";

  it("j0 prod : à Saint-Maur le serveur dit « Ashore (France) » ET « high seas » → la phrase haute mer part", () => {
    // Réponse réelle de GET /ici/moment?lat=46.808&lon=1.636 (prod, 18/10/2026).
    const here = { zee: { name: "Ashore (France)", mrgid: null }, sentences: [HIGH_SEAS_EN] };
    assert.deepEqual(hereWithoutFalseHighSeas(here).sentences, []);
  });

  it("au port de La Rochelle (≤ 12 nm d'une escale) : pas de haute mer, même si la ZEE répond « aucune »", () => {
    const near = nearestStopNm(46.15, -1.2, MARKS);
    assert.ok(near < TERRITORIAL_SEA_NM);
    const ruledOut = highSeasRuledOut({ vehicle: "main", nearStopNm: near });
    assert.equal(ruledOut, true);
    const here = { zee: { name: "Haute mer", mrgid: null }, sentences: [HIGH_SEAS_FR, "Vent 12 kn."] };
    assert.deepEqual(hereWithoutFalseHighSeas(here, { ruledOut }).sentences, ["Vent 12 kn."]);
    const dossier = { zee: { name: "Haute mer", mrgid: null }, sources: { zee: "marineregions" }, highSeasRuledOut: ruledOut };
    assert.equal(highSeasClaimAllowed(dossier), false);
    assert.doesNotMatch(narrateIci(dossier, "fr"), /haute mer/i);
    assert.doesNotMatch(narrateIci(dossier, "en"), /high seas/i);
  });

  it("sur la route Saint-Maur → La Rochelle (à terre, 64 nm), la ZEE « High seas » du serveur ne passe pas", () => {
    // GET /ici/moment?lat=46.465&lon=0.168 (prod) répond zee « High seas ».
    const ruledOut = highSeasRuledOut({ vehicle: "land", nearStopNm: nearestStopNm(46.465, 0.168, MARKS) });
    assert.equal(ruledOut, true);
    const here = { zee: { name: "High seas", mrgid: null }, sentences: [HIGH_SEAS_EN] };
    assert.deepEqual(hereWithoutFalseHighSeas(here, { ruledOut }).sentences, []);
    assert.equal(highSeasRuledOut({ vehicle: "quay" }), true);
    assert.equal(highSeasRuledOut({ vehicle: "plane" }), true);
  });

  it("en vraie haute mer, loin des escales, la phrase reste", () => {
    const far = nearestStopNm(-15.5, -158, MARKS);
    const ruledOut = highSeasRuledOut({ vehicle: "main", nearStopNm: far });
    assert.equal(ruledOut, false);
    const here = { zee: { name: "High seas", mrgid: null }, sentences: [HIGH_SEAS_EN] };
    assert.deepEqual(hereWithoutFalseHighSeas(here, { ruledOut }).sentences, [HIGH_SEAS_EN]);
    const dossier = { zee: { name: "Haute mer", mrgid: null }, sources: { zee: "marineregions" } };
    assert.equal(highSeasClaimAllowed(dossier), true);
  });

  it("branchements : Ici filtre les phrases serveur, le dossier porte la position", () => {
    const read = (rel) => readFileSync(join(here, rel), "utf8");
    assert.match(read("../components/IciMaintenant.jsx"), /hereWithoutFalseHighSeas\(frame\.here, \{ ruledOut: highSeasRuledOut \}\)/);
    assert.match(read("../hooks/useIciDossier.js"), /highSeasRuledOut \? \{ \.\.\.merged, highSeasRuledOut: true \}/);
    const app = read("../App.jsx");
    assert.match(app, /highSeasRuledOut: highSeasRuled,/);
    assert.match(app, /momentHighSeasRuledOut=\{momentHighSeasRuled\}/);
    assert.match(read("../components/Sidebar.jsx"), /highSeasRuledOut=\{momentHighSeasRuledOut\}/);
  });

  it("Tracer J0, curseur à 0 : départ de Saint-Maur, transfert routier, jamais haute mer", () => {
    // Cast Tracer : interpolateCast laisse vehicle « main » sur la jambe
    // terrestre. Le drapeau Suivre n'est pas sur le dossier. drawTip annule
    // le véhicule du moment. ZEE « High seas » / « Haute mer », ou le nom
    // anglais « Ashore » sans le booléen ashore.
    const at = { lat: SAINT_MAUR.lat, lon: SAINT_MAUR.lon };
    const nearby = { marinas: [], capitaineries: [], wpi: [] };
    const sources = { zee: "marineregions" };
    const marks = [{
      kind: "leg",
      from: "Saint-Maur (Berry, Indre)",
      to: "La Rochelle",
      vehicle: "main",
    }];
    const cases = [
      ["en", { name: "High seas", mrgid: null }, /high seas/i, /Departure: Saint-Maur \(Indre\), road transfer to La Rochelle/],
      ["fr", { name: "Haute mer", mrgid: null }, /haute mer/i, /Départ : Saint-Maur \(Indre\), transfert routier vers La Rochelle/],
      ["en", { name: "Ashore (France)", mrgid: null }, /high seas/i, /Departure: Saint-Maur \(Indre\), road transfer to La Rochelle/],
      ["fr", { name: "Ashore (France)", mrgid: null }, /haute mer/i, /Départ : Saint-Maur \(Indre\), transfert routier vers La Rochelle/],
    ];
    for (const [lang, zee, forbidden, expected] of cases) {
      const text = narrateIci({ at, zee, sources, nearby, marks }, lang);
      assert.doesNotMatch(text, forbidden);
      assert.match(text, expected);
    }
    // Véhicule du tracé annulé, escales pas encore là : la phrase serveur
    // « high seas » ne reste pas sur ce départ terrestre.
    const ruledOut = highSeasRuledOut({
      vehicle: null,
      nearStopNm: null,
      fromStop: "Saint-Maur (Berry, Indre)",
      toStop: "La Rochelle",
    });
    assert.equal(ruledOut, true);
    const frame = { zee: { name: "High seas", mrgid: null }, sentences: [HIGH_SEAS_EN, HIGH_SEAS_FR] };
    assert.deepEqual(hereWithoutFalseHighSeas(frame, { ruledOut }).sentences, []);
    const app = readFileSync(join(here, "../App.jsx"), "utf8");
    assert.match(app, /fromStop: jambe\?\.fromStop/);
    assert.match(app, /toStop: jambe\?\.toStop/);
  });

  it("jambe en mer, ZEE anglaise « Ashore (France) » sans le booléen ashore : pas de haute mer", () => {
    const dossier = {
      at: { lat: 46.0, lon: -4.5 },
      zee: { name: "Ashore (France)", mrgid: null },
      sources: { zee: "marineregions" },
      nearby: { marinas: [], capitaineries: [], wpi: [] },
      marks: [{ kind: "leg", from: "La Rochelle", to: "Horta (Açores)", vehicle: "main" }],
    };
    assert.equal(highSeasClaimAllowed(dossier), false);
    assert.doesNotMatch(narrateIci(dossier, "en"), /high seas/i);
    assert.doesNotMatch(narrateIci(dossier, "fr"), /haute mer/i);
  });
});

describe("fiche Ici — position rejouée", () => {
  const NOUMEA = { name: "Nouméa (Nouvelle-Calédonie)", lat: -22.2758, lon: 166.4419 };
  const TROMELIN = { name: "Tromelin (TAAF)", lat: -15.892, lon: 54.524 };
  const NC = {
    name: "New Caledonia Exclusive Economic Zone",
    mrgid: 8312,
    territory: "nouvelle_caledonie",
  };
  const HIGH = { name: "Haute mer", mrgid: null };
  const read = (rel) => readFileSync(join(here, rel), "utf8");

  it("Nouméa (−22.27, 166.44) : ZEE Nouvelle-Calédonie, pas Adelaide, pas haute mer", () => {
    const frame = replayHereFrame({
      lat: -22.27,
      lon: 166.44,
      marks: [NOUMEA, TROMELIN],
      zee: NC,
      logLeg: { from: "Port Vila", to: "Nouméa (Nouvelle-Calédonie)" },
      lang: "fr",
    });
    assert.equal(frame.stop?.name, NOUMEA.name);
    assert.equal(frame.highSeas, false);
    assert.match(frame.statusText, /Nouvelle-Calédonie/);
    assert.doesNotMatch(frame.statusText, /Adelaide/i);
    assert.doesNotMatch(frame.statusText, /haute mer/i);
    assert.equal(frame.leg.from, "Port Vila");
    assert.equal(frame.leg.to, "Nouméa (Nouvelle-Calédonie)");
    const en = replayHereFrame({
      lat: -22.27, lon: 166.44, marks: [NOUMEA], zee: NC, lang: "en",
    });
    assert.match(en.statusText, /New Caledonia/);
    assert.doesNotMatch(en.statusText, /Adelaide|high seas/i);
  });

  it("position TAAF hors escale : pas de fiche d'escale", () => {
    const far = replayHereFrame({
      lat: -14.5,
      lon: 54.524,
      marks: [TROMELIN],
      zee: { name: "French Southern and Antarctic Lands Exclusive Economic Zone", mrgid: 48946, territory: "taaf" },
      logLeg: { from: "Europa (TAAF)", to: "Tromelin (TAAF)" },
      lang: "en",
    });
    assert.ok(nearestStopNm(-14.5, 54.524, [TROMELIN]) > TERRITORIAL_SEA_NM);
    assert.equal(nearestStop(-14.5, 54.524, [TROMELIN]), null);
    assert.equal(far.stop, null);
    assert.equal(far.highSeas, false);
    assert.doesNotMatch(far.statusText, /high seas/i);
    assert.equal(far.leg.to, "Tromelin (TAAF)");
    const offshore = replayHereFrame({
      lat: -14.5,
      lon: 54.524,
      marks: [TROMELIN],
      zee: HIGH,
      lang: "en",
    });
    assert.equal(offshore.stop, null);
    assert.equal(offshore.highSeas, true);
    assert.match(offshore.statusText, /high seas/i);
  });

  it("à moins de 12 nm d'une escale, jamais « high seas », même si la ZEE dit haute mer", () => {
    const at = replayHereFrame({
      lat: TROMELIN.lat,
      lon: TROMELIN.lon,
      marks: [TROMELIN],
      zee: HIGH,
      logLeg: { from: "Europa (TAAF)", to: "Tromelin (TAAF)" },
      lang: "fr",
    });
    assert.equal(at.stop?.name, TROMELIN.name);
    assert.equal(at.highSeas, false);
    assert.doesNotMatch(at.statusText, /haute mer/i);
    assert.equal(at.leg.from, "Europa (TAAF)");
  });

  it("Revoir à J0, à Saint-Maur : départ et transfert routier, jamais haute mer", () => {
    const SAINT_MAUR = { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358 };
    const LA_ROCHELLE = { name: "La Rochelle", lat: 46.1541, lon: -1.167 };
    const logLeg = { from: "Saint-Maur (Berry, Indre)", to: "La Rochelle" };
    for (const [lang, zee, forbidden, expected] of [
      ["fr", HIGH, /haute mer/i, /Départ : Saint-Maur \(Indre\), transfert routier vers La Rochelle/],
      ["en", { name: "High seas", mrgid: null }, /high seas/i, /Departure: Saint-Maur \(Indre\), road transfer to La Rochelle/],
      ["en", { name: "Ashore (France)", mrgid: null }, /high seas/i, /Departure: Saint-Maur \(Indre\), road transfer to La Rochelle/],
    ]) {
      const frame = replayHereFrame({
        lat: SAINT_MAUR.lat, lon: SAINT_MAUR.lon, marks: [SAINT_MAUR, LA_ROCHELLE], zee, logLeg, lang,
      });
      assert.equal(frame.stop?.name, SAINT_MAUR.name);
      assert.equal(frame.highSeas, false);
      assert.doesNotMatch(frame.statusText, forbidden);
      assert.match(frame.statusText, expected);
    }
    // Sur la route, loin des deux escales : toujours pas de haute mer.
    const road = replayHereFrame({
      lat: 46.465, lon: 0.168, marks: [SAINT_MAUR, LA_ROCHELLE],
      zee: { name: "High seas", mrgid: null }, logLeg, lang: "en",
    });
    assert.equal(road.stop, null);
    assert.equal(road.highSeas, false);
    assert.doesNotMatch(road.statusText, /high seas/i);
  });

  it("une ZEE d'un autre pas (Adelaide) ne s'affiche pas à Nouméa", () => {
    const frame = replayHereFrame({
      lat: -22.27,
      lon: 166.44,
      marks: [NOUMEA],
      zee: {
        name: "Adelaide Exclusive Economic Zone",
        mrgid: 8323,
        bucket: filmZeeBucket(-35.0, 138.6),
      },
      logLeg: { from: "Port Vila", to: "Nouméa (Nouvelle-Calédonie)" },
      lang: "en",
    });
    assert.equal(frame.stop?.name, NOUMEA.name);
    assert.equal(frame.highSeas, false);
    assert.equal(frame.zee, null);
    assert.doesNotMatch(frame.statusText, /Adelaide|high seas/i);
    assert.equal(frame.leg.to, "Nouméa (Nouvelle-Calédonie)");
    const fresh = replayHereFrame({
      lat: -22.27,
      lon: 166.44,
      marks: [NOUMEA],
      zee: { ...NC, bucket: filmZeeBucket(-22.27, 166.44) },
      logLeg: { from: "Port Vila", to: "Nouméa (Nouvelle-Calédonie)" },
      lang: "en",
    });
    assert.match(fresh.statusText, /New Caledonia/);
    assert.doesNotMatch(fresh.statusText, /Adelaide|high seas/i);
  });

  it("haute mer d'un pas précédent ne reste pas à Nouméa", () => {
    const frame = replayHereFrame({
      lat: -22.27,
      lon: 166.44,
      marks: [NOUMEA],
      zee: { name: "Haute mer", mrgid: null, bucket: filmZeeBucket(0, -30) },
      logLeg: { from: "Port Vila", to: "Nouméa (Nouvelle-Calédonie)" },
      lang: "en",
    });
    assert.equal(frame.stop?.name, NOUMEA.name);
    assert.equal(frame.highSeas, false);
    assert.doesNotMatch(frame.statusText, /high seas|haute mer/i);
  });

  it("le Log Marigot → Cayenne ne garde pas la fiche de Port-de-Paix", () => {
    const portDePaix = { name: "Port-de-Paix (Haïti)", lat: 19.94, lon: -72.83 };
    const frame = replayHereFrame({
      lat: portDePaix.lat,
      lon: portDePaix.lon,
      marks: [portDePaix, { name: "Marigot (Saint-Martin)", lat: 18.07, lon: -63.08 }],
      zee: { name: "Haitian Exclusive Economic Zone", mrgid: 8408, bucket: filmZeeBucket(19.94, -72.83) },
      logLeg: { from: "Marigot (Saint-Martin)", to: "Cayenne (Guyane)" },
      lang: "en",
    });
    assert.equal(frame.stop, null);
    assert.equal(frame.highSeas, false);
    assert.doesNotMatch(frame.statusText, /high seas|Port-de-Paix|Port de Paix/i);
    assert.equal(frame.leg.from, "Marigot (Saint-Martin)");
    assert.equal(frame.leg.to, "Cayenne (Guyane)");
    const onStep = replayHereFrame({
      lat: 18.07,
      lon: -63.08,
      marks: [portDePaix, { name: "Marigot (Saint-Martin)", lat: 18.07, lon: -63.08 }],
      zee: { name: "Haute mer", mrgid: null },
      logLeg: { from: "Marigot (Saint-Martin)", to: "Cayenne (Guyane)" },
      lang: "en",
    });
    assert.equal(onStep.stop?.name, "Marigot (Saint-Martin)");
    assert.equal(onStep.highSeas, false);
    assert.doesNotMatch(onStep.statusText, /high seas/i);
  });

  it("en-tête et statut viennent de la même position ; l'étape est celle du Log", () => {
    const frame = replayHereFrame({
      lat: -22.27,
      lon: 166.44,
      marks: [NOUMEA, TROMELIN],
      zee: { name: "Haute mer", mrgid: null },
      logLeg: { from: "Port Vila", to: "Nouméa (Nouvelle-Calédonie)" },
      lang: "en",
    });
    assert.equal(frame.leg.from, "Port Vila");
    assert.equal(frame.leg.to, "Nouméa (Nouvelle-Calédonie)");
    assert.equal(frame.stop?.name, NOUMEA.name);
    assert.equal(frame.highSeas, false);
    assert.doesNotMatch(frame.statusText, /high seas|TAAF|Tromelin/i);
    const offshore = replayHereFrame({
      lat: -14.5,
      lon: 54.524,
      marks: [TROMELIN],
      zee: { name: "Haute mer", mrgid: null },
      logLeg: { from: "Europa (TAAF)", to: "Tromelin (TAAF)" },
      lang: "en",
    });
    assert.equal(offshore.stop, null);
    assert.equal(offshore.highSeas, true);
    assert.match(offshore.statusText, /high seas/i);
    const app = read("../App.jsx");
    assert.match(app, /replayHereFrame\(/);
    assert.match(app, /useFilmZee\(/);
    assert.match(app, /replay\.active && hudLeg\?\.fromStop/);
    assert.match(app, /replay\.live\.sailNm/);
    assert.match(app, /cast: onFilm \? null : cast/);
    assert.match(app, /replayFrame=\{replayFrame\}/);
    assert.match(read("../components/IciMaintenant.jsx"), /data-testid="ici-replay-status"/);
    assert.match(read("../components/IciMaintenant.jsx"), /data-testid="ici-replay-here"/);
    assert.match(read("../components/IciMaintenant.jsx"), /replayFrame\.stop && !replayFrame\.highSeas/);
    assert.match(read("../components/IciMaintenant.jsx"), /data-testid="ici-replay-header"/);
    assert.match(read("../components/SimulationFilmBar.jsx"), /data-testid="film-leg"/);
  });
});
