import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  LANE_FREE,
  LANE_NOW,
  FREE_STALE_NM,
  STALE_CARD_NM,
  TTL,
  advanceMoments,
  cardFromEvent,
  cardFromJournalEntry,
  cardSpeech,
  newsExpired,
  eventTruth,
  strikeParts,
  truthForCard,
  classifyMoment,
  dismissNow,
  emptyMoments,
  entityForEvent,
  escaleCard,
  infoItemsFromBag,
  isFreeStale,
  isStaleCard,
  nextFree,
  cardsFromOfficialMoments,
  pageOfficialCards,
  selectDisplayedMoments,
} from "./momentCard.js";
import { NM_TO_KM } from "../utils/berryLegs.js";

const gale = {
  id: "wind-gale:1", stableKey: "wind-gale:a", type: "wind-gale", severity: "alert", judge: "now",
  judgeReason: "safety", whenNm: 0, filmCum: 100, payload: { tws: 36, kind: "forecast" },
};
const poeAhead = {
  id: "poe-ahead:1", stableKey: "poe-ahead:lr", type: "poe-ahead", severity: "info", judge: "now",
  judgeReason: "safety", whenNm: 12, filmCum: 112,
  payload: { poe: { name: "La Rochelle - La Pallice", nm: 12, lat: 46.16, lon: -1.22, url: "https://www.douane.gouv.fr/x" } },
};
const windShiftLater = {
  id: "wind-shift:1", stableKey: "wind-shift:b", type: "wind-shift", severity: "info", judge: "later",
  judgeReason: "later", whenNm: 0, filmCum: 140, payload: { tws: 18, twd: 240, dTws: 9, kind: "forecast" },
};
const ampEnter = {
  id: "amp-enter:1", stableKey: "amp-enter:pc", type: "amp-enter", severity: "watch", judge: "now",
  judgeReason: "safety", whenNm: 0, filmCum: 100, payload: { amp: { name: "Pertuis Charentais", nm: 3.6, visitable: true, lat: 46.1, lon: -1.3 } },
};
const digest = {
  id: "group:zee-ahead:1", type: "group", severity: "watch", judge: "now", judgeReason: "digest",
  whenNm: 20, filmCum: 120, payload: { members: ["zee-ahead", "poe-ahead"] },
  digest: { fr: "Depuis cette jambe : zee-ahead + poe-ahead.", en: "Along this leg: zee-ahead + poe-ahead." },
};

const bag = {
  at: { lat: 46.15, lon: -1.17 },
  nearby: {
    marinas: [{ name: "Port des Minimes", nm: 0.4, lat: 46.14, lon: -1.17, website: "https://port-la-rochelle.fr" }],
    capitaineries: [], wpi: [{ name: "La Pallice", nm: 2.2, lat: 46.16, lon: -1.22 }], anchorages: [],
  },
  amp: [{ name: "Pertuis Charentais - Filets", nm: 3.6, lat: 46.1, lon: -1.3, visit_url: "https://www.paysdelaloire.fr/x" }],
  science: { nearby: [{ name: "Cadastre napoléonien de La Rochelle 1811", nm: 0.8, lat: 46.15, lon: -1.15, source: "sextant", url: "https://sextant.ifremer.fr/x" }] },
  projects: [{ name: "Echo-Mer", nm: 0.7, lat: 46.15, lon: -1.16, url: "https://fondationdelamer.org" }],
  aton: { nearby: [{ name: "buoy_lateral", nm: 4.6, lat: 46.1, lon: -1.2, source: "osm-overpass" }, { name: "light_minor", nm: 6, lat: 46.0, lon: -1.2 }] },
  satellites: { scene: { id: "S2A_MSIL2A_20260914T110651_N0512_R137_T30TXR_20260914T175111", product: "sentinel-2-l2a", datetime: "2026-09-14T11:06:51Z" } },
  emodnet: { cables: { nearby: true } },
  climatology: { month: 9, source: "atlas", period: "1980-2020", point: { wind_atlas: { most_likely: { speed_knots: 8.8, dir_deg: 45 } } } },
};
/** Same bag without the two NOW kinds (balisage, climatologie). */
const bagFreeOnly = { ...bag, aton: { nearby: [] }, climatology: null };

describe("classifyMoment — deux voies (arbitrage du 19 sept.)", () => {
  it("sécurité / décision → NOW ; information → FREE ; caché → rien", () => {
    assert.equal(classifyMoment(gale), LANE_NOW);
    assert.equal(classifyMoment(poeAhead), LANE_NOW);
    assert.equal(classifyMoment({ ...gale, judge: "hide" }), null);
    assert.equal(classifyMoment(digest, { filmCum: 200 }), LANE_FREE);
    assert.equal(classifyMoment({ ...gale, type: "science-hit", judge: "now" }, { filmCum: 200 }), LANE_FREE);
  });

  it("AMP et câbles sont de l’information ; balisage et climatologie des décisions", () => {
    assert.equal(classifyMoment(ampEnter, { filmCum: 100 }), LANE_FREE);
    assert.equal(classifyMoment({ ...ampEnter, type: "amp-ahead" }, { filmCum: 100 }), LANE_FREE);
    assert.equal(classifyMoment({ ...gale, type: "cable-alert" }, { filmCum: 100 }), LANE_FREE);
    const items = infoItemsFromBag(bag, "fr");
    const lanes = Object.fromEntries(items.map((c) => [c.kind, c.lane]));
    assert.equal(lanes.aton, LANE_NOW);
    assert.equal(lanes.climatology, LANE_NOW);
    assert.equal(lanes.amp, LANE_FREE);
    assert.equal(lanes.cable, LANE_FREE);
    assert.equal(lanes.science, LANE_FREE);
    assert.equal(lanes.satellite, LANE_FREE);
    assert.equal(items.filter((c) => c.kind === "aton").length, 1, "un seul balisage (le plus proche) par sac");
  });

  it("« later » attend la tête de lecture en Simulation, jamais en Suivre", () => {
    assert.equal(classifyMoment(windShiftLater, { filmCum: 100 }), null);
    assert.equal(classifyMoment(windShiftLater, { filmCum: 140 }), LANE_FREE);
    assert.equal(classifyMoment(windShiftLater, { filmCum: 0, mode: "suivre" }), LANE_FREE);
    assert.equal(classifyMoment({ ...windShiftLater, judge: "now", promoted: true }, { filmCum: 0 }), LANE_FREE);
  });
});

describe("cartes", () => {
  it("CardFromJournalEntry rend climo et sci (titre non vide, icône via journal)", () => {
    const climo = cardFromJournalEntry({
      id: "climo:rose:1",
      kind: "climo",
      event: "rose",
      t: "2026-06-02T12:00:00Z",
      lat: 22.0,
      lon: -40.0,
      title: { fr: "Changement de régime", en: "Regime change" },
      facts: { fromDeg: 45, toDeg: 165, deltaDeg: 120 },
    }, "fr");
    assert.equal(climo.kind, "climo");
    assert.ok(climo.title && climo.title.length > 0);
    assert.match(climo.title, /Changement de régime/);
    assert.match(climo.text, /120/);
    assert.equal(climo.entity.lat, 22);
    const sci = cardFromJournalEntry({
      id: "sci:pirata",
      kind: "sci",
      event: "nearby",
      t: "2026-06-10T06:00:00Z",
      lat: 14.5,
      lon: -50.0,
      name: "PIRATA",
      facts: { nm: 6, name: "PIRATA" },
      entity: { kind: "science", name: "PIRATA", lat: 14.6, lon: -50.1, url: "https://www.pmel.noaa.gov/pirata/", source: "argo" },
    }, "en");
    assert.equal(sci.kind, "sci");
    assert.ok(sci.title);
    assert.match(sci.title, /Station passed/);
    assert.match(sci.text, /PIRATA/);
    assert.equal(sci.entity.kind, "science");
    assert.equal(sci.entity.url, "https://www.pmel.noaa.gov/pirata/");
    assert.equal(cardFromJournalEntry({ kind: "grib", t: "2026-05-15T12:00:00Z" }), null);
    const zeeEn = cardFromJournalEntry({
      id: "zee:es",
      kind: "zee",
      t: "2026-05-16T10:00:00Z",
      title: "Zone économique exclusive espagnole",
    }, "en");
    assert.match(zeeEn.title, /Spanish EEZ/);
    assert.doesNotMatch(zeeEn.title, /Zone économique|espagnole/);
    const ampEn = cardFromJournalEntry({
      id: "amp:taaone",
      kind: "amp",
      t: "2026-05-16T10:00:00Z",
      title: "Aire marine protégée",
      name: "Taaone",
    }, "en");
    assert.match(ampEn.title, /Marine protected area/);
    assert.doesNotMatch(ampEn.title, /Aire marine|\bAMP\b/);
  });

  it("Carte FREE news datée, lien, expire à J+2 ; phrase science sourcée", () => {
    const entry = {
      id: "news:noumea:2026-09-20",
      kind: "news",
      t: "2026-09-20T12:00:00Z",
      expires: "2026-09-23T00:00:00Z",
      name: "Nouméa",
      text: "Travaux annoncés à la marina de Motu Uta",
      url: "https://www.portautonome.nc/avis",
      source: "nemotron-lightning",
    };
    const card = cardFromJournalEntry(entry, "fr", Date.parse("2026-09-20T15:00:00Z"));
    assert.equal(card.lane, LANE_FREE);
    assert.equal(card.kind, "news");
    assert.match(card.title, /Nouméa/);
    assert.match(card.title, /veille du/);
    assert.match(card.text, /Travaux/);
    assert.equal(card.entity.url, "https://www.portautonome.nc/avis");
    assert.equal(cardFromJournalEntry(entry, "fr", Date.parse("2026-09-23T00:00:00Z")), null);
    assert.equal(newsExpired({ ...entry, expires: "2026-09-22T00:00:00Z" }, Date.parse("2026-09-22T00:00:00Z")), true);

    const withNews = {
      ...bagFreeOnly,
      news: [entry],
      science: {
        nearby: [{
          name: "IRD Nouméa", nm: 2, lat: 46.15, lon: -1.16, source: "ird",
          url: "https://www.ird.fr/noumea",
          enrich: { text: "L'IRD observe le climat du Pacifique Sud.", url: "https://www.ird.fr/noumea" },
        }],
      },
    };
    // Heure fixe : l'actualité expire le 23 sept. 2026 — jugée à l'horloge murale, ce test est devenu
    // rouge ce jour-là sur main et sur toutes les PR (24 sept.).
    const items = infoItemsFromBag(withNews, "fr", Date.parse("2026-09-20T15:00:00Z"));
    const news = items.find((c) => c.kind === "news");
    assert.ok(news);
    assert.equal(infoItemsFromBag(withNews, "fr", Date.parse("2026-09-23T00:00:00Z")).find((c) => c.kind === "news"), undefined);
    assert.equal(news.lane, LANE_FREE);
    assert.match(news.title, /Nouméa · veille du/);
    assert.equal(news.entity.url, entry.url);
    const sci = items.find((c) => c.kind === "science");
    assert.match(sci.text, /IRD observe le climat/);
    assert.equal(isFreeStale(news, { lat: 46.15, lon: -1.17 }), false);
  });

  it("cardFromEvent : texte de phraseForEvent, entité du payload, liens", () => {
    const card = cardFromEvent(poeAhead, "fr");
    assert.equal(card.lane, LANE_NOW);
    assert.match(card.text, /Port d’entrée officiel devant : La Rochelle - La Pallice/);
    assert.equal(card.entity.kind, "poe");
    assert.equal(card.entity.lat, 46.16);
    assert.equal(card.entity.url, "https://www.douane.gouv.fr/x");
    assert.equal(entityForEvent(gale), null);
    assert.equal(cardSpeech(card), card.text);
  });

  it("truth : champ porté, affirmations unsupported barrées jamais retirées", () => {
    const ev = {
      ...poeAhead,
      payload: {
        ...poeAhead.payload,
        poe: { ...poeAhead.payload.poe, truth: { status: "verified", checkedAt: "2026-09-20T12:00:00Z", unsupported: ["Visa 90 jours"] } },
      },
    };
    const card = cardFromEvent(ev, "fr");
    assert.equal(card.truth.status, "verified");
    assert.deepEqual(card.truth.unsupported, ["Visa 90 jours"]);
    assert.equal(eventTruth(ev).status, "verified");
    const fromBag = truthForCard({ entity: { url: "https://www.douane.gouv.fr/x", name: "La Rochelle - La Pallice" } }, {
      poe: [{ name: "La Rochelle - La Pallice", url: "https://www.douane.gouv.fr/x", truth: card.truth }],
    });
    assert.equal(fromBag.status, "verified");
    const text = "Port d'entrée Fort-de-France (Gold). Visa 90 jours.";
    const parts = strikeParts(text, ["Visa 90 jours"]);
    const struck = parts.filter((p) => p.strike).map((p) => p.text).join("");
    const kept = parts.map((p) => p.text).join("");
    assert.match(struck, /Visa 90 jours/);
    assert.equal(kept, text);
    const extra = strikeParts("Port d'entrée Fort-de-France (Gold).", ["Visa 90 jours"]);
    assert.ok(extra.some((p) => p.strike && p.text === "Visa 90 jours" && p.extra));
    assert.ok(extra.some((p) => !p.strike && p.text.includes("Fort-de-France")));
  });

  it("infoItemsFromBag : lieux, AMP, câble, image satellite, climatologie — clés stables", () => {
    const items = infoItemsFromBag(bag, "fr");
    const kinds = items.map((c) => c.kind);
    assert.deepEqual(kinds, ["marina", "wpi", "science", "project", "amp", "aton", "satellite", "cable", "climatology"]);
    const marina = items[0];
    assert.equal(marina.title, "Marina");
    assert.equal(marina.text, "Port des Minimes à 0,4 nm.");
    assert.equal(marina.entity.url, "https://port-la-rochelle.fr");
    assert.equal(items[4].entity.url, "https://www.paysdelaloire.fr/x");
    assert.equal(items[5].text, "bouée latérale à 4,6 nm.");
    assert.match(items[6].text, /Dernière image satellite \(CDSE\) : Sentinel-2 \(S2A, tuile T30TXR\)/);
    assert.match(items[7].text, /câble sous-marin/);
    assert.match(items[8].text, /Climatologie de septembre/);
    assert.equal(infoItemsFromBag(bag, "en")[0].title, "Marina");
    assert.deepEqual(infoItemsFromBag(bag).map((c) => c.key), items.map((c) => c.key));
    assert.deepEqual(infoItemsFromBag(null), []);
  });

  it("escaleCard : arrivée, jours à quai, départ cap sur", () => {
    const c = escaleCard({ fromStop: "Ajaccio (Corse)", toStop: "Fort-de-France (Martinique)", holdDays: 3, legNm: 5153, etaLabel: "23 juin", lat: 41.9, lon: 8.7 }, "fr");
    assert.equal(c.lane, LANE_NOW);
    assert.equal(c.text.replace(/[\u202f\u00a0]/g, " "), "Escale Ajaccio (Corse) — 3 jours à quai. Départ : cap sur Fort-de-France (Martinique) (5 153 nm), arrivée prévue le 23 juin.");
    assert.equal(c.entity.lat, 41.9);
    assert.equal(escaleCard(null), null);
    assert.match(escaleCard({ fromStop: "Ajaccio", toStop: "FdF", holdDays: 3 }, "en").text, /^Stopover Ajaccio — 3 days in port\. Departure: heading for FdF\.$/);
  });

  it("escaleCard à Saint-Maur : km et heures, pas de nm", () => {
    const km = Math.round(122 * NM_TO_KM);
    const c = escaleCard({
      fromStop: "Saint-Maur (Berry, Indre)",
      toStop: "La Rochelle",
      holdDays: 0,
      legNm: 122,
      roadHours: 4,
      kind: "land",
    }, "fr");
    const text = c.text.replace(/[\u202f\u00a0]/g, " ");
    assert.equal(text, `Escale Saint-Maur (Indre). Départ : cap sur La Rochelle, ${km} km, ≈ 4 h.`);
    assert.doesNotMatch(text, /par la route|de route|by road|on the road/);
    assert.doesNotMatch(text, /\bnm\b/);
    const en = escaleCard({
      fromStop: "Saint-Maur (Berry)",
      toStop: "La Rochelle",
      legNm: 122,
      roadHours: 4,
      kind: "land",
    }, "en");
    const enText = en.text.replace(/[\u202f\u00a0]/g, " ");
    assert.equal(enText, `Stopover Saint-Maur (Indre). Departure: heading for La Rochelle, ${km} km, ≈ 4 h.`);
    assert.doesNotMatch(enText, /by road|on the road|\bnm\b/);
    const short = escaleCard({ fromStop: "Saint-Maur", toStop: "La Rochelle", legNm: 122, roadHours: 4 }, "fr");
    assert.match(short.text.replace(/[\u202f\u00a0]/g, " "), new RegExp(`${km} km, ≈ 4 h`));
    assert.doesNotMatch(short.text, /\bnm\b|par la route/);
  });

  it("isStaleCard : en Simulation seulement, au-delà de STALE_CARD_NM derrière la tête", () => {
    const card = { filmCum: 100 };
    assert.equal(isStaleCard(card, { filmCum: 100 + STALE_CARD_NM + 1 }), true);
    assert.equal(isStaleCard(card, { filmCum: 100 + STALE_CARD_NM - 1 }), false);
    assert.equal(isStaleCard(card, { filmCum: 5000, mode: "suivre" }), false);
    assert.equal(isStaleCard({ filmCum: null }, { filmCum: 5000 }), false);
  });
});

describe("advanceMoments — file, expiration, moment libre", () => {
  it("une carte NOW à la fois ; l’alerte passe devant ; FREE attend", () => {
    let s = advanceMoments(emptyMoments(), { events: [poeAhead, gale], bag: bagFreeOnly, filmCum: 100, nowMs: 1000, playing: true, legId: "A" });
    assert.equal(s.now.type, "wind-gale", "l’alerte est posée d’abord");
    assert.equal(s.nowQueue.length, 1);
    assert.equal(s.free, null, "rien en FREE tant qu’une carte NOW est posée");
    assert.ok(s.freeQueue.length >= 7, "le sac remplit la file d’information");

    // Same inputs → same object (no render).
    const again = advanceMoments(s, { events: [poeAhead, gale], bag: bagFreeOnly, filmCum: 100, nowMs: 2000, playing: true, legId: "A" });
    assert.equal(again, s);

    // Playing: a queued decision replaces the shown card after TTL.nowReplaceMs.
    s = advanceMoments(s, { events: [poeAhead, gale], bag: bagFreeOnly, filmCum: 100, nowMs: 1000 + TTL.nowReplaceMs, playing: true, legId: "A" });
    assert.equal(s.now.type, "poe-ahead");
    assert.equal(s.nowQueue.length, 0);

    // Then the last card expires and the free block breathes.
    s = advanceMoments(s, { events: [poeAhead, gale], bag: bagFreeOnly, filmCum: 100, nowMs: 1000 + TTL.nowReplaceMs + TTL.nowPlayingMs, playing: true, legId: "A" });
    assert.equal(s.now, null);
    assert.equal(s.free.kind, "marina");
    const firstFree = s.free;
    s = advanceMoments(s, { events: [], bag: bagFreeOnly, filmCum: 100, nowMs: firstFree.shownAt + TTL.freeMs, playing: true, legId: "A" });
    assert.equal(s.free.kind, "wpi", "rotation après TTL.freeMs");
  });

  it("le sac pousse balisage et climatologie en NOW, une fois chacun", () => {
    let s = advanceMoments(emptyMoments(), { events: [], bag, filmCum: 100, nowMs: 0, playing: false, legId: "A" });
    assert.equal(s.now.kind, "aton");
    assert.deepEqual(s.nowQueue.map((c) => c.kind), ["climatology"]);
    s = dismissNow(s, 1);
    assert.equal(s.now.kind, "climatology");
    s = advanceMoments(s, { events: [], bag, filmCum: 100, nowMs: 2, playing: false, legId: "A" });
    assert.equal(s.nowQueue.length, 0, "pas de doublon au sac suivant");
  });

  it("en pause, une carte NOW ne s’efface pas seule ; fermer la fait passer", () => {
    let s = advanceMoments(emptyMoments(), { events: [gale, poeAhead], filmCum: 100, nowMs: 0, playing: false, legId: "A" });
    s = advanceMoments(s, { events: [gale, poeAhead], filmCum: 100, nowMs: 10 * 60_000, playing: false, legId: "A" });
    assert.equal(s.now.type, "wind-gale");
    s = dismissNow(s, 1);
    assert.equal(s.now.type, "poe-ahead");
    assert.ok(s.dismissed.has("ev:wind-gale:a"));
    s = dismissNow(s, 2);
    assert.equal(s.now, null);
    s = advanceMoments(s, { events: [gale, poeAhead], filmCum: 100, nowMs: 3, playing: false, legId: "A" });
    assert.equal(s.now, null);
  });

  it("Simulation : une carte laissée loin derrière la tête de lecture n’est plus montrée", () => {
    // Queued while the boat was at 100 nm; the film jumped to Corsica.
    let s = advanceMoments(emptyMoments(), { events: [gale, poeAhead], filmCum: 100, nowMs: 0, playing: true, legId: "A" });
    assert.equal(s.now.type, "wind-gale");
    s = advanceMoments(s, { events: [gale, poeAhead], filmCum: 100 + STALE_CARD_NM + 500, nowMs: 1000, playing: true, legId: "A" });
    assert.equal(s.now, null, "la carte affichée est périmée");
    assert.equal(s.nowQueue.length, 0, "la file aussi");
    // An event first seen far behind is never a card.
    const late = advanceMoments(emptyMoments(), { events: [gale], filmCum: 2000, nowMs: 0, playing: true, legId: "A" });
    assert.equal(late.now, null);
    // Suivre never drops on distance.
    const suivre = advanceMoments(emptyMoments(), { events: [gale], filmCum: 20000, nowMs: 0, mode: "suivre", legId: "A" });
    assert.equal(suivre.now.type, "wind-gale");
  });

  it("changement de jambe : les files se vident, le vu reste vu, une carte d’escale s’ouvre", () => {
    let s = advanceMoments(emptyMoments(), { events: [gale, poeAhead], bag: bagFreeOnly, filmCum: 100, nowMs: 0, playing: false, legId: "A" });
    assert.equal(s.nowQueue.length, 1);
    s = advanceMoments(s, {
      events: [], bag: bagFreeOnly, filmCum: 1942, nowMs: 1, playing: false, legId: "B",
      leg: { fromStop: "Ajaccio (Corse)", toStop: "Fort-de-France (Martinique)", holdDays: 3, legNm: 5153, etaLabel: "23 juin" },
    });
    assert.equal(s.freeQueue.length, 0);
    assert.ok(s.seen.has("bag:marina:Port des Minimes:46.14:-1.17"));
    // The gale shown at 100 nm is 1 842 nm behind: dropped; the escale card takes its place.
    assert.equal(s.now.kind, "escale");
    assert.match(s.now.text, /^Escale Ajaccio \(Corse\) — 3 jours à quai\. Départ : cap sur Fort-de-France/);
    const firstLand = advanceMoments(emptyMoments(), {
      events: [], filmCum: 0, nowMs: 0, legId: "A",
      leg: { fromStop: "Saint-Maur", toStop: "La Rochelle", legNm: 122, kind: "land" },
    });
    assert.equal(firstLand.now.kind, "escale");
    assert.match(firstLand.now.text.replace(/[\u202f\u00a0]/g, " "), /\d+ km/);
    assert.doesNotMatch(firstLand.now.text, /\bnm\b|par la route|by road/);
    const firstSea = advanceMoments(emptyMoments(), {
      events: [], filmCum: 0, nowMs: 0, legId: "A",
      leg: { fromStop: "La Rochelle", toStop: "Ajaccio", legNm: 1820 },
    });
    assert.equal(firstSea.now, null);
  });

  it("Suivre : NOW expire après 90 s, une fiche « later » se montre sans attendre le film", () => {
    let s = advanceMoments(emptyMoments(), { events: [gale, windShiftLater], filmCum: 0, nowMs: 0, mode: "suivre", legId: "A" });
    assert.equal(s.now.type, "wind-gale");
    s = advanceMoments(s, { events: [gale, windShiftLater], filmCum: 0, nowMs: TTL.nowSuivreMs, mode: "suivre", legId: "A" });
    assert.equal(s.now, null);
    assert.equal(s.free.type, "wind-shift");
  });

  it("file vide : le bloc boucle sur les fiches du sac (marquées loop), jamais sur les événements", () => {
    const small = { at: bag.at, nearby: { marinas: bag.nearby.marinas, wpi: bag.nearby.wpi } };
    let s = advanceMoments(emptyMoments(), { events: [windShiftLater], bag: small, filmCum: 200, nowMs: 0, mode: "suivre", legId: "A" });
    const order = [s.free.kind];
    for (let i = 1; i <= 6; i++) {
      s = advanceMoments(s, { events: [windShiftLater], bag: small, filmCum: 200, nowMs: i * TTL.freeSuivreMs, mode: "suivre", legId: "A" });
      order.push(s.free?.kind ?? null);
    }
    assert.deepEqual(order, ["wind-shift", "marina", "wpi", "marina", "wpi", "marina", "wpi"]);
    assert.equal(s.free.loop, true, "un tour de boucle est marqué (Stop auto ne s’y arrête pas)");
    assert.equal(s.seen.size, 3);
  });

  it("le récit arrive après la carte : le texte affiché se met à jour", () => {
    let s = advanceMoments(emptyMoments(), { events: [gale], filmCum: 100, nowMs: 0, playing: false, legId: "A" });
    assert.match(s.now.text, /Coup de vent : 36 kn/);
    const withStory = { ...gale, story: { status: "ready", text: "Le vent monte à 36 nœuds : on réduit la toile." } };
    s = advanceMoments(s, { events: [withStory], filmCum: 100, nowMs: 1, playing: false, legId: "A", written: true });
    assert.equal(s.now.text, "Le vent monte à 36 nœuds : on réduit la toile.");
    assert.equal(s.now.storyStatus, "ready");
    assert.equal(s.now.storySource, null);
    const withModel = { ...withStory, story: { ...withStory.story, source: "nemotron-super" } };
    s = advanceMoments(s, { events: [withModel], filmCum: 100, nowMs: 2, playing: false, legId: "A", written: true });
    assert.equal(s.now.storySource, "nemotron-super");
    const local = { ...withStory, story: { ...withStory.story, source: "nemotron-super", engine: "nemotron-super+local" } };
    s = advanceMoments(s, { events: [local], filmCum: 100, nowMs: 3, playing: false, legId: "A", written: true });
    assert.equal(s.now.storySource, null);
  });

  it("pur : deux appels sur le même état précédent donnent le même résultat (StrictMode)", () => {
    const prev = emptyMoments();
    const input = { events: [gale], bag, filmCum: 100, nowMs: 0, playing: false, legId: "A" };
    const a = advanceMoments(prev, input);
    const b = advanceMoments(prev, input);
    assert.equal(prev.seen.size, 0, "l’état précédent n’est jamais muté");
    assert.equal(a.now.type, "wind-gale");
    assert.equal(b.now.type, "wind-gale");
    assert.equal(a.freeQueue.length, b.freeQueue.length);
    assert.equal(a.seen.size, b.seen.size);
  });

  it("nextFree avance à la main et reboucle sur le sac", () => {
    let s = advanceMoments(emptyMoments(), { events: [], bag: bagFreeOnly, filmCum: 0, nowMs: 0, playing: false, legId: "A" });
    assert.equal(s.free.kind, "marina");
    s = nextFree(s, 1);
    assert.equal(s.free.kind, "wpi");
    const total = 1 + s.freeQueue.length;
    for (let i = 0; i < total; i++) s = nextFree(s, 2 + i);
    assert.equal(s.free.kind, "marina", "après un tour complet, on revient au début");
    let e = advanceMoments(emptyMoments(), { events: [windShiftLater], filmCum: 200, nowMs: 0, playing: false, legId: "A" });
    assert.equal(e.free.type, "wind-shift");
    e = nextFree(e, 1);
    assert.equal(e.free, null);
    assert.equal(nextFree(e, 2), e);
  });

  it("Carte à 90 nm exclue de la boucle FREE, à 30 nm gardée", () => {
    assert.equal(FREE_STALE_NM, 60);
    const boat = { lat: 18.1, lon: -16.9 };
    const bag = {
      at: boat,
      nearby: {
        marinas: [],
        capitaineries: [],
        wpi: [
          { name: "Nouadhibou", nm: 30, lat: 18.6, lon: -16.9 },
          { name: "Port Bourgenay", nm: 90, lat: 46.48, lon: -1.78 },
        ],
        anchorages: [],
      },
    };
    const items = infoItemsFromBag(bag, "fr");
    assert.ok(items.some((c) => c.entity?.rawName === "Nouadhibou"), "30 nm : gardée");
    assert.ok(!items.some((c) => /Bourgenay/i.test(c.entity?.rawName || c.text || "")), "90 nm : exclue");

    const farCard = {
      key: "bag:wpi:far",
      origin: "bag",
      lane: LANE_FREE,
      kind: "wpi",
      text: "Port Bourgenay à 90 nm.",
      entity: { name: "Port Bourgenay", rawName: "Port Bourgenay", lat: 46.48, lon: -1.78, nm: 90 },
    };
    const nearCard = {
      key: "bag:wpi:near",
      origin: "bag",
      lane: LANE_FREE,
      kind: "wpi",
      text: "Nouadhibou à 30 nm.",
      entity: { name: "Nouadhibou", rawName: "Nouadhibou", lat: 18.6, lon: -16.9, nm: 30 },
    };
    let s = {
      ...emptyMoments(),
      legId: "A",
      seen: new Set([farCard.key, nearCard.key]),
      freeLoop: [farCard, nearCard],
    };
    s = advanceMoments(s, { events: [], bag, filmCum: 0, nowMs: 0, playing: false, legId: "A" });
    const around = [s.free, ...s.freeQueue, ...s.freeLoop].filter(Boolean);
    assert.ok(around.some((c) => /Nouadhibou/i.test(c.entity?.rawName || c.text || "")), "30 nm reste dans la boucle");
    assert.ok(!around.some((c) => /Bourgenay/i.test(c.entity?.rawName || c.text || "")), "90 nm sort de la boucle");
  });
});

describe("Carte NOW piraterie", () => {
  const aden = {
    name: "Horn of Africa / Gulf Aden",
    level: "HIGH",
    source: "IMB/UKMTO",
  };

  it("infoItemsFromBag : carte présente dans la zone, absente hors zone", () => {
    const inZone = infoItemsFromBag({ ...bagFreeOnly, piracy: aden }, "fr");
    const card = inZone.find((c) => c.kind === "piracy");
    assert.ok(card);
    assert.equal(card.lane, LANE_NOW);
    assert.equal(card.severity, "alert");
    assert.equal(card.title, null);
    assert.equal(card.text, "Piraterie — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO");
    assert.equal(inZone.filter((c) => c.kind === "piracy").length, 1);

    const en = infoItemsFromBag({ ...bagFreeOnly, piracy: aden }, "en").find((c) => c.kind === "piracy");
    assert.equal(en.text, "Piracy — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO");

    const medium = infoItemsFromBag({
      ...bagFreeOnly,
      piracy: { name: "Strait of Malacca", level: "MEDIUM", source: "ReCAAP" },
    }, "fr").find((c) => c.kind === "piracy");
    assert.equal(medium.severity, "watch");
    assert.match(medium.text, /Strait of Malacca · MEDIUM · ReCAAP/);

    assert.equal(infoItemsFromBag(bag, "fr").some((c) => c.kind === "piracy"), false);
    assert.equal(infoItemsFromBag({ ...bag, piracy: null }, "fr").some((c) => c.kind === "piracy"), false);
  });

  it("advanceMoments : alerte HIGH devant, disparaît hors zone, revient à la rentrée", () => {
    let s = advanceMoments(emptyMoments(), {
      events: [], bag, filmCum: 0, nowMs: 0, playing: false, legId: "A",
    });
    assert.notEqual(s.now?.kind, "piracy");

    s = advanceMoments(s, {
      events: [], bag: { ...bag, piracy: aden }, filmCum: 0, nowMs: 1, playing: false, legId: "A",
    });
    assert.equal(s.now.kind, "piracy");
    assert.equal(s.now.severity, "alert");
    assert.match(s.now.text, /Horn of Africa \/ Gulf Aden · HIGH · IMB\/UKMTO/);

    s = advanceMoments(s, {
      events: [], bag, filmCum: 0, nowMs: 2, playing: false, legId: "A",
    });
    assert.notEqual(s.now?.kind, "piracy");
    assert.equal([s.now, ...s.nowQueue].filter((c) => c?.kind === "piracy").length, 0);

    s = advanceMoments(s, {
      events: [], bag: { ...bag, piracy: aden }, filmCum: 0, nowMs: 3, playing: false, legId: "A",
    });
    assert.equal(s.now.kind, "piracy");
  });
});

describe("cardsFromOfficialMoments", () => {
  it("shows a card when official moments exist, and next / dismiss move it", () => {
    const built = cardsFromOfficialMoments([
      {
        t: "2026-05-17T12:00:00Z",
        signature: "early",
        pos: { lat: 43.3, lon: -8.4 },
        alerts: [{ title: "Ancienne alerte", fact: "passée" }],
      },
      {
        t: "2026-10-18T06:00:00Z",
        signature: "now",
        pos: { lat: -22.2, lon: 166.4 },
        alerts: [{ id: "a", title: "Carte maintenant", fact: "au bateau", severity: "alert" }],
        around: [
          { kind: "marina", title: "Marina de Nouméa", fact: "à portée", url: "https://example.test/marina", lat: -22.3, lon: 166.4 },
          { kind: "poe", title: "Port d'entrée", fact: "formel", url: "https://example.test/poe", lat: -22.2, lon: 166.5 },
        ],
      },
    ], { until: "2026-10-18T12:00:00Z" });
    assert.equal(built.now.title, "Carte maintenant");
    assert.equal(built.now.text, "au bateau");
    assert.equal(built.freeQueue.length, 2);
    const first = pageOfficialCards(built);
    const second = pageOfficialCards(built, { freeIndex: 1 });
    assert.equal(first.free.title, "Marina de Nouméa");
    assert.equal(second.free.title, "Port d'entrée");
    assert.equal(first.now.title, "Carte maintenant");
    assert.equal(pageOfficialCards(built, { hideNow: true }).now, null);
    assert.equal(first.free.entity.url, "https://example.test/marina");
    assert.equal(first.free.entity.lat, -22.3);
  });

  it("keeps the official now card in front of the stopover card", () => {
    const built = cardsFromOfficialMoments([
      {
        t: "2026-10-18T06:00:00Z",
        signature: "now",
        alerts: [{ title: "Carte maintenant", fact: "au bateau" }],
        around: [{ kind: "marina", title: "Marina de Nouméa", fact: "à portée" }],
      },
    ], { until: "2026-10-18T12:00:00Z" });
    const escale = escaleCard({ fromStop: "Saint-Maur (Berry, Indre)", toStop: "La Rochelle", kind: "land", legNm: 120 });
    const shown = selectDisplayedMoments({
      eventNow: escale,
      officialNow: built.now,
      officialHasNow: true,
      officialFree: built.freeQueue[0],
    });
    assert.equal(shown.now.title, "Carte maintenant");
    assert.equal(shown.free.title, "Marina de Nouméa");
    const dismissed = selectDisplayedMoments({
      eventNow: escale,
      officialNow: null,
      officialHasNow: true,
      officialFree: built.freeQueue[0],
    });
    assert.equal(dismissed.now, null);
    const galeCard = cardFromEvent(gale, "fr");
    const safety = selectDisplayedMoments({
      eventNow: galeCard,
      officialNow: built.now,
      officialHasNow: true,
    });
    assert.equal(safety.now.kind, "wind-gale");
    const onlyEscale = selectDisplayedMoments({ eventNow: escale });
    assert.equal(onlyEscale.now.kind, "escale");
  });
});
