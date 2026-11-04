import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BUBBLE_SCORE_WINDOW_MS,
  EVENT_BUBBLE_MIN_MS,
  EventBubbleGate,
  FilmEventScoreGate,
  applyBubbleClose,
  bubbleFacts,
  bubbleId,
  bubbleScore,
  bubbleTitle,
  createEventPopupOptions,
  ensureEventPopup,
  followPopupToMarker,
  filmEventCard,
  isBubbleSuppressed,
  pickFilmEvent,
  shouldShowFilmEvent,
} from "./eventBubble.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "EventBubble.jsx"), "utf8");
const logic = readFileSync(join(here, "eventBubble.js"), "utf8");
const sceneSrc = readFileSync(join(here, "..", "map", "MapSceneController.js"), "utf8");
const hook = readFileSync(join(here, "..", "hooks", "useReplay.js"), "utf8");
const cards = readFileSync(join(here, "MomentCards.jsx"), "utf8");

function fakePopup() {
  return {
    ll: null,
    content: null,
    setLatLng(v) {
      this.ll = Array.isArray(v) ? { lat: v[0], lng: v[1] } : v;
      return this;
    },
    getLatLng() { return this.ll; },
    setContent(c) { this.content = c; return this; },
    openOn() { return this; },
    remove() { return this; },
  };
}

function fakeMarker(lat, lng) {
  return {
    ll: { lat, lng },
    getLatLng() { return this.ll; },
    setLatLng(v) {
      this.ll = Array.isArray(v) ? { lat: v[0], lng: v[1] } : v;
    },
  };
}

describe("EventBubble — contrat", () => {
  it("masque un corps français en anglais et conserve le français en français", () => {
    const ev = { kind: "zee", fact: "Du 11 juin, des navires arrivent.", card: { text: "Du 11 juin, des navires arrivent." } };
    assert.equal(filmEventCard(ev, "en").text, "");
    assert.equal(bubbleFacts({ text: ev.fact }, "en"), "");
    assert.equal(filmEventCard(ev, "fr").text, ev.fact);
    assert.equal(bubbleFacts({ text: ev.fact }, "fr"), ev.fact);
    assert.equal(filmEventCard({ ...ev, fact: "Ships arrive.", card: { text: "Ships arrive." } }, "en").text, "Ships arrive.");
  });

  it("L.popup : autoPan false, pas de croix Leaflet, classe event-bubble, 280 px", () => {
    const opts = createEventPopupOptions();
    assert.equal(opts.autoPan, false);
    assert.equal(opts.closeButton, false);
    assert.equal(opts.className, "event-bubble");
    assert.equal(opts.maxWidth, 280);
    assert.equal(opts.minWidth, 280);
    assert.match(logic, /autoPan:\s*false/);
    assert.match(src, /ensureEventPopup/);
    assert.match(src, /className:\s*"event-bubble"|createEventPopupOptions/);
  });

  it("la bulle suit le marqueur (popup.getLatLng() = bateau après update)", () => {
    const popup = fakePopup();
    const marker = fakeMarker(46.15, -1.16);
    followPopupToMarker(popup, marker);
    assert.equal(popup.getLatLng().lat, marker.getLatLng().lat);
    assert.equal(popup.getLatLng().lng, marker.getLatLng().lng);
    marker.setLatLng([14.6, -61.07]);
    followPopupToMarker(popup, marker);
    assert.deepEqual(popup.getLatLng(), marker.getLatLng());
  });

  it("une seule bulle à la fois (un seul L.popup, la carte courante remplace)", () => {
    const created = [];
    const L = {
      popup(opts) {
        const p = { ...fakePopup(), opts };
        created.push(p);
        return p;
      },
    };
    const first = ensureEventPopup(null, L);
    const again = ensureEventPopup(first, L);
    assert.equal(created.length, 1);
    assert.equal(again, first);
    let t = 0;
    const gate = new EventBubbleGate({ now: () => t });
    assert.equal(bubbleId(gate.propose({ id: "a" })), "a");
    t = 4000;
    assert.equal(bubbleId(gate.propose({ id: "b" })), "b");
    assert.equal(bubbleId(gate.card), "b");
  });

  it("minimum 3 s avant de remplacer (faux timers)", () => {
    let t = 0;
    const gate = new EventBubbleGate({ now: () => t });
    assert.equal(bubbleId(gate.propose({ id: "a", title: "A" })), "a");
    t = 1000;
    assert.equal(bubbleId(gate.propose({ id: "b", title: "B" })), "a", "encore dans les 3 s");
    t = EVENT_BUBBLE_MIN_MS - 1;
    gate.tick();
    assert.equal(bubbleId(gate.card), "a");
    t = EVENT_BUBBLE_MIN_MS;
    gate.tick();
    assert.equal(bubbleId(gate.card), "b");
    const afterEsc = gate.dismiss();
    assert.equal(afterEsc, null);
    t = EVENT_BUBBLE_MIN_MS + 10;
    assert.equal(gate.propose({ id: "b", title: "B" }), null, "Échap : la même carte ne revient pas");
    assert.equal(bubbleId(gate.propose({ id: "c", title: "C" })), "c");
  });

  it("titre borné à 40 caractères ; pick film : charIdx (voix) / date (sans voix)", () => {
    assert.equal(bubbleTitle({ title: "Court" }).length <= 40, true);
    const long = "X".repeat(50);
    assert.equal(bubbleTitle({ title: long }).length, 40);
    const chapter = {
      idx: 0,
      events: [
        { id: "depart", charIdx: 0, card: { id: "depart", kind: "stop", at: "2026-05-15T06:00:00Z", title: "Départ" } },
        { id: "wx", charIdx: 80, card: { id: "wx", kind: "wx", at: "2026-05-27T12:00:00Z", title: "Coup de vent" } },
      ],
    };
    assert.equal(pickFilmEvent({ chapter, charIdx: 10, voiceLed: true })?.id, "depart");
    assert.equal(pickFilmEvent({ chapter, charIdx: 80, voiceLed: true })?.id, "wx");
    assert.equal(pickFilmEvent({
      chapter, voiceLed: false, tMs: Date.parse("2026-05-15T08:00:00Z"),
    })?.id, "depart");
    assert.equal(pickFilmEvent({
      chapter, voiceLed: false, tMs: Date.parse("2026-05-27T13:00:00Z"),
    })?.id, "wx");
  });

  it("localise le titre ZEE des bulles et cartes du film en EN sans modifier le FR", () => {
    const card = { kind: "zee", title: "Zone économique exclusive vénézuélienne" };
    assert.equal(bubbleTitle(card, undefined, "fr"), card.title);
    assert.equal(bubbleTitle(card, undefined, "en"), "Venezuelan EEZ");
    assert.equal(filmEventCard({ card }).title, card.title);
    assert.equal(filmEventCard({ card }, "en").title, "Venezuelan EEZ");
    assert.match(src, /bubbleTitle\(card, undefined, lang\)/);
  });

  it("la scène resynchronise la popup après syncMarkers ; le film ouvre la bulle", () => {
    assert.match(sceneSrc, /this\.eventBubble = attachEventBubble\(this, L\)/);
    assert.match(sceneSrc, /this\.eventBubble\?\.sync\(\)/);
    assert.match(sceneSrc, /mainBoatMarker\(/);
    assert.match(hook, /pickFilmEvent/);
    assert.match(hook, /publishEventBubble/);
    assert.match(hook, /FilmEventScoreGate/);
    assert.doesNotMatch(cards, /publishEventBubble/);
    assert.match(src, /keydown/);
    assert.match(src, /Escape/);
    assert.match(src, /data-testid="event-bubble"/);
  });

  it("La croix ferme la bulle, pas le film", () => {
    assert.match(src, /data-testid="event-bubble-close"/);
    assert.match(src, /×/);
    assert.match(src, /onClose/);
    const closed = applyBubbleClose({ id: "wx-1" });
    assert.equal(closed.card, null);
    assert.equal(closed.closedId, "wx-1");
    assert.equal(isBubbleSuppressed(closed.closedId, { id: "wx-1" }), true);
    assert.equal(isBubbleSuppressed(closed.closedId, { id: "zee-1" }), false);
  });
});

describe("eventBubble — : seuil de score et somme 20 s", () => {
  it("score ≥ 2 s'affiche, score 1 seul non", () => {
    assert.equal(shouldShowFilmEvent(3), true);
    assert.equal(shouldShowFilmEvent(2), true);
    assert.equal(shouldShowFilmEvent(1), false);
    assert.equal(shouldShowFilmEvent(1, [1]), false);
    assert.equal(shouldShowFilmEvent(1, [1, 1]), true);
    assert.equal(shouldShowFilmEvent(0, [3]), true);
  });

  it("infère le score depuis le kind quand le script n'en a pas", () => {
    assert.equal(bubbleScore({ kind: "stop" }), 3);
    assert.equal(bubbleScore({ kind: "wx" }), 3);
    assert.equal(bubbleScore({ kind: "zee" }), 2);
    assert.equal(bubbleScore({ kind: "sci" }), 2);
    assert.equal(bubbleScore({ kind: "amp" }), 1);
    assert.equal(bubbleScore({ kind: "climo" }), 1);
    assert.equal(bubbleScore({ score: 2, kind: "amp" }), 2);
  });

  it("somme des non-montrés depuis 20 s atteint 3 → bulle", () => {
    let t = 0;
    const gate = new FilmEventScoreGate({ now: () => t });
    assert.equal(gate.accept({ id: "amp-1", kind: "amp", score: 1 }), null);
    t = 5_000;
    assert.equal(gate.accept({ id: "climo-1", kind: "climo", score: 1 }), null);
    t = 12_000;
    const third = gate.accept({ id: "amp-2", kind: "amp", score: 1 });
    assert.equal(third?.id, "amp-2");
  });

  it("fenêtre de 20 s : un score 1 trop ancien ne compte plus", () => {
    let t = 0;
    const gate = new FilmEventScoreGate({ now: () => t });
    assert.equal(gate.accept({ id: "amp-old", kind: "amp", score: 1 }), null);
    t = BUBBLE_SCORE_WINDOW_MS + 1;
    assert.equal(gate.accept({ id: "amp-new", kind: "amp", score: 1 }), null);
    t += 1_000;
    assert.equal(gate.accept({ id: "climo-new", kind: "climo", score: 1 }), null);
  });

  it("score 2 remplace sans attendre la somme", () => {
    let t = 0;
    const gate = new FilmEventScoreGate({ now: () => t });
    assert.equal(gate.accept({ id: "amp-1", kind: "amp", score: 1 }), null);
    t = 2_000;
    assert.equal(gate.accept({ id: "zee-1", kind: "zee", score: 2 })?.id, "zee-1");
  });
});

describe("EN text_en priority", () => {
  it("EN prefers text_en over French text", async () => {
    const { bubbleFacts } = await import("./eventBubble.js");
    assert.match(bubbleFacts({ text: "Le bateau longe la côte des Baléares avec les alizés.", text_en: "The boat sails along the Balearic coast." }, "en"), /Balearic/);
    assert.match(bubbleFacts({ text: "Le bateau longe la côte.", text_en: "The boat sails." }, "fr"), /bateau/);
  });
});
