import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  consecutiveHomonyms,
  lookup,
  originName,
  sheetLabel,
  spokenZeeName,
  watersLabel,
} from "./toponyms.js";

describe("toponyms RC32", () => {
  it("donne les exonymes FR/EN, pas une traduction automatique", () => {
    assert.equal(watersLabel("Spanish Exclusive Economic Zone", "fr"), "les eaux espagnoles");
    assert.equal(watersLabel("Spanish Exclusive Economic Zone", "en"), "Spanish waters");
    assert.match(watersLabel("Sint-Eustatius Exclusive Economic Zone", "fr"), /Saint-Eustache/);
    assert.match(watersLabel("Sint-Eustatius Exclusive Economic Zone", "en"), /Sint Eustatius/);
  });

  it("distingue Saint-Martin et Sint Maarten", () => {
    const frMf = watersLabel("Saint-Martin Exclusive Economic Zone", "fr");
    const frSx = watersLabel("Sint-Maarten Exclusive Economic Zone", "fr");
    assert.match(frMf, /Saint-Martin \(partie française\)/);
    assert.match(frSx, /Sint Maarten \(partie néerlandaise\)/);
    assert.deepEqual(consecutiveHomonyms(`${frSx}, puis ${frMf}`), []);
    const blob = "les eaux de Saint-Martin, puis celles de Saint-Martin";
    assert.ok(consecutiveHomonyms(blob).length > 0);
  });

  it("fiche ici : ZEE française (Guadeloupe), pas le nom Marine Regions brut", () => {
    const zee = { name: "French Exclusive Economic Zone", mrgid: 33177, territory: "guadeloupe" };
    assert.equal(spokenZeeName(zee, "fr"), "Zone économique exclusive française (Guadeloupe)");
    assert.equal(sheetLabel(zee.name, "en", { mrgid: 33177, territory: "guadeloupe" }), "French EEZ (Guadeloupe)");
  });

  it("normalise la casse des ports en majuscules, garde le nom d'origine mixte", () => {
    assert.equal(originName("LA ROCHELLE"), "La Rochelle");
    assert.equal(originName("MUXIA"), "Muxía");
    assert.equal(originName("Porto Torres"), "Porto Torres");
  });

  it("donne un exonyme français aux eaux de l'océan Indien (plus de « les eaux Sri Lankan »)", () => {
    assert.equal(watersLabel("Sri Lankan Exclusive Economic Zone", "fr"), "les eaux sri-lankaises");
    assert.equal(watersLabel("Maldivian Exclusive Economic Zone", "fr"), "les eaux maldiviennes");
    assert.equal(watersLabel("Maldivian Exclusive Economic Zone", "en"), "Maldivian waters");
  });
  it("ne prend pas les îles Gambier pour la Gambie (alias borné)", () => {
    assert.notEqual(lookup("Gambier Islands")?.id, "gm");
    assert.equal(lookup("Gambia")?.id, "gm");
    assert.equal(watersLabel("Gambian Exclusive Economic Zone", "fr"), "les eaux gambiennes");
  });
});
