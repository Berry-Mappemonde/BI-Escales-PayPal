import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import { readFileSync } from "node:fs";
import { SCIENCE_KIND_KEYS, scienceKindLabel } from "./scienceLabels.js";

const tOf = (dict) => (key) => dict[key] || key;

describe("Science card: no raw code", () => {
  it("argo_float and dataset read as words in FR and EN", () => {
    assert.equal(scienceKindLabel("argo_float", tOf(fr)), "Flotteur Argo");
    assert.equal(scienceKindLabel("argo_float", tOf(en)), "Argo float");
    assert.equal(scienceKindLabel("dataset", tOf(fr)), "Jeu de données");
    assert.equal(scienceKindLabel("dataset", tOf(en)), "Dataset");
  });

  it("every known code has a label in both languages", () => {
    for (const key of new Set(Object.values(SCIENCE_KIND_KEYS))) {
      assert.ok(fr[key], `fr ${key}`);
      assert.ok(en[key], `en ${key}`);
    }
  });

  it("an unknown code is spelled out, never shown with underscores", () => {
    assert.equal(scienceKindLabel("sea_level_gauge", tOf(en)), "Sea level gauge");
    assert.equal(scienceKindLabel("", tOf(en)), "");
  });

  it("the card's fallback title is translated, not « Science » in French", () => {
    const src = readFileSync(new URL("../components/LayerFichePopup.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(src, /\|\|\s*"Science"/);
    assert.match(src, /t\("layerFicheScience"\)/);
    assert.match(src, /scienceKindLabel\(props\.kind, t\)/);
    assert.notEqual(fr.layerFicheScience, en.layerFicheScience);
  });
});
