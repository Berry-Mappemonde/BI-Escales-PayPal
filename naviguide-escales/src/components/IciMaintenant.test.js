import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import fixture from "../fixtures/moment.json" with { type: "json" };
import { momentSearchParams, validMomentPosition } from "../hooks/useMoment.js";
import { wrapLon } from "../utils/geo.js";
import { sortJournalEntries } from "../hooks/useMomentJournal.js";
import {
  dismissAlert,
  defaultIciTab,
  formatJournalLine,
  hiddenIciTabs,
  journalChangeLabel,
  displayIciFrame,
  localizeStoredTitle,
  legsFromClockMarks,
  seekJournalEntry,
  servesNowContent,
  visibleAlerts,
  visibleIciTabs,
  formatLegLine,
} from "./iciMaintenant.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "IciMaintenant.jsx"), "utf8");
const helpers = readFileSync(join(here, "iciMaintenant.js"), "utf8");
const hook = readFileSync(join(here, "..", "hooks", "useMoment.js"), "utf8");
const css = readFileSync(join(here, "..", "index.css"), "utf8");

const tFr = (key, vars = {}) => {
  const table = {
    iciLegDay: "J{n}",
    iciLegKn: "{kn} kn",
    iciLegRemaining: "reste {nm} nm",
    etaRange: "arrivée entre le {p10} et le {p90}",
  };
  return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), table[key] || key);
};

describe("IciMaintenant — film : étiquette position du jour", () => {
  it("masque le sac live et affiche l'étiquette i18n", () => {
    assert.equal(en.iciTodayPosition, "Today's position");
    assert.equal(fr.iciTodayPosition, "position du jour");
    assert.match(src, /todayPosition = false/);
    assert.match(src, /data-testid="ici-today-position"/);
    assert.match(src, /t\("iciTodayPosition"\)/);
    assert.doesNotMatch(src, /Today's position|position du jour/);
    const section = src.slice(src.indexOf('testId="ici-section-here"'));
    const labelAt = section.indexOf('data-testid="ici-today-position"');
    const elseAt = section.indexOf(") : (", labelAt);
    const bodyAt = section.indexOf("{hereBody}", elseAt);
    assert.ok(labelAt >= 0 && elseAt > labelAt && bodyAt > elseAt, "le sac est dans la branche sans étiquette");
    const sidebar = readFileSync(join(here, "Sidebar.jsx"), "utf8");
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.match(sidebar, /todayPosition=\{todayPosition\}/);
    assert.match(app, /todayPosition=\{Boolean\(iciPack\.todayPosition\)\}/);
  });
});

describe("IciMaintenant — : cinq sections, pas de titre", () => {
  it("rend les cinq sections et le sélecteur à trois onglets, sans bandeau", () => {
    assert.match(src, /data-testid="ici-maintenant"/);
    assert.match(src, /data-testid="ici-tabs"/);
    assert.match(src, /data-testid=\{testId\}/);
    assert.match(src, /data-testid=\{tab\.testId\}/);
    assert.match(src, /visibleIciTabs\(mode/);
    assert.match(src, /tabs\.map\(\(tab\) =>/);
    assert.doesNotMatch(src, /ICI_TABS\.map/);
    for (const id of [
      "ici-section-leg",
      "ici-section-alerts",
      "ici-section-here",
      "ici-section-around",
      "ici-section-sources",
    ]) {
      assert.match(src, new RegExp(`testId="${id}"`));
    }
    assert.match(helpers, /ici-tab-now/);
    assert.match(helpers, /ici-tab-story/);
    assert.match(helpers, /ici-tab-journal/);
    assert.match(helpers, /ici-tab-review/);
    assert.match(helpers, /iciNowTab/);
    assert.match(helpers, /iciStoryTab/);
    assert.match(helpers, /iciJournalTab/);
    assert.match(helpers, /planReviewTitle/);
    assert.match(src, /iciSectionLeg/);
    assert.match(src, /iciSectionAlerts/);
    assert.match(src, /iciSectionHere/);
    assert.match(src, /iciSectionAround/);
    assert.match(src, /iciSectionSources/);
    assert.doesNotMatch(src, /Ici et maintenant|Here and now|iciNowTitle|ici-title|ici-banner/);
    assert.doesNotMatch(src, /<h[1-6]\b/);
    assert.doesNotMatch(src, /momentNowTitle|storyHint|journalHint/);
  });

  it("ferme une pastille sans en ouvrir une autre", () => {
    const alerts = fixture.alerts;
    assert.ok(alerts.length >= 2, "la fixture porte au moins deux alertes");
    const first = alerts[0].id;
    const second = alerts[1].id;
    const afterOne = dismissAlert(new Set(), first);
    const shown = visibleAlerts(alerts, afterOne);
    assert.equal(shown.some((a) => a.id === first), false);
    assert.equal(shown.some((a) => a.id === second), true);
    assert.equal(shown.length, alerts.length - 1);
    const afterTwo = dismissAlert(afterOne, second);
    const left = visibleAlerts(alerts, afterTwo);
    assert.equal(left.some((a) => a.id === second), false);
    assert.equal(left.length, alerts.length - 2);
  });

  it("conserve les liens de sources et les emplacements vides Récit / Journal", () => {
    assert.match(src, /data-testid="ici-source-link"/);
    assert.match(src, /here\?\.links/);
    assert.match(src, /target="_blank"/);
    assert.match(src, /rel="noopener noreferrer"/);
    assert.match(src, /data-testid="ici-story-slot"/);
    assert.match(src, /data-testid="ici-journal-slot"/);
    assert.match(src, /flex-1 min-h-0 overflow-auto/);
    assert.doesNotMatch(src, /Bientôt|placeholder|aide|hint|TODO/i);
  });

  it("formate la ligne d'étape avec les noms affichés, pas le suffixe d'une autre escale", () => {
    const line = formatLegLine({
      from: "Açores (Corse)",
      to: "Saint-Maur (Berry, Indre)",
      day: 3,
      kn: 6.5,
      remainingNm: 40,
    }, tFr, "fr");
    assert.match(line, /^Açores → Saint-Maur \(Indre\)/);
    assert.doesNotMatch(line, /Corse|Berry/);
    assert.match(line, /J3/);
    assert.match(line, /reste 40 nm/);
    const enLine = formatLegLine({
      from: "Açores (Corse)",
      to: "Ajaccio (Corse)",
    }, (key, vars = {}) => {
      const table = { iciLegDay: "D{n}", iciLegKn: "{kn} kn", iciLegRemaining: "{nm} nm left" };
      return Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, String(v ?? "")), table[key] ?? key);
    }, "en");
    assert.match(enLine, /^Azores \(Portugal\) → Ajaccio \(Corse\)/);
  });

  it("formate la ligne d'étape avec les chiffres du Moment, sans en inventer", () => {
    const line = formatLegLine(fixture.leg, tFr, "fr");
    assert.match(line, /Fort-de-France/);
    assert.match(line, /Pointe-à-Pitre/);
    assert.match(line, /J21/);
    assert.match(line, /8,0 kn/);
    assert.match(line, /reste 80 nm/);
    assert.match(line, /arrivée entre le/);
  });
});

describe("IciMaintenant — : récit / journal / escale, pas d'Écouter", () => {
  it("reçoit les vues Récit et Journal et ouvre l'escale dans Ici", () => {
    assert.match(src, /data-testid="ici-story-slot"/);
    assert.match(src, /data-testid="ici-journal-slot"/);
    assert.match(src, /<EscaleSheet/);
    assert.match(src, /escale\?\.stop/);
    assert.match(src, /testId="moment-now"/);
    assert.match(src, /testId="moment-free"/);
    assert.doesNotMatch(src, /ListenButton/);
    assert.doesNotMatch(src, /moment-free-listen/);
    assert.doesNotMatch(src, /momentNowTitle|momentFreeTitle/);
  });
});

describe("IciMaintenant — : journal chronologique, clic → onSeek(t)", () => {
  const entries = [
    { t: "2026-06-23T08:00:00Z", pos: { lat: 14.6, lon: -61.0 }, signature: "c", seq: 2, changes: [{ title: "Fort-de-France" }] },
    { t: "2026-05-15T08:00:00Z", pos: { lat: 48.86, lon: 2.35 }, signature: "a", seq: 0, changes: [] },
    { t: "2026-06-02T08:00:00Z", pos: { lat: 32.1, lon: -16.9 }, signature: "b", seq: 1, changes: [{ title: "ZEE du Maroc" }] },
  ];

  it("rend N entrées dans l'ordre chronologique", () => {
    const lines = sortJournalEntries(entries).map((entry) => formatJournalLine(entry, "fr"));
    assert.equal(lines.length, 3);
    assert.match(lines[0], /15 mai/);
    assert.match(lines[1], /2 juin/);
    assert.match(lines[2], /23 juin/);
    assert.match(lines[0], /48,9/);
    assert.match(lines[1], /ZEE du Maroc/);
    assert.match(src, /data-testid="ici-journal-entry"/);
    assert.match(src, /data-testid="ici-journal-list"/);
    assert.match(src, /hidden=\{view !== "journal"\}/);
    assert.match(src, /sortJournalEntries\(entries\)/);
    assert.match(src, /formatJournalLine\(entry, lang\)/);
    assert.doesNotMatch(src, /journalHint|Le journal commence|cliquez|aide/i);
  });

  it("clic appelle onSeek(t)", () => {
    const seen = [];
    seekJournalEntry((t) => seen.push(t), entries[2]);
    assert.deepEqual(seen, ["2026-06-02T08:00:00Z"]);
    seekJournalEntry((t) => seen.push(t), { t: "2026-05-15T08:00:00Z" });
    assert.deepEqual(seen, ["2026-06-02T08:00:00Z", "2026-05-15T08:00:00Z"]);
    assert.match(src, /seekJournalEntry\(onSeek, entry\)/);
    assert.match(src, /displayIciFrame\(moment, journalEntries, mode\)/);
  });
});

describe("useMoment", () => {
  it("interroge /ici/moment ; sans lat/lon ou API KO → moment null, pas la fixture", () => {
    assert.match(hook, /\/ici\/moment\?/);
    assert.match(hook, /moment: null/);
    assert.match(hook, /source: "none"/);
    assert.match(hook, /export const MOMENT_FIXTURE/);
    assert.doesNotMatch(hook, /moment: MOMENT_FIXTURE/);
    assert.doesNotMatch(hook, /source: "fixture"/);
    assert.match(hook, /controller\.abort\(\)/);
    assert.match(hook, /frozen = false/);
    assert.match(hook, /if \(frozen\) return undefined/);
    const q = momentSearchParams({ lat: 37.7, lon: 236.84, t: "2026-05-15T08:00:00Z", mode: "follow", lang: "fr" });
    assert.equal(Number(Number(q.get("lon")).toFixed(2)), Number(wrapLon(236.84).toFixed(2)));
    assert.equal(q.get("t"), "2026-05-15T08:00:00Z");
  });

  it("no request without a valid position (never lat=null&lon=0)", () => {
    for (const [lat, lon] of [[null, null], [null, 0], [undefined, 5], ["", 5], [12, null], [NaN, 1], [95, 1], [true, 1]]) {
      assert.equal(validMomentPosition(lat, lon), null, `${lat},${lon}`);
      assert.equal(momentSearchParams({ lat, lon, mode: "follow" }), null, `${lat},${lon}`);
    }
    // 0, 0 is a real position.
    assert.deepEqual(validMomentPosition(0, 0), { lat: 0, lon: 0 });
    assert.equal(momentSearchParams({ lat: 0, lon: 0 }).toString(), "lat=0&lon=0");
    assert.equal(momentSearchParams({ lat: "41.92", lon: "8.74" }).get("lat"), "41.92");
  });
});

describe("IciMaintenant — : encadré honnête", () => {
  it("moment null : sections présentes, aucune ligne Antilles", () => {
    for (const id of [
      "ici-section-leg",
      "ici-section-alerts",
      "ici-section-here",
      "ici-section-around",
      "ici-section-sources",
    ]) {
      assert.match(src, new RegExp(`testId="${id}"`));
    }
    assert.equal(formatLegLine(null, tFr, "fr"), "");
    assert.equal(formatLegLine(undefined, tFr, "fr"), "");
    assert.equal(formatLegLine({}, tFr, "fr"), "");
    assert.deepEqual(visibleAlerts(null, new Set()), []);
    assert.doesNotMatch(src, /Fort-de-France|Pointe-à-Pitre|CORIOLIS-Guadeloupe/);
  });

  it("rend here.sentences et here.links même si hereBody est passé", () => {
    assert.match(src, /hereBody/);
    assert.match(src, /here\?\.sentences/);
    assert.match(src, /here\?\.links/);
    assert.match(src, /data-testid="ici-here-sentence"/);
    assert.match(src, /data-testid="ici-source-link"/);
    assert.doesNotMatch(src, /!hereBody \? \(shown\?\.here\?\.sentences/);
    const idxBody = src.indexOf("{hereBody}");
    const idxSent = src.indexOf("(here?.sentences || []).map");
    assert.ok(idxBody >= 0 && idxSent > idxBody, "sentences après hereBody, sans le masquer");
  });

  it("fermeture d'une pastille inchangée", () => {
    const alerts = fixture.alerts;
    const first = alerts[0].id;
    const second = alerts[1].id;
    const afterOne = dismissAlert(new Set(), first);
    const shown = visibleAlerts(alerts, afterOne);
    assert.equal(shown.some((a) => a.id === first), false);
    assert.equal(shown.some((a) => a.id === second), true);
    assert.equal(shown.length, alerts.length - 1);
  });
});

describe("IciMaintenant — : onglet Récit et journal nommé", () => {
  it("garde les quatre onglets en Suivre (DM9 élargit Récit à Tracer)", () => {
    assert.deepEqual(visibleIciTabs("follow").map((t) => t.id), ["now", "story", "journal", "review"]);
    assert.match(src, /visibleIciTabs\(mode/);
    assert.doesNotMatch(src, /className="mt-1\.5 min-h-0 flex-1"/);
    assert.doesNotMatch(src, /placeholder|journalHint|récit vide|onglet vide/i);
  });

  it("nomme l'AMP, le cyclone et la marina d'après le fait, sans inventer", () => {
    const ampNamed = journalChangeLabel({
      changes: [{ kind: "amp", score: 1, title: "Iroise", fact: "Iroise (4 nm)" }],
    }, "fr");
    assert.equal(ampNamed, "Aire marine protégée — Iroise");
    const ampFromFact = journalChangeLabel({
      changes: [{ kind: "alert-on", score: 3, title: "Aire marine protégée", fact: "Iroise (4 nm): IUCN II." }],
    }, "fr");
    assert.equal(ampFromFact, "Aire marine protégée — Iroise");
    const ampTypeOnly = journalChangeLabel({
      changes: [{ kind: "amp", score: 1, title: "Aire marine protégée", fact: "" }],
    }, "fr");
    assert.equal(ampTypeOnly, "Aire marine protégée");
    const cyclone = journalChangeLabel({
      changes: [{ kind: "cyclone", score: 3, title: "Cyclone", fact: "Irma (2017)" }],
    }, "fr");
    assert.equal(cyclone, "Cyclone — Irma (2017)");
    const cycloneAnon = journalChangeLabel({
      changes: [{ kind: "cyclone", score: 3, title: "Cyclone", fact: "3 traces de cyclone ce mois-ci." }],
    }, "fr");
    assert.equal(cycloneAnon, "Cyclone");
    const marina = journalChangeLabel({
      changes: [{ kind: "marina", score: 1, title: "Marina Bas-du-Fort", fact: "Marina Bas-du-Fort (16 nm)" }],
    }, "fr");
    assert.equal(marina, "Marina — Marina Bas-du-Fort");
    const ports = journalChangeLabel({
      changes: [{ kind: "zee-enter", score: 2, title: "Ports d'entrée : Pointe-à-Pitre", fact: "Pointe-à-Pitre" }],
    }, "fr");
    assert.equal(ports, "Ports d'entrée : Pointe-à-Pitre");
    const line = formatJournalLine({
      t: "2026-05-16T10:00:00Z",
      pos: { lat: 48.2, lon: -4.8 },
      changes: [{ kind: "amp", score: 1, title: "Iroise", fact: "Iroise (4 nm)" }],
    }, "fr");
    assert.match(line, /Aire marine protégée — Iroise/);
    assert.doesNotMatch(line, /Iroise Iroise/);
    assert.equal(localizeStoredTitle("Formalités d’entrée", "en"), "Entry formalities");
    assert.equal(localizeStoredTitle("Aire marine protégée", "en"), "Marine protected area");
    assert.equal(localizeStoredTitle("Station croisée", "en"), "Station passed");
    assert.equal(journalChangeLabel({
      changes: [{ kind: "entry", score: 2, title: "Formalités d’entrée", fact: "" }],
    }, "en"), "Entry formalities");
    assert.equal(journalChangeLabel({
      changes: [{ kind: "amp", score: 1, title: "Aire marine protégée", fact: "Iroise (4 nm)" }],
    }, "en"), "Marine protected area — Iroise");
    assert.equal(journalChangeLabel({
      changes: [{ kind: "stop", score: 3, title: "Escale Saint-Maur", fact: "" }],
    }, "en"), "Stopover — Saint-Maur");
    assert.equal(journalChangeLabel({
      changes: [{ kind: "sci", score: 2, title: "Station croisée", fact: "" }],
    }, "en"), "Station passed");
    assert.equal(localizeStoredTitle("AMP", "en"), "Marine protected area");
    assert.equal(localizeStoredTitle("AMP Taaone", "en"), "Marine protected area Taaone");
    assert.equal(localizeStoredTitle("Aire marine protégée Matavai", "en"), "Marine protected area Matavai");
    assert.equal(localizeStoredTitle("Zone économique exclusive espagnole", "en"), "Spanish EEZ");
    assert.equal(localizeStoredTitle("Zone économique exclusive vénézuélienne", "en"), "Venezuelan EEZ");
    assert.equal(localizeStoredTitle("Entrée dans Zone économique exclusive française (France métropolitaine)", "en"), "Entering French EEZ (France métropolitaine)");
    assert.equal(journalChangeLabel({
      changes: [{ kind: "zee-enter", score: 2, title: "Zone économique exclusive espagnole", fact: "" }],
    }, "en"), "Spanish EEZ");
    assert.doesNotMatch(journalChangeLabel({
      changes: [{ kind: "zee", score: 2, title: "Zone économique exclusive espagnole", fact: "" }],
    }, "en"), /Zone économique|Aire marine|\bAMP\b|\bZEE\b/);
    const live = { t: "2026-05-16T10:00:00Z", alerts: [{ id: "entry-1", title: "Entry formalities" }], here: { sentences: ["English waters."] } };
    const journalFr = [{ t: "2026-05-16T09:00:00Z", alerts: [{ id: "entry-1", title: "Formalités d’entrée" }], here: { sentences: ["Eaux françaises."] } }];
    const frame = displayIciFrame(live, journalFr, "follow");
    assert.equal(frame.here.sentences[0], "English waters.");
    assert.equal(frame.alerts[0].title, "Entry formalities");
  });
});

describe("IciMaintenant — : fiche d'escale en tête de Ici", () => {
  it("rend EscaleSheet avant hereBody / story-source quand escale.stop", () => {
    const idxSheet = src.indexOf("<EscaleSheet");
    const idxBody = src.indexOf("{hereBody}");
    assert.ok(idxSheet >= 0 && idxBody > idxSheet, "fiche avant hereBody (ligne Nemotron)");
    assert.match(src, /escale\?\.stop/);
    assert.match(src, /onViewChange\("now"\)/);
    assert.doesNotMatch(src, /placeholder|aide|hint|cliquez le drapeau/i);
  });
});

describe("IciMaintenant — : journal lisible dans les deux thèmes", () => {
  it("pose une couleur explicite claire (sombre) et foncée (clair), sans text-inherit", () => {
    assert.match(
      css,
      /(?:^|\n)\.ici-maintenant \[data-testid="ici-journal-entry"\] \{[\s\S]{0,80}color:\s*rgb\(226 232 240\)/,
    );
    assert.match(
      css,
      /\.light-mode \.ici-maintenant \[data-testid="ici-journal-entry"\] \{[\s\S]{0,80}color:\s*rgb\(30 41 59\)/,
    );
    assert.match(src, /data-testid="ici-journal-entry"/);
    assert.doesNotMatch(src, /text-inherit/);
  });
});

describe("IciMaintenant — : onglet Revue du plan", () => {
  it("rend l'onglet Revue en Suivre et en Tracer (DM9 : aussi le brouillon)", () => {
    assert.ok(visibleIciTabs("follow").some((t) => t.id === "review"));
    assert.ok(visibleIciTabs("simulation").some((t) => t.id === "review"));
    assert.ok(visibleIciTabs("drawn").some((t) => t.id === "review"));
    assert.match(helpers, /ici-tab-review/);
    assert.match(helpers, /planReviewTitle/);
    assert.match(src, /data-testid="ici-review-slot"/);
    assert.match(src, /<PlanReview/);
    assert.match(src, /planReview\.legs/);
    assert.match(src, /startOpen/);
    assert.doesNotMatch(src, /placeholder|onglet vide|aide|hint/i);
  });
});

describe("IciMaintenant — : Tracer sert le tracé", () => {
  it("Tracer : Revue du plan et Récit seulement, Revue ouverte par défaut ; Suivre : 4 onglets", () => {
    assert.deepEqual(visibleIciTabs("follow").map((t) => t.id), ["now", "story", "journal", "review"]);
    assert.deepEqual(visibleIciTabs("simulation").map((t) => t.id), ["review", "story"]);
    assert.deepEqual(visibleIciTabs("drawn").map((t) => t.id), ["review", "story"]);
    assert.deepEqual(hiddenIciTabs("simulation").map((t) => t.id), ["now", "journal"]);
    assert.deepEqual(hiddenIciTabs("follow"), []);
    assert.equal(defaultIciTab("follow"), "now");
    assert.equal(defaultIciTab("simulation"), "review");
    assert.equal(defaultIciTab("drawn"), "review");
    assert.equal(servesNowContent("review", "simulation"), true);
    assert.equal(servesNowContent("review", "follow"), false);
    assert.equal(servesNowContent("now", "follow"), true);
    assert.equal(visibleIciTabs("simulation").some((t) => t.id === "now"), false);
    assert.equal(visibleIciTabs("simulation").some((t) => t.id === "journal"), false);
    assert.match(src, /defaultIciTab\(mode/);
    assert.match(src, /servesNowContent\(view, mode/);
    assert.match(src, /hiddenIciTabs\(mode/);
    assert.match(src, /extraTabs\.some\(\(tab\) => tab\.id === "now"\)/);
    assert.match(helpers, /ici-tab-now/);
    assert.match(helpers, /ici-tab-journal/);
    assert.doesNotMatch(src, /placeholder|aide|hint|onglet vide/i);
  });
});

describe("IciMaintenant — : Suivre × ma route", () => {
  it("masque Maintenant, garde Revue · Journal · Récit ; jambes depuis l'horloge", () => {
    assert.deepEqual(
      visibleIciTabs("follow", { routeSource: "custom" }).map((t) => t.id),
      ["review", "journal", "story"],
    );
    assert.deepEqual(hiddenIciTabs("follow", { routeSource: "custom" }).map((t) => t.id), ["now"]);
    assert.equal(defaultIciTab("follow", { routeSource: "custom" }), "review");
    assert.equal(servesNowContent("now", "follow", { routeSource: "custom" }), false);
    assert.deepEqual(visibleIciTabs("follow").map((t) => t.id), ["now", "story", "journal", "review"]);
    const legs = legsFromClockMarks({
      marks: [
        { name: "La Rochelle", filmNm: 0, tHours: 0, iso: "2026-06-15T08:00:00Z" },
        { name: "Antilles", filmNm: 3350, tHours: 720, iso: "2026-07-15T08:00:00Z" },
      ],
    }, "fr");
    assert.equal(legs.length, 1);
    assert.match(legs[0].title, /La Rochelle/);
    assert.match(legs[0].title, /Antilles/);
    assert.equal(legsFromClockMarks({ marks: [{ name: "Seul" }] }).length, 0);
  });
});


it("localizes geographic exonyms in stored title parentheses without changing FR", () => {
  for (const [raw, expected] of [
    ["Pojada (Polynésie Française)", "Pojada (French Polynesia)"],
    ["Station (Wallis-et-Futuna)", "Station (Wallis and Futuna)"],
  ]) {
    assert.equal(localizeStoredTitle(raw, "en"), expected);
    assert.equal(localizeStoredTitle(raw, "fr"), raw);
  }
});
