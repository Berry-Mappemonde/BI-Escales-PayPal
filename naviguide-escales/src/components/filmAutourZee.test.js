// Revue visuelle du 29/10 12 h 57, défauts hors PR :
// (1) « Autour du bateau : Fineveke » figé pendant le film,
// (2) alerte ZEE Nouvelle-Calédonie à Papeete,
// (3) mot « règles » isolé dans l'interface.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import { cardsBetween, journalTimeline, FILM_CARD_MAX_NM } from "../engine/replay.js";
import { replayHereFrame } from "../engine/iciBriefing.js";
import { replayIciFrame, REPLAY_AROUND_MAX_NM } from "./iciMaintenant.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(join(here, rel), "utf8");

const PAPEETE = { lat: -17.5116, lon: -149.5685 };
const WALLIS = { lat: -13.2725, lon: -176.2036 };
// Horloge du film : Papeete le 17 oct., Mata-Utu 10 jours plus tard.
const CLOCK = {
  t0: "2026-10-17T00:00:00Z",
  vertices: [
    { ...PAPEETE, tHours: 0, sailNm: 16205 },
    { ...WALLIS, tHours: 240, sailNm: 17847 },
  ],
};

describe("film — cartes du journal à la position du bateau du film (ZEE)", () => {
  // Stock daté sur un ancien planning : l'entrée en ZEE Nouvelle-Calédonie
  // tombe le 14 oct., quand le bateau du film est encore à Papeete.
  const tl = journalTimeline({ events: [
    { id: "zee:nc", kind: "zee", event: "enter", t: "2026-10-14T08:46:17Z", name: "French Exclusive Economic Zone (New Caledonia)", mrgid: 8325, lat: -22.4847, lon: 170.0785 },
    { id: "zee:pf", kind: "zee", event: "enter", t: "2026-10-17T01:00:00Z", name: "French Exclusive Economic Zone (French Polynesia)", mrgid: 8443, lat: -17.52, lon: -149.6 },
    { id: "note:1", kind: "note", t: "2026-10-17T02:00:00Z", text: "Appareillage.", author: "Clément" },
  ] });
  const from = Date.parse("2026-10-13T00:00:00Z");
  const to = Date.parse("2026-10-17T03:00:00Z");

  it("une ZEE loin du bateau du film n'est jamais une carte ; celle du lieu reste", () => {
    const cards = cardsBetween(tl, from, to, "en", CLOCK);
    const text = cards.map((c) => `${c.title} ${c.text}`).join(" | ");
    assert.doesNotMatch(text, /New Caledonia|Nouvelle-Calédonie/);
    assert.match(text, /French Polynesia|Polynésie/);
    // Sans position (note), la carte passe.
    assert.ok(cards.some((c) => c.kind === "note"));
    assert.ok(FILM_CARD_MAX_NM >= 30 && FILM_CARD_MAX_NM <= 120);
  });

  it("sans horloge, rien ne change (compatibilité)", () => {
    assert.equal(cardsBetween(tl, from, to, "en").length, 3);
  });

  it("useReplay passe l'horloge du film à cardsBetween", () => {
    assert.match(read("../hooks/useReplay.js"), /cardsBetween\(timelineRef\.current, from, next, lang, clockRef\.current\)/);
  });
});

describe("film — « Autour du bateau » suit la position du bateau du film", () => {
  const live = {
    t: "2026-10-29T16:00",
    pos: WALLIS,
    alerts: [{ id: "poe-wf", title: "Formalités d’entrée", fact: "Aucun port d’entrée officiel n’est connu pour Zone économique exclusive française (Wallis-et-Futuna)." }],
    around: [{ kind: "marina", title: "Marina de Fineveke", fact: "Marina de Fineveke (1,6 nm)" }],
    sources: ["zee"],
  };
  const journal = [
    { t: "2026-09-11T06:51:57Z", pos: PAPEETE, signature: "a", changes: [], alerts: [], around: [] },
    { t: "2026-09-26T19:10:10Z", pos: { lat: -17.5116, lon: -149.5685 }, signature: "b", changes: [],
      alerts: [{ id: "poe-pf", title: "Formalités d’entrée", fact: "Aucun port d’entrée officiel n’est connu pour Zone économique exclusive française (Polynésie française)." }],
      around: [{ kind: "marina", title: "Marina de Vaiare", fact: "Marina de Vaiare (11 nm)" }] },
    { t: "2026-10-08T12:19:17Z", pos: WALLIS, signature: "c", changes: [], alerts: live.alerts, around: live.around },
  ];

  it("à Papeete : Vaiare et la Polynésie française, jamais Fineveke ni Wallis", () => {
    const frame = replayIciFrame(live, journal, { lat: -17.53, lon: -149.57 });
    const around = frame.around.map((a) => a.title).join(" ");
    const alerts = frame.alerts.map((a) => a.fact).join(" ");
    assert.doesNotMatch(around, /Fineveke/);
    assert.match(around, /Vaiare/);
    assert.doesNotMatch(alerts, /Wallis/);
    assert.match(alerts, /Polynésie française/);
  });

  it("en pleine mer, loin de tout moment du journal : rien plutôt que le direct", () => {
    const frame = replayIciFrame(live, journal, { lat: -15.5, lon: -163 });
    assert.deepEqual(frame.around, []);
    assert.deepEqual(frame.alerts, []);
    assert.ok(REPLAY_AROUND_MAX_NM > 0 && REPLAY_AROUND_MAX_NM <= 60);
  });

  it("le cadre « Ici » du film porte sa position", () => {
    const f = replayHereFrame({ lat: -17.53, lon: -149.57, marks: [], lang: "fr" });
    assert.equal(f.at.lat, -17.53);
    assert.equal(f.at.lon, -149.57);
  });

  it("IciMaintenant lit le cadre du film ; App coupe la carte libre du direct pendant le film", () => {
    assert.match(read("IciMaintenant.jsx"), /replayIciFrame\(moment, journalEntries, replayFrame\.at\)/);
    assert.match(read("../App.jsx"), /momentFree=\{sceneReady && !replay\.active \? moments\.free : null\}/);
  });
});

describe("interface — pas de mot « règles » isolé", () => {
  it("l'étiquette de source « règles » dit ce qu'elle est", () => {
    assert.equal(fr.storySourceRules, "Formulé par les données brutes");
    assert.equal(en.storySourceRules, "Written from raw data");
    for (const dict of [fr, en]) {
      const label = dict.storySourceRules;
      assert.ok(label.trim().split(/\s+/).length >= 3, `étiquette trop courte : « ${label} »`);
      assert.doesNotMatch(label, /sans IA|no AI/i);
    }
  });

  it("Revue du plan : sans proposition, une phrase et pas d'étiquette seule", () => {
    const src = read("PlanReview.jsx");
    assert.match(src, /\{best \? \(\s*<LlmSourceBadge source=\{source\} testId="plan-review-source"/);
    assert.match(src, /planReviewNoChange/);
    assert.ok(fr.planReviewNoChange && en.planReviewNoChange);
  });
});
