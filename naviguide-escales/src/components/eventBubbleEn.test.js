import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { bubbleFacts, bubbleTitle, enTitleFromFacts, looksFrench } from "./eventBubble.js";
import { enDecimals } from "./iciMaintenant.js";

describe("bulles du film en anglais (revue EN 1020)", () => {
  it("un titre de zone français devient le fait anglais", () => {
    const card = { kind: "zee", title: "Zone économique exclusive espagnole", text: "On 17 May, Spanish waters." };
    assert.equal(bubbleTitle(card, 40, "en"), "Spanish EEZ");
    assert.equal(bubbleTitle(card, 40, "fr"), "Zone économique exclusive espagnole");
  });

  it("côte et vents : plus de titre français en EN", () => {
    assert.equal(bubbleTitle({ kind: "coast", title: "les Baléares — Mahón", text: "On 30 May, the Balearic Islands — Mahón." }, 40, "en"), "The Balearic Islands — Mahón");
    assert.equal(bubbleTitle({ kind: "climo", title: "alizés de nord-est", text: "On 24 June, the northeasterly trade winds set in: fourteen knots." }, 40, "en"), "The northeasterly trade winds set in");
    assert.equal(bubbleTitle({ kind: "coast", title: "l'Andalousie — Cartagena", text: "On 27 May, the boat skirts Andalusia — Cartagena." }, 40, "en"), "The boat skirts Andalusia — Cartagena");
    assert.equal(bubbleTitle({ kind: "climo", title: "alizés de nord-est", text: "" }, 40, "en"), "Seasonal winds");
    assert.equal(bubbleTitle({ kind: "zee", title: "Haute mer", text: "On 22 June, the high seas." }, 40, "en"), "The high seas");
  });

  it("un corps de données seulement en français est masqué en EN, jamais traduit", () => {
    const card = { kind: "news", title: "Des navires", text: "Du 11 Jun, Des navires d'une flotte de Cotignac passent." };
    assert.equal(bubbleFacts(card, "en"), "");
    assert.match(bubbleFacts(card, "fr"), /Cotignac/);
    assert.equal(bubbleTitle(card, 40, "en"), "Along the route");
    const overlap = { kind: "zee", title: "Overlapping claim Western Sahara: Western Sahara / Morocco", text: "Du 24 Jun, désaccord entre Western Sahara et Morocco." };
    assert.equal(bubbleFacts(overlap, "en"), "");
    assert.equal(looksFrench(bubbleTitle(overlap, 40, "en")), false);
  });

  it("noms propres gardés : escale, projet", () => {
    assert.equal(bubbleTitle({ kind: "stop", title: "Pointe-à-Pitre (Guadeloupe)", text: "Arrival at Pointe-à-Pitre (Guadeloupe) on 18 July." }, 40, "en"), "Pointe-à-Pitre (Guadeloupe)");
    const proj = { kind: "project", title: "CÔTE À CÔTE", text: "On 15 May, six miles away, project Côte À Côte." };
    assert.equal(bubbleTitle(proj, 40, "en"), "CÔTE À CÔTE");
    assert.equal(bubbleFacts(proj, "en"), proj.text);
    assert.equal(looksFrench("On 17 July, twenty-one miles away, project Restaurer les coraux préférés des poissons-demoiselles."), false);
  });

  it("enTitleFromFacts retire la date et la suite", () => {
    assert.equal(enTitleFromFacts("The next day, Portuguese waters."), "Portuguese waters");
  });

  it("décimales EN : 2,7 nm → 2.7 nm, milliers intacts, FR inchangé", () => {
    assert.equal(enDecimals("MAERL-OFB / POS3IDON (2,7 nm)", "en"), "MAERL-OFB / POS3IDON (2.7 nm)");
    assert.equal(enDecimals("1,500 nm", "en"), "1,500 nm");
    assert.equal(enDecimals("(2,7 nm)", "fr"), "(2,7 nm)");
  });
});
