import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fr from "./fr.js";
import en from "./en.js";

describe("i18n parity", () => {
  it("chaque clé fr a sa clé en, et inversement", () => {
    const frKeys = Object.keys(fr);
    const enKeys = Object.keys(en);
    const missingEn = frKeys.filter((k) => !(k in en));
    const missingFr = enKeys.filter((k) => !(k in fr));
    assert.deepEqual(missingEn, [], `clés fr sans en : ${missingEn.join(", ")}`);
    assert.deepEqual(missingFr, [], `clés en sans fr : ${missingFr.join(", ")}`);
    assert.equal(fr._lang, "fr");
    assert.equal(en._lang, "en");
  });

  it("Plus de clés d'aide (logbook, revue, chiffres)", () => {
    for (const k of ["logbookChatHint", "planReviewSummary", "skipperExpertHint"]) {
      assert.equal(fr[k], undefined, `fr.${k} ne doit plus exister`);
      assert.equal(en[k], undefined, `en.${k} ne doit plus exister`);
    }
  });

  it("Info-bulle de vitesse d'époque", () => {
    assert.equal(fr.traveledEraSpeed, "{knots} kn");
    assert.equal(en.traveledEraSpeed, "{knots} kn");
  });

  it("Escale précédente et info-bulles de régime", () => {
    assert.equal(fr.previousEscale, "Escale précédente");
    assert.equal(en.previousEscale, "Previous stop");
    assert.match(fr.regimeTooltipHindcast, /vraiment rencontré/);
    assert.match(fr.regimeTooltipForecast, /10 jours/);
    assert.match(fr.regimeTooltipClimatology, /moyenne du mois/);
    assert.match(en.regimeTooltipHindcast, /actually met/);
    assert.match(en.regimeTooltipForecast, /10 days/);
    assert.match(en.regimeTooltipClimatology, /monthly average/);
  });

  it("Unités terrestres km / h de route", () => {
    assert.equal(fr.unitKm, "km");
    assert.equal(en.unitKm, "km");
    assert.equal(fr.unitRoadHours, "h de route");
    assert.equal(en.unitRoadHours, "h on the road");
    assert.equal(fr.byRoad, "par la route");
    assert.equal(en.byRoad, "by road");
  });

  it("Fourchette d'arrivée sans p10 ni membres à l'écran", () => {
    assert.equal(fr.etaRange, "arrivée entre le {p10} et le {p90}");
    assert.equal(en.etaRange, "arrival between {p10} and {p90}");
    assert.equal(fr.etaRangeTitle, "p10–p90, {n} membres");
    assert.equal(en.etaRangeTitle, "p10–p90, {n} members");
  });

  it("Ligne de raison quand la fourchette manque", () => {
    assert.equal(fr.etaUnavailable, "fourchette indisponible — {reason}, nouvel essai le {date}");
    assert.equal(en.etaUnavailable, "arrival window unavailable — {reason}, retry on {date}");
    assert.equal(fr.etaUnavailableShort, "fourchette indisponible — {reason}");
    assert.equal(en.etaUnavailableShort, "arrival window unavailable — {reason}");
    assert.equal(fr.etaReasonQuota, "quota Open-Meteo atteint");
    assert.equal(en.etaReasonQuota, "Open-Meteo quota reached");
    assert.equal(fr.etaReasonPreparing, "en préparation");
    assert.equal(en.etaReasonPreparing, "preparing");
  });

  it("Bandeau climato : source du repli global", () => {
    assert.equal(fr.climatologySourceGlobal, "maille 4°");
    assert.equal(en.climatologySourceGlobal, "4° mesh");
  });

  it("les libellés plein écran film existent dans les deux langues", () => {
    assert.match(fr.filmFullscreen, /Plein écran film/);
    assert.match(en.filmFullscreen, /fullscreen/i);
    assert.ok(fr.filmFullscreenExit);
    assert.ok(en.filmFullscreenExit);
  });
});
