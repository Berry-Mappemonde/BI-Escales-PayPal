import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ESCALE_SHEET_NM, escaleSheetVisible, nearestAlongside, parkedCatamaranSample, pickAutoEscaleStop,
} from "./escaleSheetPick.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "useEscaleSheetState.js"), "utf8");

const SAINT_MAUR = { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358 };
const LA_ROCHELLE = { name: "La Rochelle", lat: 46.1541, lon: -1.167 };
const AJACCIO = { name: "Ajaccio", lat: 41.9267, lon: 8.7378 };
const FORT_DE_FRANCE = { name: "Fort-de-France (Martinique)", lat: 14.5887, lon: -61.0731 };
const MARKS = [SAINT_MAUR, LA_ROCHELLE, AJACCIO, FORT_DE_FRANCE];

const alongside = {
  isSuivre: true,
  atQuay: true,
  clockSample: { lat: FORT_DE_FRANCE.lat, lon: FORT_DE_FRANCE.lon },
  marks: MARKS,
};

describe("useEscaleSheetState — KO #309 Fort-de-France", () => {
  it("à quai à Fort-de-France, nearestAlongside rend Fort-de-France, pas Saint-Maur", () => {
    const best = nearestAlongside(alongside.clockSample, MARKS);
    assert.equal(best?.name, FORT_DE_FRANCE.name);
    assert.notEqual(best?.name, SAINT_MAUR.name);
    assert.notEqual(best?.name, LA_ROCHELLE.name);
  });

  it("repro : après un clic-liste, l'horloge restée à quai ouvre Fort-de-France (le troisième nom)", () => {
    // handleSidebarSeek (App.jsx) pose userPreview + seek ; le curseur
    // reste sur la jambe live (KO bot #309). clockSample reste à quai à
    // Fort-de-France. Sans garde userPicked, l'auto-fiche ouvre ce nom-là
    // — pas Saint-Maur / La Rochelle / Ajaccio cliqués.
    const leaked = pickAutoEscaleStop(alongside);
    assert.equal(leaked?.name, FORT_DE_FRANCE.name);
    assert.notEqual(leaked?.name, SAINT_MAUR.name);
    assert.notEqual(leaked?.name, AJACCIO.name);
  });

  it("une fiche désignée (drapeau) n'est jamais remplacée par Fort-de-France", () => {
    const kept = pickAutoEscaleStop({ ...alongside, userPicked: true });
    assert.equal(kept, null);
  });

  it("la fiche auto ne s'ouvre que pour l'escale à quai la plus proche", () => {
    assert.equal(pickAutoEscaleStop({ ...alongside, atQuay: false })?.name, undefined);
    assert.equal(pickAutoEscaleStop({ ...alongside, hold: true })?.name, undefined);
    assert.equal(pickAutoEscaleStop({ ...alongside, filmActive: true })?.name, undefined);
    const atAjaccio = pickAutoEscaleStop({
      ...alongside,
      clockSample: { lat: AJACCIO.lat, lon: AJACCIO.lon },
    });
    assert.equal(atAjaccio?.name, AJACCIO.name);
  });

  it("En Tracer, l'auto-fiche suit le tracé (Saint-Maur), jamais Papeete", () => {
    const PAPEETE = { name: "Papeete (Polynésie française)", lat: -17.537, lon: -149.566 };
    const atStart = pickAutoEscaleStop({
      isSuivre: false,
      atQuay: true,
      clockSample: { lat: SAINT_MAUR.lat, lon: SAINT_MAUR.lon },
      marks: [...MARKS, PAPEETE],
    });
    assert.equal(atStart?.name, SAINT_MAUR.name);
    assert.notEqual(atStart?.name, PAPEETE.name);
    const leakedOfficial = pickAutoEscaleStop({
      isSuivre: false,
      atQuay: true,
      clockSample: { lat: PAPEETE.lat, lon: PAPEETE.lon },
      marks: [...MARKS, PAPEETE],
    });
    assert.equal(leakedOfficial?.name, PAPEETE.name, "si on passe encore le sample officiel, Papeete sort — le cloisonnement est dans App (clockSample du tracé)");
  });

  it("Catamaran parqué à Cayenne : fiche Cayenne, pas Halifax", () => {
    const CAYENNE = { name: "Cayenne (Guyane)", lat: 4.93, lon: -52.35 };
    const HALIFAX = { name: "Halifax (Nouvelle-Écosse)", lat: 44.65, lon: -63.57 };
    const marks = [...MARKS, CAYENNE, HALIFAX];
    for (const vehicle of ["plane", "side", "quay"]) {
      const sample = {
        lat: HALIFAX.lat,
        lon: HALIFAX.lon,
        vehicle,
        parkLat: CAYENNE.lat,
        parkLon: CAYENNE.lon,
      };
      assert.equal(parkedCatamaranSample(sample)?.lat, CAYENNE.lat, vehicle);
      const stop = pickAutoEscaleStop({
        isSuivre: true,
        atQuay: vehicle === "quay",
        clockSample: sample,
        marks,
      });
      assert.equal(stop?.name, CAYENNE.name, vehicle);
      assert.notEqual(stop?.name, HALIFAX.name);
    }
  });

  it("open() pose userPickedRef ; l'effet passe par pickAutoEscaleStop", () => {
    assert.match(src, /userPickedRef\.current = true/);
    assert.match(src, /pickAutoEscaleStop\(/);
    assert.match(src, /userPicked: userPickedRef\.current/);
  });
});

describe("fiche d'escale — seulement au port ou juste autour", () => {
  const TROMELIN = { name: "Tromelin (TAAF)", lat: -15.892, lon: 54.524 };
  const PAPEETE = { name: "Papeete (Polynésie française)", lat: -17.537, lon: -149.566 };
  const atPapeete = { lat: PAPEETE.lat, lon: PAPEETE.lon };
  const offPapeete = { lat: -16.9, lon: -151.2 }; // j94 : au large, vers Mata-Utu

  it("KO parcours #21 : fiche Tromelin alors que le bateau est à Papeete → masquée", () => {
    assert.equal(escaleSheetVisible({ stop: TROMELIN, clockSample: atPapeete }), false);
    assert.equal(escaleSheetVisible({ stop: TROMELIN, clockSample: offPapeete }), false);
  });

  it("une fiche cliquée tient jusqu'à ce que l'horloge bouge, puis suit la règle de distance", () => {
    assert.equal(
      escaleSheetVisible({ stop: TROMELIN, clockSample: offPapeete, userPicked: true }),
      true,
      "juste après le clic sur le drapeau, la fiche demandée s'affiche",
    );
    // Le skipper déplace l'horloge : userPicked est relâché.
    assert.equal(escaleSheetVisible({ stop: TROMELIN, clockSample: offPapeete, userPicked: false }), false);
  });

  it("à quai et juste autour : la fiche de cette escale reste ; au-delà de N nm elle part", () => {
    assert.equal(escaleSheetVisible({ stop: PAPEETE, clockSample: atPapeete }), true);
    const justOut = { lat: PAPEETE.lat + (ESCALE_SHEET_NM - 2) / 60, lon: PAPEETE.lon };
    assert.equal(escaleSheetVisible({ stop: PAPEETE, clockSample: justOut }), true);
    const farOut = { lat: PAPEETE.lat + (ESCALE_SHEET_NM + 5) / 60, lon: PAPEETE.lon };
    assert.equal(escaleSheetVisible({ stop: PAPEETE, clockSample: farOut }), false);
    assert.ok(ESCALE_SHEET_NM <= 30, "« au port ou juste autour »");
  });

  it("le hook ne rend la fiche que si elle est visible et la referme au départ", () => {
    assert.match(src, /stop: visible \? stop : null/);
    assert.match(src, /if \(!stop \|\| visible\) return;[\s\S]*?setStop\(null\)/);
    // Déplacer l'horloge (scrub, lecture, précédent / suivant) relâche la fiche cliquée.
    assert.match(src, /if \(!clockMoveToken \|\| !userPickedRef\.current\) return;\s*userPickedRef\.current = false;/);
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.match(app, /clockMoveToken,\n/);
    assert.ok((app.match(/noteClockMove\(\);/g) || []).length >= 6, "scrub, lecture, précédent, suivant, journal, événement");
  });
});
