import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fr from "../i18n/fr.js";
import { MOMENT_MAX_NM, momentNearest } from "../hooks/useMomentJournal.js";
import en from "../i18n/en.js";
import {
  PORT_CARD_NEAR_NM,
  PORT_CARD_PHASE_NM,
  cardsFromOfficialMoments,
  escaleCard,
  pickOfficialMoment,
  readableCard,
  stopKey,
  portCardIsCurrent,
  selectDisplayedMoments,
} from "./momentCard.js";
import {
  aroundWithoutShown,
  dedupeFacts,
  displayIciFrame,
  sentencesNotShown,
  keptSentences,
  localizeStoredFact,
  localizeStoredLabel,
  visibleAlerts,
} from "../components/iciMaintenant.js";

const SHA = "3f9c2a7be41d08c5a6e2f1b0d9c87a65";

function row(t, lat, lon, extra = {}) {
  return { t, pos: { lat, lon }, signature: `${t}-sig`, ...extra };
}

describe("Maintenant tab: one fact once", () => {
  it("« haute mer : aucune ZEE » once, whatever list repeats it", () => {
    const items = [
      { kind: "zee", title: "Haute mer", fact: "haute mer : aucune ZEE" },
      { kind: "zee", title: "Haute mer ", fact: "Haute mer : aucune ZEE." },
      { kind: "amp", title: "Haute mer", fact: "haute mer : aucune ZEE" },
    ];
    const out = dedupeFacts(items);
    assert.equal(out.length, 2);
    assert.deepEqual(out.map((i) => i.kind), ["zee", "amp"]);
    const alerts = visibleAlerts([
      { id: "a", kind: "zee", fact: "haute mer : aucune ZEE" },
      { id: "b", kind: "zee", fact: "haute mer : aucune ZEE" },
    ], new Set());
    assert.deepEqual(alerts.map((a) => a.id), ["a"]);
  });

  it("one Bathymétrie card, not three; never the Now card again in the queue", () => {
    const bathy = { kind: "layer", layer: "bathymetry", title: "Bathymétrie – Nouvelle-Calédonie", fact: "Profondeurs GEBCO" };
    const rows = [row("2026-10-10T00:00:00Z", -22, 166, {
      alerts: [{ kind: "zee", title: "ZEE Nouvelle-Calédonie", fact: "Entrée en ZEE Nouvelle-Calédonie" }],
      around: [
        bathy,
        { ...bathy },
        { ...bathy, fact: "Profondeurs GEBCO (zoom)" },
        { kind: "zee", title: "ZEE Nouvelle-Calédonie", fact: "Entrée en ZEE Nouvelle-Calédonie" },
        { kind: "amp", title: "Parc naturel de la mer de Corail", fact: "AMP" },
        { kind: "amp", title: "Réserve Merlet", fact: "AMP" },
      ],
    })];
    const { now, freeQueue } = cardsFromOfficialMoments(rows, { until: "2026-10-11T00:00:00Z" });
    assert.equal(now.title, "ZEE Nouvelle-Calédonie");
    const titles = freeQueue.map((c) => c.title);
    assert.equal(titles.filter((t) => t.startsWith("Bathymétrie")).length, 1);
    assert.ok(!titles.includes("ZEE Nouvelle-Calédonie"));
    // Two distinct marine protected areas stay two cards.
    assert.ok(titles.includes("Parc naturel de la mer de Corail"));
    assert.ok(titles.includes("Réserve Merlet"));
  });

  it("Now is not the card already shown as Next", () => {
    const card = { key: "free:x:layer:Bathymétrie", kind: "layer", title: "Bathymétrie – Nouvelle-Calédonie", text: "Profondeurs" };
    const shown = selectDisplayedMoments({ officialNow: { ...card, key: "now:x" }, officialHasNow: true, officialFree: card });
    assert.equal(shown.now, null);
    assert.equal(shown.free, card);
    const around = aroundWithoutShown([
      { kind: "layer", title: "Bathymétrie – Nouvelle-Calédonie", fact: "Profondeurs" },
      { kind: "amp", title: "Réserve Merlet", fact: "AMP" },
    ], card);
    assert.deepEqual(around.map((i) => i.title), ["Réserve Merlet"]);
  });
});

describe("Maintenant tab: port card only near that port", () => {
  const saintMaur = escaleCard({ fromStop: "Saint-Maur", toStop: "La Rochelle", legNm: 122, roadHours: 4, lat: 48.8, lon: 2.49 }, "fr");

  it("named constants", () => {
    assert.equal(typeof PORT_CARD_NEAR_NM, "number");
    assert.equal(typeof PORT_CARD_PHASE_NM, "number");
    assert.ok(PORT_CARD_NEAR_NM > 0 && PORT_CARD_PHASE_NM > 0);
  });

  it("the Saint-Maur card does not come back at J132 in the Pacific", () => {
    const pacific = { lat: -17.5, lon: -149.6 };
    const leg = { fromStop: "Papeete", toStop: "Nouméa", doneNm: 600, leftNm: 2400 };
    assert.equal(portCardIsCurrent(saintMaur, { boat: pacific, leg }), false);
    const shown = selectDisplayedMoments({ eventNow: saintMaur, officialHasNow: false, boat: pacific, leg });
    assert.equal(shown.now, null);
  });

  it("shown when leaving that port, when arriving, or close to it", () => {
    assert.equal(portCardIsCurrent(saintMaur, { leg: { fromStop: "Saint-Maur", toStop: "La Rochelle", doneNm: 5, leftNm: 117 } }), true);
    assert.equal(portCardIsCurrent(saintMaur, { leg: { fromStop: "Le Havre", toStop: "Saint-Maur", doneNm: 300, leftNm: 10 } }), true);
    assert.equal(portCardIsCurrent(saintMaur, { boat: { lat: 48.85, lon: 2.5 } }), true);
    assert.equal(portCardIsCurrent(saintMaur, { leg: { fromStop: "Saint-Maur", doneNm: PORT_CARD_PHASE_NM + 40, leftNm: 40 } }), false);
  });

  it("the departure text itself is untouched, other cards always pass", () => {
    assert.match(saintMaur.text, /Saint-Maur/);
    assert.equal(portCardIsCurrent({ kind: "zee", title: "ZEE" }, { boat: { lat: 0, lon: 0 } }), true);
    assert.equal(portCardIsCurrent(saintMaur, {}), true);
  });
});

describe("Maintenant tab: moment closest to the boat", () => {
  const rows = [
    row("2026-10-10T00:00:00Z", -22.0, 166.4, { alerts: [{ kind: "poe", title: "Nouméa", fact: "Port d’entrée Nouméa" }] }),
    row("2026-10-10T06:00:00Z", -21.0, 165.0, { alerts: [{ kind: "amp", title: "Parc de la mer de Corail", fact: "AMP" }] }),
    row("2026-10-10T12:00:00Z", -19.0, 163.0, { alerts: [{ kind: "zee", title: "ZEE Vanuatu", fact: "Approche Vanuatu" }] }),
  ];

  it("in the date window, the nearest moment wins", () => {
    const picked = pickOfficialMoment(rows, { boat: { lat: -22.1, lon: 166.5 } });
    assert.equal(picked.t, "2026-10-10T00:00:00Z");
    const { now } = cardsFromOfficialMoments(rows, { until: "2026-10-10T13:00:00Z", boat: { lat: -21.05, lon: 165.1 } });
    assert.equal(now.title, "Parc de la mer de Corail");
  });

  it("without a position, the latest moment (date only)", () => {
    assert.equal(pickOfficialMoment(rows).t, "2026-10-10T12:00:00Z");
    const { now } = cardsFromOfficialMoments(rows, { until: "2026-10-10T13:00:00Z" });
    assert.equal(now.title, "ZEE Vanuatu");
  });

  it("never a moment after `until`, never an old one outside the window", () => {
    const old = [row("2026-09-01T00:00:00Z", -22.1, 166.5, { alerts: [{ kind: "poe", title: "Vieux", fact: "x" }] }), ...rows];
    const { now } = cardsFromOfficialMoments(old, { until: "2026-10-10T07:00:00Z", boat: { lat: -22.1, lon: 166.5 } });
    assert.equal(now.title, "Port d’entrée Nouméa".replace("Port d’entrée ", ""));
  });
});

describe("Maintenant tab: fallback title never a hash", () => {
  it("place name when known, else the translated type", () => {
    const named = [{ t: "2026-10-10T00:00:00Z", signature: SHA, pos: { lat: -22, lon: 166 }, here: { place: { name: "Nouméa" } } }];
    const a = cardsFromOfficialMoments(named, { lang: "fr" }).freeQueue[0];
    assert.equal(a.title, "Nouméa");
    const bare = [{ t: "2026-10-10T00:00:00Z", signature: SHA, pos: { lat: -22, lon: 166 } }];
    const fr1 = cardsFromOfficialMoments(bare, { lang: "fr" }).freeQueue[0];
    const en1 = cardsFromOfficialMoments(bare, { lang: "en" }).freeQueue[0];
    assert.equal(fr1.title, fr.momentFallbackTitle);
    assert.equal(en1.title, en.momentFallbackTitle);
    for (const card of [a, fr1, en1]) {
      assert.ok(!card.title.includes(SHA));
      assert.ok(!/^[0-9a-f]{16,}$/i.test(card.title));
      assert.ok(!String(card.text).includes(SHA));
    }
  });

  it("a hash-like title from the store is not shown either", () => {
    const rows = [row("2026-10-10T00:00:00Z", -22, 166, { around: [{ kind: "place", title: SHA }] })];
    const { freeQueue } = cardsFromOfficialMoments(rows, { lang: "en" });
    assert.ok(freeQueue.every((c) => !c.title.includes(SHA)));
  });
});

describe("Maintenant tab: no port of entry alert through i18n", () => {
  it("FR and EN keys exist", () => {
    assert.ok(fr.alertNoPortOfEntryFor.includes("{zone}"));
    assert.ok(en.alertNoPortOfEntryFor.includes("{zone}"));
    assert.ok(fr.alertNoPortOfEntry && en.alertNoPortOfEntry);
  });

  it("the stored French sentence reads in English in EN", () => {
    const stored = "Aucun port d'entrée officiel n'est connu pour Vanuatu";
    const enText = localizeStoredFact(stored, "en");
    assert.equal(enText, "No official port of entry is known for Vanuatu.");
    assert.ok(!/Aucun|entrée/.test(enText));
    assert.equal(localizeStoredFact(stored, "fr"), "Aucun port d’entrée officiel n’est connu pour Vanuatu.");
    assert.equal(localizeStoredFact("Aucun port d'entrée officiel n'est connu pour cette ZEE.", "en"), en.alertNoPortOfEntry);
    assert.equal(localizeStoredLabel(stored, "en"), enText);
    assert.equal(localizeStoredFact("Profondeurs GEBCO", "en"), "Profondeurs GEBCO");
  });

  it("the Now card carries the translated alert", () => {
    const rows = [row("2026-10-10T00:00:00Z", -17, 168, {
      alerts: [{ kind: "entry", title: "Vanuatu", fact: "Aucun port d'entrée officiel n'est connu pour Vanuatu" }],
    })];
    assert.equal(cardsFromOfficialMoments(rows, { lang: "en" }).now.text, "No official port of entry is known for Vanuatu.");
  });
});

describe("one fact once in the Now tab", () => {
  const HIGH = "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir.";

  it("drops a server sentence the briefing already says (Ajaccio double)", () => {
    const briefing = `${HIGH} Ports à proximité : Ajaccio.\n\nMétéo au bateau : vent 12 kn.`;
    assert.deepEqual(sentencesNotShown([HIGH, "Météo au bateau : vent 12 kn."], [briefing]), []);
  });

  it("matches across quotes, spacing and final punctuation", () => {
    const shown = "Le bateau est en haute mer : aucune ZEE, pas de formalités d'entrée à prévoir";
    assert.deepEqual(sentencesNotShown([`  ${HIGH}  `], [shown]), []);
  });

  it("drops a sentence repeated by the server itself or said by an alert", () => {
    const fact = "Aucun port d’entrée officiel n’est connu pour Vanuatu.";
    assert.deepEqual(sentencesNotShown([HIGH, HIGH, fact], ["", fact]), [HIGH]);
  });

  it("keeps sentences nobody else says", () => {
    const amp = "À 3 milles de Scandola.";
    assert.deepEqual(sentencesNotShown([amp], [HIGH]), [amp]);
    assert.deepEqual(sentencesNotShown(null, [HIGH]), []);
  });
});

describe("keptSentences", () => {
  it("one flag per sentence, in order", () => {
    const a = "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir.";
    assert.deepEqual(keptSentences([a, "Vent 12 kn.", a], ["Vent 12 kn."]), [true, false, false]);
  });
});

describe("Now tab: the moment is chosen by position, not by date", () => {
  // Near Papeete, the latest stored moments are New Caledonia ones.
  const rows = [
    row("2026-09-20T00:00:00Z", -17.53, -149.57, { alerts: [{ kind: "zee", title: "ZEE Polynésie", fact: "Polynésie française" }] }),
    row("2026-09-21T00:00:00Z", -22.25, 166.45, { alerts: [{ kind: "poe", title: "Nouméa", fact: "Aucun port d'entrée officiel n'est connu pour Nouvelle-Calédonie" }] }),
    row("2026-09-21T06:00:00Z", -22.3, 166.5, { around: [{ kind: "marina", title: "Cercle Nautique Calédonien", fact: "Boulari 5,9 nm" }] }),
  ];
  const papeete = { lat: -17.55, lon: -149.6 };

  it("never a moment from another territory: the nearest one within the cap", () => {
    const picked = pickOfficialMoment(rows, { boat: papeete });
    assert.equal(picked.t, "2026-09-20T00:00:00Z");
    const { now, freeQueue } = cardsFromOfficialMoments(rows, { until: "2026-09-22T00:00:00Z", boat: papeete, lang: "fr" });
    const text = JSON.stringify({ now, freeQueue });
    assert.doesNotMatch(text, /Calédoni|Boulari|Nouméa/);
  });

  it("nothing near the boat: no moment rather than a far one", () => {
    assert.equal(pickOfficialMoment(rows, { boat: { lat: 0, lon: -30 } }), null);
    assert.ok(MOMENT_MAX_NM > 0 && MOMENT_MAX_NM < 1000, "well under Papeete – Nouméa (≈ 2 500 nm)");
  });

  it("the Ici frame takes the journal entry where the boat is", () => {
    const live = { t: "2026-09-22T00:00:00Z", pos: papeete, alerts: [], here: {}, around: [] };
    const journal = [
      { t: "2026-09-20T00:00:00Z", pos: { lat: -17.53, lon: -149.57 }, signature: "pf", here: { sentences: ["Polynésie."] } },
      { t: "2026-09-21T06:00:00Z", pos: { lat: -22.3, lon: 166.5 }, signature: "nc", here: { sentences: ["Nouvelle-Calédonie."] } },
    ];
    const frame = displayIciFrame(live, journal, "follow");
    assert.equal(frame.shown.signature, "pf");
    assert.deepEqual(frame.here.sentences, ["Polynésie."]);
    assert.equal(momentNearest(journal, { t: live.t, pos: { lat: 0, lon: -30 } }), null);
  });
});

describe("Now tab: no raw code as a card title", () => {
  it("« grib / grib » and « amp / Pertuis… » read as words, FR and EN", () => {
    const rowsCodes = [row("2026-09-01T00:00:00Z", 46.0, -1.6, {
      changes: [
        { kind: "layer", layer: "grib", title: "grib", fact: "grib" },
        { kind: "amp", title: "amp", fact: "Pertuis charentais - Rochebonne" },
      ],
    })];
    for (const [lang, grib, amp] of [["fr", fr.momentKindGrib, fr.momentKindAmp], ["en", en.momentKindGrib, en.momentKindAmp]]) {
      const { freeQueue } = cardsFromOfficialMoments(rowsCodes, { lang, boat: { lat: 46.0, lon: -1.6 } });
      const titles = freeQueue.map((c) => c.title);
      assert.ok(titles.includes(grib), `${lang} ${titles}`);
      assert.ok(titles.includes("Pertuis charentais - Rochebonne"), `${lang} ${titles}`);
      assert.equal(freeQueue.find((c) => c.title === "Pertuis charentais - Rochebonne").text, amp);
      for (const c of freeQueue) assert.doesNotMatch(`${c.title} ${c.text}`, /^(grib|amp)\b|\b(grib|amp)$/);
    }
  });
});

describe("Now tab: English renamed stop still matches the stored port", () => {
  it("Azores (Portugal) keeps the Açores departure phase via rawName", () => {
    const card = escaleCard({
      fromStop: "Açores (Corse)",
      toStop: "La Rochelle",
      legNm: 800,
      lat: 37.74,
      lon: -25.67,
    }, "en");
    assert.equal(card.entity.name, "Azores (Portugal)");
    assert.equal(card.entity.rawName, "Açores (Corse)");
    assert.equal(card.key, "ev:escale:Açores (Corse)→La Rochelle");
    const leg = { fromStop: "Açores (Corse)", toStop: "La Rochelle", doneNm: 4, leftNm: 790 };
    assert.equal(portCardIsCurrent(card, { leg }), true);
    assert.equal(portCardIsCurrent({
      kind: "escale",
      entity: { name: "Azores (Portugal)" },
    }, { leg }), false);
  });
});

describe("Now tab: the departure port card at 6 nm", () => {
  it("La Rochelle shows while arriving, whatever the stored name form", () => {
    const card = { kind: "port", title: "Escale La Rochelle (Charente-Maritime)", entity: { name: "Escale La Rochelle (Charente-Maritime)" } };
    assert.equal(portCardIsCurrent(card, { leg: { fromStop: "Saint-Maur (Berry, Indre)", toStop: "La Rochelle", doneNm: 120, leftNm: 6 } }), true);
    assert.equal(stopKey("Escale La Rochelle (Charente-Maritime)"), stopKey("La Rochelle"));
    assert.notEqual(stopKey("La Rochelle"), stopKey("Rochefort"));
  });
});

describe("Now tab: « haute mer » once in the whole tab", () => {
  it("the briefing and the server say it once between them", () => {
    const HIGH = "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir.";
    const briefing = `${HIGH}\n\nMétéo au bateau : vent 12 kn.`;
    assert.deepEqual(sentencesNotShown([HIGH], [briefing]), []);
    assert.deepEqual(keptSentences([HIGH, HIGH], [""]), [true, false]);
  });
});

describe("Now tab: a null position is unknown, not (0, 0)", () => {
  // A moment in the Gulf of Guinea, at (0, 0): it must not win for a null boat.
  const rowsGulf = [
    row("2026-09-20T00:00:00Z", 0, 0, { alerts: [{ kind: "zee", title: "Golfe de Guinée", fact: "Golfe de Guinée" }] }),
    row("2026-09-21T00:00:00Z", -17.53, -149.57, { alerts: [{ kind: "zee", title: "Polynésie", fact: "Polynésie française" }] }),
  ];

  for (const boat of [{ lat: null, lon: null }, { lat: null, lon: 0 }, { lat: 0, lon: null }, { lat: "", lon: "" }]) {
    it(`official moment for boat ${JSON.stringify(boat)}: chosen by date`, () => {
      assert.equal(pickOfficialMoment(rowsGulf, { boat }).t, "2026-09-21T00:00:00Z");
    });

    it(`journal moment for pos ${JSON.stringify(boat)}: chosen by date`, () => {
      const journal = [
        { t: "2026-09-20T00:00:00Z", pos: { lat: 0, lon: 0 }, signature: "gulf" },
        { t: "2026-09-21T00:00:00Z", pos: { lat: -17.53, lon: -149.57 }, signature: "pf" },
      ];
      assert.equal(momentNearest(journal, { t: "2026-09-22T00:00:00Z", pos: boat }).signature, "pf");
    });
  }

  it("a journal row with a null position is never « at » (0, 0)", () => {
    const journal = [
      { t: "2026-09-20T00:00:00Z", pos: { lat: null, lon: null }, signature: "nowhere" },
      { t: "2026-09-19T00:00:00Z", pos: { lat: 0.2, lon: 0.2 }, signature: "near" },
    ];
    assert.equal(momentNearest(journal, { t: "2026-09-22T00:00:00Z", pos: { lat: 0, lon: 0 } }).signature, "near");
  });
});
