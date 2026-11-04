import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import { localizeStoredTitle } from "./iciMaintenant.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "LayerFichePopup.jsx"), "utf8");

describe("fiche de calque : libellés traduits", () => {
  it("aucun libellé français en dur", () => {
    for (const word of ["Site", "Projet", "Voir le projet", "Téléphone", "Gestionnaire", "Visite", "Navire", "regroupés", "Port d'entrée", "Aire marine", "ZEE"]) {
      assert.ok(!src.includes(`"${word}`) && !src.includes(`>${word}`), word);
    }
    assert.doesNotMatch(src, /lang === "en"/);
  });

  it("chaque clé de la fiche existe en FR et en EN", () => {
    const keys = [...src.matchAll(/t\("(layerFiche\w+)"/g)].map((m) => m[1]);
    assert.ok(keys.length >= 12);
    for (const key of keys) {
      assert.equal(typeof fr[key], "string", `fr.${key}`);
      assert.equal(typeof en[key], "string", `en.${key}`);
    }
    assert.equal(fr.layerFicheCluster, "{count} points regroupés");
    assert.equal(en.layerFicheCluster, "{count} grouped points");
  });

  it("localise le nom de ZEE en EN et conserve le libellé FR", () => {
    const title = "Zone économique exclusive vénézuélienne";
    assert.match(src, /localizeStoredTitle\(props\.GEONAME \|\| props\.geoname \|\| props\.name \|\| "", lang\)/);
    assert.equal(localizeStoredTitle(title, "fr"), title);
    assert.equal(localizeStoredTitle(title, "en"), "Venezuelan EEZ");
  });

  it("préfixe le nom du projet en EN, sans modifier son titre en FR", () => {
    assert.match(src, /name \? \(lang\.startsWith\("en"\) \? `Project: \$\{name\}` : name\)/);
  });
});
