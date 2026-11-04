import { test } from "node:test";
import assert from "node:assert/strict";
import { localizeStoredTitle, localizeSourceTag } from "./iciMaintenant.js";
import { displayStopName } from "../utils/stopLabels.js";

test("EN titles of stored EEZ cards carry no French adjective or region", () => {
  assert.equal(localizeStoredTitle("Zone économique exclusive samoane", "en"), "Samoan EEZ");
  assert.equal(localizeStoredTitle("Zone économique exclusive (Saint-Vincent-et-les-Grenadines)", "en"), "Saint Vincent and the Grenadines EEZ");
  assert.equal(localizeStoredTitle("Zone économique exclusive française (Polynésie française)", "en"), "French Polynesia EEZ");
  assert.doesNotMatch(localizeStoredTitle("ZEE Martinique", "en"), /\bZEE\b/);
  assert.equal(localizeStoredTitle("ZEE", "en"), "EEZ");
  assert.equal(localizeStoredTitle("Zone économique exclusive samoane", "fr"), "Zone économique exclusive samoane");
});

test("EN sources line reads EEZ, FR keeps zee", () => {
  assert.equal(localizeSourceTag("zee", "en"), "EEZ");
  assert.equal(localizeSourceTag("zee", "fr"), "zee");
  assert.equal(localizeSourceTag("GEBCO", "en"), "GEBCO");
});

test("EN stop names translate the overseas region", () => {
  assert.equal(displayStopName("Papeete (Polynésie française)", "en"), "Papeete (French Polynesia)");
  assert.equal(displayStopName("Mata-Utu (Wallis-et-Futuna)", "en"), "Mata-Utu (Wallis and Futuna)");
  assert.equal(displayStopName("Papeete (Polynésie française)", "fr"), "Papeete (Polynésie française)");
  assert.equal(displayStopName("Ajaccio (Corse)", "en"), "Ajaccio (Corse)");
});
