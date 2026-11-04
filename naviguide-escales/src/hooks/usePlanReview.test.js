import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ADVICE_FIXTURE,
  ETA_MIN_KN,
  ETA_RETRY_MS,
  boundEtaIso,
  buildAdviceCompare,
  attachClockIso,
  etaDayLabel,
  etaDisplayFromResponse,
  etaFromResponse,
  etaRangeFromMembers,
  etaRetryDue,
  formatAdvicePills,
  formatAdviceSentence,
  formatEtaRange,
  formatEtaRangeTitle,
  isAdviceDone,
  isAdviceUnavailable,
  localizeAdviceSentence,
  nextEtaRetryMs,
  nextStopFromMarks,
  nextStopRowIndex,
  officialNowMs,
  legendNowAndLive,
  countOfficialEtaPolls,
  shouldPollOfficialEta,
  pickHeaviestLegIdx,
  pollOfficialAdvice,
  pollOfficialEta,
  reviewAdviceKey,
  startOfficialEtaWatch,
  startWarmStatusWatch,
  tightenEtaMembers,
} from "./usePlanReview.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "usePlanReview.js"), "utf8");
const sidebarSrc = readFileSync(join(here, "../components/Sidebar.jsx"), "utf8");

const tick = (ms = 15) => new Promise((r) => setTimeout(r, ms));
const hangUntilAbort = (_ms, signal) => new Promise((resolve, reject) => {
  const onAbort = () => {
    const err = new Error("aborted");
    err.name = "AbortError";
    reject(err);
  };
  if (signal?.aborted) {
    onAbort();
    return;
  }
  signal?.addEventListener?.("abort", onAbort, { once: true });
});

const interpolate = (dict) => (key, vars = {}) =>
  Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), dict[key] ?? key);

const tFr = interpolate(fr);
const tEn = interpolate(en);
const plain = (s) => String(s).replace(/[\u202f\u00a0]/g, " ");

describe("usePlanReview — fourchette ETA", () => {
  it("ne fabrique pas de fourchette sans membres ou sans dates", () => {
    assert.equal(formatEtaRange(null, tFr, "fr"), "");
    assert.equal(formatEtaRange({ members: 0, p10: "2026-10-11T00:00:00Z", p90: "2026-10-14T00:00:00Z" }, tFr, "fr"), "");
    assert.equal(formatEtaRange({ members: 80, p10: null, p90: null }, tFr, "fr"), "");
    assert.equal(formatEtaRangeTitle(null, tFr), "");
  });

  it("écrit les dates courtes fr/en, sans p10 ni membres à l'écran", () => {
    const eta = { members: 80, p10: "2026-10-31T08:00:00Z", p90: "2026-11-04T18:00:00Z" };
    const frLabel = plain(formatEtaRange(eta, tFr, "fr"));
    assert.match(frLabel, /^arrivée entre le 31 oct\.? et le 4 nov/);
    assert.doesNotMatch(frLabel, /p10|membres/i);
    const enLabel = plain(formatEtaRange(eta, tEn, "en"));
    assert.match(enLabel, /^arrival between 31 Oct\.? and 4 Nov/i);
    assert.doesNotMatch(enLabel, /p10|members/i);
    assert.equal(formatEtaRangeTitle(eta, tFr), "p10–p90, 80 membres");
    assert.equal(formatEtaRangeTitle(eta, tEn), "p10–p90, 80 members");
  });

  it("garde le mois même quand p10 et p90 sont dans le même mois", () => {
    const eta = { members: 30, p10: "2026-10-11T08:00:00Z", p90: "2026-10-14T18:00:00Z" };
    const frLabel = plain(formatEtaRange(eta, tFr, "fr"));
    assert.match(frLabel, /11 oct/);
    assert.match(frLabel, /14 oct/);
    assert.doesNotMatch(frLabel, /p10|membres/i);
  });

  it("prend la prochaine escale dont l'iso est dans le futur", () => {
    const now = Date.parse("2026-09-20T12:00:00Z");
    const name = nextStopFromMarks([
      { name: "Nouméa", iso: "2026-09-01T00:00:00Z" },
      { name: "Dzaoudzi", iso: "2026-10-12T00:00:00Z" },
    ], now);
    assert.equal(name, "Dzaoudzi");
    assert.equal(nextStopFromMarks([], now), "");
  });

  it("appelle GET /voyage/official/eta et n'invente rien si members=0", () => {
    assert.match(src, /\/voyage\/official\/eta\?stop=/);
    assert.match(src, /Number\(body\.members\) > 0/);
    assert.match(src, /etaRange: eta/);
    assert.match(src, /formatEtaRangeTitle/);
    assert.match(src, /pollOfficialEta/);
    assert.match(src, /ETA_RETRY_MS/);
  });

  it("affiche la fourchette dès que members passe de 0 à un ensemble", async () => {
    const empty = { members: 0, p10: null, p90: null };
    const full = {
      members: 40,
      p10: "2026-11-13T00:00:00Z",
      p50: "2026-11-15T00:00:00Z",
      p90: "2026-11-18T00:00:00Z",
    };
    let n = 0;
    const seen = [];
    const ready = await pollOfficialEta("Dzaoudzi", {
      fetchFn: async () => {
        n += 1;
        return n === 1 ? empty : full;
      },
      sleep: async () => {},
      onUpdate: (eta) => seen.push(eta),
    });
    assert.equal(etaFromResponse(empty), null);
    assert.equal(seen[0], null);
    assert.equal(formatEtaRange(empty, tFr, "fr"), "");
    assert.equal(ready.members, 40);
    const label = plain(formatEtaRange(ready, tFr, "fr"));
    assert.match(label, /arrivée entre le 13 nov/);
    assert.match(label, /18 nov/);
    assert.doesNotMatch(label, /p10|membres/i);
    assert.equal(plain(formatEtaRange(ready, tEn, "en")).slice(0, 16).toLowerCase(), "arrival between ");
    assert.equal(n, 2);
    assert.equal(nextEtaRetryMs(0), ETA_RETRY_MS[0]);
    assert.ok(nextEtaRetryMs(9) >= nextEtaRetryMs(0));
    assert.equal(ETA_RETRY_MS[ETA_RETRY_MS.length - 1], 30000);
  });

  it("écarte tout membre à 0 kn de la fourchette", () => {
    assert.equal(ETA_MIN_KN, 3);
    const members = [
      { knots: 8.1, arrival: "2026-11-13T00:00:00Z" },
      { knots: 0, arrival: "2027-06-10T00:00:00Z" },
      { knots: 7.8, arrival: "2026-11-16T00:00:00Z" },
    ];
    const kept = tightenEtaMembers(members);
    assert.equal(kept.some((m) => m.knots === 0), false);
    assert.equal(kept.length, 2);
    const eta = etaRangeFromMembers(members);
    assert.ok(eta);
    assert.ok(eta.memberKnots.every((k) => k >= ETA_MIN_KN));
    assert.doesNotMatch(eta.p90, /2027-06/);
    const days = (Date.parse(eta.p90) - Date.parse(eta.p10)) / 86400000;
    assert.ok(days <= 7, `span ${days} j`);
    const label = plain(formatEtaRange({
      members: 80,
      p10: "2026-11-13T00:00:00Z",
      p50: "2026-11-15T00:00:00Z",
      p90: "2027-06-10T00:00:00Z",
      memberKnots: [8, 8],
    }, tFr, "fr"));
    assert.doesNotMatch(label, /juin/i);
    assert.match(label, /arrivée entre le/);
    const hidden = boundEtaIso("2026-11-13T00:00:00Z", null, "2027-06-10T00:00:00Z");
    assert.equal(hidden.p10, "");
  });

  it("Ligne de raison quand members = 0, jamais une fourchette", () => {
    const empty = {
      members: 0,
      p10: "2026-10-11T00:00:00Z",
      p90: "2026-10-14T00:00:00Z",
      reason: "quota Open-Meteo atteint",
      nextRetry: "2026-09-29T00:15:00Z",
      status: "unavailable",
    };
    assert.equal(etaFromResponse(empty), null);
    assert.equal(etaDisplayFromResponse(empty), empty);
    const preparing = { members: 0, p10: null, p90: null, status: "preparing", reason: "en préparation" };
    assert.equal(etaDisplayFromResponse(preparing), preparing);
    const preparingLabel = plain(formatEtaRange(preparing, tFr, "fr"));
    assert.match(preparingLabel, /fourchette indisponible/);
    assert.match(preparingLabel, /en préparation/);
    assert.doesNotMatch(preparingLabel, /1 janv/);
    assert.equal(etaRetryDue(empty, Date.parse("2026-09-28T12:00:00Z")), false);
    const frLabel = plain(formatEtaRange(empty, tFr, "fr"));
    assert.match(frLabel, /fourchette indisponible/);
    assert.match(frLabel, /quota Open-Meteo atteint/);
    assert.match(frLabel, /29 sept/);
    assert.doesNotMatch(frLabel, /arrivée entre le/);
    const enLabel = plain(formatEtaRange(empty, tEn, "en"));
    assert.match(enLabel, /arrival window unavailable/i);
    assert.match(enLabel, /Open-Meteo quota reached/);
    assert.match(enLabel, /29 Sep/i);
    assert.doesNotMatch(enLabel, /arrival between/i);
  });

  it("PollOfficialEta s'arrête quand nextRetry est dans le futur", async () => {
    const unavailable = {
      members: 0,
      p10: null,
      p90: null,
      reason: "quota",
      nextRetry: "2099-01-02T00:15:00Z",
      status: "unavailable",
    };
    let n = 0;
    const seen = [];
    const out = await pollOfficialEta("Nouméa", {
      fetchFn: async () => {
        n += 1;
        return unavailable;
      },
      sleep: async () => {
        throw new Error("ne doit pas relancer");
      },
      onUpdate: (eta) => seen.push(eta),
    });
    assert.equal(n, 1);
    assert.equal(out.reason, "quota");
    assert.equal(seen[0].status, "unavailable");
    assert.match(plain(formatEtaRange(out, tFr, "fr")), /fourchette indisponible/);
  });

  it("NextRetry null ou epoch : pas « 1 janv. »", () => {
    assert.equal(etaDayLabel(null, "fr"), "");
    assert.equal(etaDayLabel(undefined, "fr"), "");
    assert.equal(etaDayLabel("", "fr"), "");
    assert.equal(etaDayLabel("1970-01-01T00:00:00Z", "fr"), "");
    assert.match(etaDayLabel("2026-09-30T00:00:00Z", "fr"), /30 sept/);
    const noRetry = {
      members: 0,
      p10: null,
      p90: null,
      reason: "quota Open-Meteo atteint",
      nextRetry: null,
      status: "unavailable",
    };
    const label = plain(formatEtaRange(noRetry, tFr, "fr"));
    assert.match(label, /fourchette indisponible/);
    assert.match(label, /quota Open-Meteo atteint/);
    assert.doesNotMatch(label, /1 janv/);
    assert.doesNotMatch(label, /nouvel essai/);
    const epoch = { ...noRetry, nextRetry: "1970-01-01T00:00:00.000Z" };
    assert.doesNotMatch(plain(formatEtaRange(epoch, tFr, "fr")), /1 janv/);
    const invalid = { ...noRetry, nextRetry: "pas-une-date" };
    assert.doesNotMatch(plain(formatEtaRange(invalid, tFr, "fr")), /1 janv/);
  });

  it("Label sur la prochaine, pas la première rangée", () => {
    const now = Date.parse("2026-09-29T12:00:00Z");
    const marks = [
      { name: "Saint-Maur (Berry, Indre)", iso: "2026-05-15T08:00:00Z", filmNm: 0 },
      { name: "La Rochelle", iso: "2026-05-15T12:00:00Z", filmNm: 122 },
      { name: "Nouméa (Nouvelle-Calédonie)", iso: "2026-09-30T07:51:40Z", filmNm: 19177 },
      { name: "La Rochelle", iso: "2027-04-17T21:16:31Z", filmNm: 39426 },
    ];
    const stolen = marks.map((m, i) => (
      i === 1 ? { ...m, iso: "2027-04-17T21:16:31Z" } : m
    ));
    assert.equal(nextStopFromMarks(stolen, now), "Nouméa (Nouvelle-Calédonie)");
    const clock = [
      { name: "Nouméa (Nouvelle-Calédonie)", iso: "2026-09-30T07:51:40Z", filmNm: 19336 },
      { name: "La Rochelle", iso: "2027-04-17T21:16:31Z", filmNm: 39585 },
    ];
    const attached = attachClockIso(marks, clock);
    assert.equal(attached[1].iso, "2026-05-15T12:00:00Z");
    assert.equal(attached[3].iso, "2027-04-17T21:16:31Z");
    assert.equal(nextStopFromMarks(attached, now), "Nouméa (Nouvelle-Calédonie)");
    const rows = attached.map((m) => ({ name: m.name, mark: m }));
    assert.equal(nextStopRowIndex(rows, attached, now), 2);
    assert.notEqual(nextStopRowIndex(rows, attached, now), 0);
    assert.notEqual(nextStopRowIndex(rows, attached, now), 1);
  });

  it("Horloge 19 sept. / 17 nm de Nouméa → Nouméa, pas Dzaoudzi", () => {
    const officialNow = Date.parse("2026-09-19T12:00:00Z");
    const wall = Date.parse("2026-09-29T20:00:00Z");
    const noumeaNm = 19177;
    const liveNm = noumeaNm - 17;
    const marks = [
      { name: "Saint-Maur (Berry, Indre)", iso: "2026-05-15T08:00:00Z", filmNm: 0 },
      { name: "La Rochelle", iso: "2026-05-15T12:00:00Z", filmNm: 122 },
      { name: "Nouméa (Nouvelle-Calédonie)", iso: "2026-09-01T00:00:00Z", filmNm: noumeaNm },
      { name: "Dzaoudzi", iso: "2026-10-12T00:00:00Z", filmNm: 25000 },
      { name: "Papeete", iso: "2026-12-01T00:00:00Z", filmNm: 30000 },
    ];
    assert.equal(nextStopFromMarks(marks, wall), "Dzaoudzi");
    assert.equal(nextStopFromMarks(marks, officialNow, liveNm), "Nouméa (Nouvelle-Calédonie)");
    assert.notEqual(nextStopFromMarks(marks, officialNow, liveNm), "Dzaoudzi");
    assert.notEqual(nextStopFromMarks(marks, officialNow, liveNm), "Papeete");
    const rows = marks.map((m) => ({ name: m.name, mark: m, at: m.filmNm }));
    assert.equal(nextStopRowIndex(rows, marks, officialNow, liveNm), 2);
    assert.notEqual(nextStopRowIndex(rows, marks, officialNow, liveNm), 1);
    assert.notEqual(nextStopRowIndex(rows, marks, officialNow, liveNm), 3);
  });

  it("Sans official.clock, aucun GET /eta ni ligne inventée", () => {
    assert.ok(Number.isNaN(officialNowMs(null, null)));
    assert.ok(Number.isNaN(officialNowMs({}, {})));
    assert.equal(
      officialNowMs({ t0: "2026-05-15T08:00:00Z" }, { iso: "2026-09-19T12:00:00Z" }),
      Date.parse("2026-09-19T12:00:00Z"),
    );
    assert.doesNotMatch(src, /export function nextStopFromMarks\(marks, nowMs = Date\.now\(\)\)/);
    assert.equal(nextStopFromMarks([
      { name: "Dzaoudzi", iso: "2026-10-12T00:00:00Z", filmNm: 25000 },
    ]), "");
    assert.equal(shouldPollOfficialEta({ enabled: true, stopName: "Nouméa" }), false);
    assert.equal(shouldPollOfficialEta({ enabled: true, stopName: "Papeete", officialClock: false }), false);
    assert.equal(shouldPollOfficialEta({
      enabled: true,
      stopName: "Nouméa",
      officialClock: true,
    }), true);
    const app = readFileSync(join(here, "../App.jsx"), "utf8");
    // L'ETA officielle n'existe qu'en Suivre × Berry.
    assert.match(app, /officialEtaReady = Boolean\(suivreBerry && official\.clock\)/);
    assert.match(app, /officialNowMs\(official\.clock,\s*official\.live\)/);
    assert.match(app, /officialEta: officialEtaReady/);
    // Hors Suivre × Berry, nowMs / liveFilmNm viennent du tracé.
    assert.match(app, /legendNowAndLive\(/);
    assert.match(app, /liveFilmNm: legendLiveFilmNm/);
    assert.match(app, /liveFilmNm=\{legendLiveFilmNm\}/);
    assert.doesNotMatch(app, /liveFilmNm=\{official\.live\?\.filmNm\}/);
    assert.match(app, /\(suivreBerry \? official\.clock\?\.marks : null\) \|\| voyage\.clock\?\.marks \|\| \[\]/);
    assert.match(app, /datedLegend \? legendMarks : \(officialClock\.marks \|\| legendMarks\)/);
  });

  it("LegendNowAndLive : Tracer ignore official.live (Papeete)", () => {
    const today = "2026-10-14T08:00:00.000Z";
    const officialNow = Date.parse("2026-09-19T12:00:00Z");
    const officialNm = 22000;
    const marks = [
      { name: "Saint-Maur (Berry, Indre)", iso: today, filmNm: 0 },
      { name: "La Rochelle", iso: "2026-10-14T12:00:00.000Z", filmNm: 122 },
      { name: "Papeete (Polynésie française)", iso: "2026-09-01T00:00:00Z", filmNm: officialNm },
      { name: "Nouméa (Nouvelle-Calédonie)", iso: "2026-11-01T00:00:00Z", filmNm: 30000 },
    ];
    const official = legendNowAndLive({
      suivreBerry: true,
      officialNowMs: officialNow,
      officialLiveNm: officialNm,
      sampleIso: today,
      sampleFilmNm: 0,
      playbackNm: 0,
    });
    assert.equal(nextStopFromMarks(marks, official.nowMs, official.liveFilmNm), "Nouméa (Nouvelle-Calédonie)");
    const trace = legendNowAndLive({
      suivreBerry: false,
      officialNowMs: officialNow,
      officialLiveNm: officialNm,
      sampleIso: today,
      sampleFilmNm: 0,
      playbackNm: 0,
    });
    assert.equal(nextStopFromMarks(marks, trace.nowMs, trace.liveFilmNm), "La Rochelle");
    assert.notEqual(nextStopFromMarks(marks, trace.nowMs, trace.liveFilmNm), "Papeete (Polynésie française)");
    assert.notEqual(nextStopFromMarks(marks, trace.nowMs, trace.liveFilmNm), "Nouméa (Nouvelle-Calédonie)");
  });
});

describe("usePlanReview — conseil", () => {
  it("écrit la phrase et les pastilles en FR et EN, sans anglais en FR", () => {
    const best = ADVICE_FIXTURE.best;
    const fr = formatAdviceSentence(best, tFr, "fr");
    const en = formatAdviceSentence(best, tEn, "en");
    assert.match(fr, /Partir de Nouméa/);
    assert.match(fr, /5 alertes au lieu de 11/);
    assert.match(fr, /\+41 nm/);
    assert.match(fr, /7 jours/);
    assert.doesNotMatch(fr, /\b(Leave|Instead|alerts instead)\b/);
    assert.match(en, /Leave Nouméa/);
    assert.match(en, /5 alerts instead of 11/);
    const pillsFr = formatAdvicePills(best, tFr);
    assert.equal(pillsFr.alerts, "11 → 5 alertes");
    assert.equal(pillsFr.nm, "+41 nm");
    assert.equal(pillsFr.days, "+7 j");
    const pillsEn = formatAdvicePills(best, tEn);
    assert.equal(pillsEn.alerts, "11 → 5 alerts");
  });

  it("écarte un texte rédigé anglais quand l'UI est FR", () => {
    const best = {
      ...ADVICE_FIXTURE.best,
      sentence: "Leave Nouméa rather than 1 Oct: 5 alerts instead of 11.",
      sentenceLang: "en",
    };
    const fr = localizeAdviceSentence(best, tFr, "fr");
    assert.match(fr, /Partir de Nouméa/);
    assert.doesNotMatch(fr, /Leave Nouméa/);
    const en = localizeAdviceSentence({ ...ADVICE_FIXTURE.best, sentenceLang: "fr" }, tEn, "en");
    assert.match(en, /Leave Nouméa/);
  });

  it("construit deux colonnes avec les dates d'escale décalées", () => {
    const compare = buildAdviceCompare(ADVICE_FIXTURE.best, { legNm: 6144, daysAtSea: 32 }, tFr, "fr");
    assert.match(compare.today.distance, /6144 nm/);
    assert.match(compare.advised.distance, /6185 nm/);
    assert.equal(compare.today.alerts, "11 alertes");
    assert.equal(compare.advised.alerts, "5 alertes");
    assert.ok(compare.today.stops.some((s) => /Dzaoudzi/.test(s)));
    assert.ok(compare.advised.stops.some((s) => /Dzaoudzi/.test(s)));
    assert.notEqual(compare.today.stops[0], compare.advised.stops[0]);
  });

  it("prend la jambe la plus chargée et sondé /advice?leg=", () => {
    assert.equal(pickHeaviestLegIdx([{ alertCount: 2 }, { alertCount: 11 }]), 1);
    const now = Date.parse("2026-07-01T00:00:00Z");
    const legs = [
      { alertCount: 2, departIso: "2026-08-01T08:00:00Z" },
      { alertCount: 11, departIso: "2026-06-01T08:00:00Z" },
      { alertCount: 5, departIso: "2026-09-01T08:00:00Z" },
    ];
    assert.equal(pickHeaviestLegIdx(legs, now), 2, "la jambe déjà partie est ignorée");
    assert.equal(pickHeaviestLegIdx([{ alertCount: 9, departIso: "2026-06-01T08:00:00Z" }], now), -1);
    assert.equal(reviewAdviceKey({ legs: [{ from: "A", to: "B" }] }, -1), "");
    assert.equal(isAdviceDone(ADVICE_FIXTURE), true);
    assert.match(src, /\/voyage\/official\/advice\?/);
    assert.match(src, /pollOfficialAdvice/);
  });

  it("relance /advice tant que pending, puis garde le best", async () => {
    const pending = { status: "pending", leg: 0 };
    const done = ADVICE_FIXTURE;
    let n = 0;
    const seen = [];
    const ready = await pollOfficialAdvice(0, {
      fetchFn: async () => {
        n += 1;
        return n === 1 ? pending : done;
      },
      sleep: async () => {},
      onUpdate: (body) => seen.push(body),
      lang: "fr",
    });
    assert.equal(n, 2);
    assert.equal(ready.best.alertsAfter, 5);
    assert.equal(seen[0].status, "pending");
  });

  it("s'arrête après unavailable, sans re-sonde", async () => {
    const unavailable = { status: "unavailable", leg: 0, reason: "no_clock" };
    let n = 0;
    const seen = [];
    const ready = await pollOfficialAdvice(0, {
      fetchFn: async () => {
        n += 1;
        return unavailable;
      },
      sleep: async () => {
        throw new Error("ne doit pas relancer");
      },
      onUpdate: (body) => seen.push(body),
      lang: "fr",
    });
    assert.equal(isAdviceUnavailable(unavailable), true);
    assert.equal(isAdviceDone(unavailable), false);
    assert.equal(n, 1);
    assert.equal(ready.status, "unavailable");
    assert.equal(seen[0].reason, "no_clock");
  });

  it("garde la même clé tant que les jambes de la revue ne changent pas", () => {
    const a = { legs: [{ from: "Nouméa", to: "Dzaoudzi" }, { from: "Dzaoudzi", to: "Le Cap" }] };
    const b = { generatedAt: "2026-09-26T22:00:00Z", legs: [{ from: "Nouméa", to: "Dzaoudzi" }, { from: "Dzaoudzi", to: "Le Cap" }] };
    assert.equal(reviewAdviceKey(a, 0), reviewAdviceKey(b, 0));
    assert.notEqual(reviewAdviceKey(a, 0), reviewAdviceKey(a, 1));
    assert.equal(reviewAdviceKey({ source: "fixture", legs: a.legs }, 0), "");
    assert.equal(reviewAdviceKey({ legs: [] }, 0), "");
    assert.match(src, /reviewAdviceKey/);
    assert.match(src, /isAdviceUnavailable/);
  });
});

describe("Plus d'abort en vol", () => {
  it("démontage pendant une requête en vol : aucun abort du fetch, aucun update", async () => {
    let resolveFetch;
    const pending = new Promise((r) => { resolveFetch = r; });
    const fetchArgs = [];
    const seen = [];
    const full = {
      members: 40,
      p10: "2026-10-31T00:00:00Z",
      p50: "2026-11-02T00:00:00Z",
      p90: "2026-11-04T00:00:00Z",
    };
    const watch = startOfficialEtaWatch("Nouméa", {
      fetchFn: async (...args) => {
        fetchArgs.push(args);
        await pending;
        return full;
      },
      sleep: hangUntilAbort,
      onUpdate: (v) => seen.push(v),
    });
    await tick();
    watch.stop();
    resolveFetch();
    await watch.done;
    await tick();
    assert.equal(fetchArgs.length, 1);
    assert.equal(fetchArgs[0].length, 1);
    assert.equal(fetchArgs[0][0], "Nouméa");
    assert.equal(seen.length, 0);
    assert.equal(watch.alive, false);
  });

  it("briefing ICI : source règles locale, pas de warm/status global", () => {
    assert.match(sidebarSrc, /LlmSourceBadge/);
    assert.match(sidebarSrc, /ICI_BRIEFING_SOURCE/);
    assert.doesNotMatch(sidebarSrc, /startWarmStatusWatch/);
    assert.doesNotMatch(sidebarSrc, /lastSource/);
    assert.doesNotMatch(sidebarSrc, /\/ici\/warm\/status/);
  });

  it("changement de stopName : une seule boucle active", async () => {
    const fetches = [];
    const watchA = startOfficialEtaWatch("Nouméa", {
      fetchFn: async (name) => {
        fetches.push(name);
        return { members: 0 };
      },
      sleep: hangUntilAbort,
      onUpdate: () => {},
    });
    await tick();
    assert.deepEqual(fetches, ["Nouméa"]);
    watchA.stop();
    const watchB = startOfficialEtaWatch("Dzaoudzi", {
      fetchFn: async (name) => {
        fetches.push(name);
        return { members: 0 };
      },
      sleep: hangUntilAbort,
      onUpdate: () => {},
    });
    await tick();
    assert.deepEqual(fetches, ["Nouméa", "Dzaoudzi"]);
    await tick(40);
    assert.equal(fetches.filter((name) => name === "Nouméa").length, 1);
    assert.equal(fetches.filter((name) => name === "Dzaoudzi").length, 1);
    watchB.stop();
    await watchA.done;
    await watchB.done;
  });

  it("coupe l'attente entre sondes, pas une deuxième sonde", async () => {
    let n = 0;
    const watch = startOfficialEtaWatch("Nouméa", {
      fetchFn: async () => {
        n += 1;
        return { members: 0 };
      },
      sleep: hangUntilAbort,
      onUpdate: () => {},
    });
    await tick();
    assert.equal(n, 1);
    watch.stop();
    await watch.done;
    await tick();
    assert.equal(n, 1);
  });

  it("ne passe plus le signal d'arrêt au fetch /eta ni à plan-review", () => {
    assert.match(src, /startOfficialEtaWatch/);
    assert.match(src, /startWarmStatusWatch/);
    assert.doesNotMatch(src, /fetchFn\(stopName,\s*\{\s*signal/);
    assert.doesNotMatch(src, /fetchFn\(legIdx,\s*lang,\s*\{\s*signal/);
    assert.doesNotMatch(src, /\/voyage\/official\/plan-review`,\s*\{\s*signal/);
    assert.match(src, /fetch\(`\$\{API_URL\}\/voyage\/official\/plan-review`\)/);
  });
});

describe("usePlanReview — ETA gelée pendant le film", () => {
  const stops = ["La Rochelle", "Ajaccio", "Fort-de-France", "Nouméa", "Dzaoudzi"];

  it("ne re-sonde pas l'ETA tant que le film tourne, une sonde à l'arrêt", () => {
    assert.equal(countOfficialEtaPolls(stops, { frozen: true, officialClock: true }), 0);
    assert.equal(shouldPollOfficialEta({ frozen: true, enabled: true, stopName: "Nouméa", officialClock: true }), false);
    assert.equal(shouldPollOfficialEta({ frozen: false, enabled: true, stopName: "Nouméa", officialClock: true }), true);
    assert.equal(countOfficialEtaPolls(["Nouméa"], { frozen: false, officialClock: true }), 1);
    assert.equal(countOfficialEtaPolls(["Nouméa"], { frozen: false, officialClock: false }), 0);
    assert.match(src, /shouldPollOfficialEta/);
    assert.match(src, /frozen = false/);
  });
});
