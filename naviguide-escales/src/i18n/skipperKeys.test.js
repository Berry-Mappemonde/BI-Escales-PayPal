import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fr from "./fr.js";
import en from "./en.js";

const KEYS = [
  "skipperProfileAria",
  "skipperProfileCoastal",
  "skipperProfileCruise",
  "skipperProfileOcean",
  "skipperBoat",
  "skipperBoatUnknown",
  "skipperLoa",
  "skipperDraft",
  "skipperBerryDefault",
  "skipperPlanningKn",
  "skipperFromPolar",
  "skipperProfileDefault",
  "skipperSuivreWindow",
  "skipperGale",
  "skipperSuggestCoastal",
  "skipperSuggestYes",
  "skipperSuggestNo",
  "skipperResetBerry",
  "skipperComfortTitle",
  "skipperComfortAria",
  "skipperComfortSoft",
  "skipperComfortNormal",
  "skipperComfortHard",
  "skipperHorizonAria",
  "skipperHorizonLeg",
  "skipperPearls",
  "skipperExpertTitle",
  "skipperExpertReset",
  "skipperExpertLocked",
  "skipperExpertGalePct",
  "skipperExpertWindResetKt",
  "skipperExpertWindResetDeg",
  "skipperExpertCurrentIgnore",
  "skipperExpertCurrentInvert",
  "skipperExpertRainMmH",
  "skipperExpertRain3h",
  "skipperExpertMarinaNm",
  "skipperExpertMarinaCooldown",
  "skipperExpertIciRadius",
  "skipperExpertAlongAmp",
  "skipperExpertAmpAhead",
];

describe("skipper i18n", () => {
  it("has every skipper label in FR and EN", () => {
    for (const k of KEYS) {
      assert.equal(typeof fr[k], "string", `fr.${k}`);
      assert.equal(typeof en[k], "string", `en.${k}`);
      assert.ok(fr[k].length > 0 && en[k].length > 0, k);
    }
  });

  it("names the characters, never raw event types", () => {
    assert.equal(fr.skipperProfileCoastal, "Côtier");
    assert.equal(fr.skipperProfileCruise, "Croisière");
    assert.equal(fr.skipperProfileOcean, "Large");
    for (const k of KEYS) {
      assert.doesNotMatch(fr[k], /wind-gale|hs-shift|depth-alert/);
      assert.doesNotMatch(en[k], /wind-gale|hs-shift|depth-alert/);
    }
  });
});
