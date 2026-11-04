import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BOAT_FIELDS,
  DEFAULT_BOAT,
  DEFAULT_PROFILE,
  EXPERT_FIELDS,
  EXPERT_IDS,
  resolveOrders,
} from "../engine/skipperOrders.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "SkipperOrdersPanel.jsx"), "utf8");

/**
 * Même contrat que `resetNumberToProfile` exporté du panneau (fichier JSX,
 * non importable par node --test) : valeur du profil, forced faux.
 */
function resetNumberToProfile(id, profile = DEFAULT_PROFILE) {
  const orders = resolveOrders({ profile });
  const value = id in BOAT_FIELDS ? orders.boat[id] : orders.values[id];
  return { value, forced: false };
}

describe("SkipperOrdersPanel — remise d’un chiffre", () => {
  it("exporte resetNumberToProfile et câble onReset sur loa, draft et chaque chiffre", () => {
    assert.match(src, /export function resetNumberToProfile/);
    assert.match(src, /onChange\?\.\(id, null\)/);
    assert.match(src, /id="loaM"[\s\S]*?onReset=\{\(fieldId\) => onBoat\?\.\(fieldId, null\)\}/);
    assert.match(src, /id="draftM"[\s\S]*?onReset=\{\(fieldId\) => onBoat\?\.\(fieldId, null\)\}/);
    assert.equal((src.match(/onReset=\{\(fieldId\) => onExpert\?\.\(fieldId, null\)\}/g) || []).length, 2);
    assert.doesNotMatch(src, /skipperExpertHint/);
    assert.doesNotMatch(src, /label=\{t\("skipperBoat"\)\}/);
    assert.match(src, /const \[draft, setDraft\]/);
    assert.match(src, /onBlur=/);
  });

  it("après remise, la valeur est celle du profil et forced est faux", () => {
    const profile = "cruise";
    const id = "galePct";
    const forced = resolveOrders({ profile, expert: { [id]: 40 } });
    assert.equal(forced.values[id], 40);
    assert.equal(id in forced.expert, true);

    const after = resolveOrders({ profile, expert: {} });
    const expected = resetNumberToProfile(id, profile);
    assert.equal(after.values[id], expected.value);
    assert.equal(expected.value, 15);
    assert.equal(expected.forced, false);
    assert.equal(id in after.expert, false);

    const coastalRain = resetNumberToProfile("rainMmH", "coastal");
    assert.equal(coastalRain.value, 3);
    assert.equal(coastalRain.forced, false);
    const oceanRain = resetNumberToProfile("rainMmH", "ocean");
    assert.equal(oceanRain.value, 6);
  });

  it("après remise de la longueur, la valeur polar/défaut revient et forced est faux", () => {
    const before = resolveOrders({ profile: "cruise", boat: { loaM: 20 } });
    assert.equal(before.boat.loaM, 20);
    assert.equal(before.boat.source.loa, "skipper");

    const after = resolveOrders({ profile: "cruise", boat: {} });
    const expected = resetNumberToProfile("loaM", "cruise");
    assert.equal(after.boat.loaM, expected.value);
    assert.equal(expected.value, DEFAULT_BOAT.loaM);
    assert.equal(expected.forced, false);
    assert.notEqual(after.boat.source.loa, "skipper");
  });

  it("cycle force → forced → remise au profil pour chaque champ numérique", () => {
    const profile = "cruise";
    for (const id of EXPERT_IDS) {
      const field = EXPERT_FIELDS[id];
      const base = resolveOrders({ profile }).values[id];
      const forcedVal = Number(base) === field.min ? field.max : field.min;
      const forced = resolveOrders({ profile, expert: { [id]: forcedVal } });
      assert.equal(id in forced.expert, true, `${id} forced`);
      assert.equal(forced.values[id], forced.expert[id], `${id} valeur forcée`);
      const after = resolveOrders({ profile, expert: {} });
      const expected = resetNumberToProfile(id, profile);
      assert.equal(after.values[id], expected.value, `${id} profil`);
      assert.equal(expected.forced, false);
      assert.equal(id in after.expert, false, `${id} plus forced`);
    }
    for (const id of Object.keys(BOAT_FIELDS)) {
      const field = BOAT_FIELDS[id];
      const base = resolveOrders({ profile }).boat[id];
      const forcedVal = Number(base) === field.min ? field.max : field.min;
      const forced = resolveOrders({ profile, boat: { [id]: forcedVal } });
      const srcKey = id === "loaM" ? "loa" : "draft";
      assert.equal(forced.boat.source[srcKey], "skipper", `${id} source skipper`);
      assert.equal(forced.boat[id], forcedVal, `${id} valeur forcée`);
      const after = resolveOrders({ profile, boat: {} });
      const expected = resetNumberToProfile(id, profile);
      assert.equal(after.boat[id], expected.value, `${id} polar/défaut`);
      assert.equal(expected.forced, false);
      assert.notEqual(after.boat.source[srcKey], "skipper", `${id} plus skipper`);
    }
  });
});

describe("SkipperOrdersPanel — Demander conseil", () => {
  it("le bouton Demander conseil est sur le panneau d'étape", () => {
    const sim = readFileSync(join(here, "EtapePanel.jsx"), "utf8");
    const fr = readFileSync(join(here, "..", "i18n", "fr.js"), "utf8");
    const en = readFileSync(join(here, "..", "i18n", "en.js"), "utf8");
    assert.match(sim, /recomputeButton/);
    assert.match(sim, /data-testid="ask-advice"/);
    assert.match(fr, /recomputeButton:\s*"Demander conseil"/);
    assert.match(en, /recomputeButton:\s*"Ask for advice"/);
    assert.doesNotMatch(fr, /Recalculer l.itin[eé]raire/);
    assert.doesNotMatch(en, /Recalculate the route/);
  });
});

describe("SkipperOrdersPanel — une seule occurrence profil/budget", () => {
  it("l'en-tête replié ne répète pas le profil ni le budget déjà dans le panneau", () => {
    const summary = src.match(/<summary\b[^>]*>[\s\S]*?<\/summary>/);
    assert.ok(summary, "un <summary> racine");
    const head = summary[0];
    assert.match(head, /advancedSettings/);
    assert.doesNotMatch(head, /PROFILE_KEY|COMFORT_KEY|horizonH|\{summary\}/);
    assert.doesNotMatch(src, /const summary = \[/);
    assert.equal((src.match(/skipper-profile/g) || []).length, 1, "pills profil une fois");
    assert.match(src, /orders\.budget\.hours/);
    assert.match(src, /data-testid="skipper-horizon"/);
  });
});
