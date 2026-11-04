import { describe, it } from "node:test";
import assert from "node:assert/strict";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import {
  destinationPortLabel,
  displayStopName,
  filmClockWithoutRoadNm,
  landLegDistanceClause,
  roadTransferLabel,
  withoutForeignRegion,
} from "./stopLabels.js";

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

describe("FV2 — noms d'escale", () => {
  it("retire le suffixe d'une autre escale et nomme les Açores en FR et EN", () => {
    assert.equal(displayStopName("Açores (Corse)", "fr", tFr), "Açores");
    assert.equal(displayStopName("Açores (Corse)", "en", tEn), "Azores (Portugal)");
    assert.equal(displayStopName("Açores", "fr", tFr), "Açores");
    assert.equal(displayStopName("Azores", "en", tEn), "Azores (Portugal)");
    assert.doesNotMatch(displayStopName("Açores (Corse)", "fr", tFr), /Corse|Corsica/);
    assert.doesNotMatch(displayStopName("Açores (Corse)", "en", tEn), /Corse|Corsica/);
    assert.equal(displayStopName("Ajaccio (Corse)", "fr", tFr), "Ajaccio (Corse)");
    assert.equal(displayStopName("Ajaccio (Corse)", "en", tEn), "Ajaccio (Corse)");
    assert.equal(displayStopName("Fort-de-France (Martinique)", "fr", tFr), "Fort-de-France (Martinique)");
    assert.equal(displayStopName("Europa (TAAF)", "en", tEn), "Europa (TAAF)");
    assert.equal(displayStopName("La Rochelle", "fr", tFr), "La Rochelle");
  });

  it("affiche Saint-Maur avec le département Indre, en FR et EN", () => {
    for (const lang of ["fr", "en"]) {
      const t = lang === "en" ? tEn : tFr;
      assert.equal(displayStopName("Saint-Maur (Berry)", lang, t), "Saint-Maur (Indre)");
      assert.equal(displayStopName("Saint-Maur (Berry, Indre)", lang, t), "Saint-Maur (Indre)");
      assert.equal(displayStopName("Saint-Maur", lang, t), "Saint-Maur (Indre)");
      assert.doesNotMatch(displayStopName("Saint-Maur (Berry)", lang, t), /Berry/);
    }
  });
});

describe("FV2 — transfert routier en km", () => {
  it("écrit le transfert Saint-Maur (Indre) → La Rochelle en km, FR et EN", () => {
    const enText = roadTransferLabel(122, 4, tEn, "en", "Saint-Maur (Berry)", "La Rochelle", en.byRoad, en.unitRoadHours, en.unitKm);
    const frText = roadTransferLabel(122, 4, tFr, "fr", "Saint-Maur (Berry, Indre)", "La Rochelle", fr.byRoad, fr.unitRoadHours, fr.unitKm);
    assert.equal(enText, "Road transfer Saint-Maur (Indre) → La Rochelle: 226 km, ≈ 4 h");
    assert.equal(frText, "Transfert routier Saint-Maur (Indre) → La Rochelle : 226 km, ≈ 4 h");
    assert.match(enText, /226 km, ≈ 4 h/);
    assert.match(frText, /226 km, ≈ 4 h/);
    assert.doesNotMatch(enText, /by road|on the road/);
    assert.doesNotMatch(frText, /par la route|de route/);
    assert.doesNotMatch(enText, /\bnm\b/);
    assert.doesNotMatch(frText, /\bnm\b/);
    assert.equal(roadTransferLabel(Number.NaN, 4, tEn, "en", "Saint-Maur", "La Rochelle", en.byRoad, en.unitRoadHours, en.unitKm), "");
  });
});

describe("FV2 — horloge et clause routière", () => {
  it("retire les milles de la ligne d'horloge et écrit les km, FR et EN", () => {
    assert.equal(filmClockWithoutRoadNm("277 nm · j0 · 15 mai 2026"), "j0 · 15 mai 2026");
    assert.equal(filmClockWithoutRoadNm("277 nm · d0 · 15 May 2026"), "d0 · 15 May 2026");
    assert.equal(filmClockWithoutRoadNm("9\u202f080 nm · j12 · 1er juin"), "j12 · 1er juin");
    assert.equal(filmClockWithoutRoadNm("9,080 nm · d12"), "d12");
    assert.equal(filmClockWithoutRoadNm("j0 · 15 mai 2026"), "j0 · 15 mai 2026");
    assert.equal(filmClockWithoutRoadNm(""), "");
    assert.equal(landLegDistanceClause(122, 4, "fr").replace(/[\u202f\u00a0]/g, " "), "226 km, ≈ 4 h");
    assert.equal(landLegDistanceClause(122, 4, "en").replace(/[\u202f\u00a0]/g, " "), "226 km, ≈ 4 h");
    assert.equal(landLegDistanceClause(122, 0, "en"), "226 km");
    assert.equal(landLegDistanceClause(Number.NaN, 4, "fr"), "");
    assert.doesNotMatch(landLegDistanceClause(122, 4, "en"), /\bnm\b|by road|on the road/);
    assert.doesNotMatch(landLegDistanceClause(122, 4, "fr"), /\bnm\b|par la route|de route/);
  });
});

describe("FV2 — suffixe d'une autre escale", () => {
  it("retire seulement la région qui appartient à un autre lieu", () => {
    assert.equal(withoutForeignRegion("Açores (Corse)"), "Açores");
    assert.equal(withoutForeignRegion("Azores (Corsica)"), "Azores");
    assert.equal(withoutForeignRegion("Ajaccio (Corse)"), "Ajaccio (Corse)");
    assert.equal(withoutForeignRegion("Saint-Maur (Berry, Indre)"), "Saint-Maur (Berry, Indre)");
    assert.equal(withoutForeignRegion("La Rochelle"), "La Rochelle");
  });
});

describe("FV2 — bannière climatologie", () => {
  it("ne dit plus « kind » en FR ni en EN", () => {
    assert.equal(en.climatologyOn, "CMEMS atlas · {month} · {maps}");
    assert.equal(fr.climatologyOn, "Atlas CMEMS · {month} · {maps}");
    assert.doesNotMatch(en.climatologyOn, /kind/i);
    assert.doesNotMatch(fr.climatologyOn, /kind/i);
  });
});

describe("FV2 — distance au port de destination", () => {
  it("explicite les milles restants, FR et EN", () => {
    const enNm = (9080).toLocaleString("en-US");
    const frNm = (9080).toLocaleString("fr-FR");
    assert.equal(destinationPortLabel(9080, tEn, "en"), `${enNm} nm to destination port`);
    assert.equal(destinationPortLabel(9080, tFr, "fr"), `${frNm} nm jusqu’au port de destination`);
    assert.match(destinationPortLabel(9080, tEn, "en"), /9,080 nm to destination port/);
    assert.doesNotMatch(destinationPortLabel(9080, tEn, "en"), /\bPORT\b/);
    assert.equal(destinationPortLabel(null, tEn, "en"), "—");
  });
});
