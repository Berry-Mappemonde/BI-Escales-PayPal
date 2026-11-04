import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  datedMarks, dayMonth, expeditionStory, expeditionStoryText, storyConnector,
  FILM_CONNECTORS, FILM_MAX_CHARS, buildFilmScript, filmCandidates, selectFilmEvents,
  normStop, officialDatedStops,
} from "./expeditionStory.js";
import { NM_TO_KM } from "../utils/berryLegs.js";

const clock = { t0: "2026-05-15T08:00:00Z" };
const marks = [
  { name: "Saint-Maur (Berry, Indre)", nm: 0, filmNm: 0, iso: "2026-05-15T08:00:00Z", holdHours: 0 },
  { name: "La Rochelle", nm: 0, filmNm: 122, iso: "2026-05-15T12:00:00Z", holdHours: 72 },
  { name: "Ajaccio (Corse)", nm: 1820, filmNm: 1942, iso: "2026-05-24T12:51:00Z", holdHours: 72 },
  { name: "Fort-de-France (Martinique)", nm: 6973, filmNm: 7095, iso: "2026-06-23T08:34:00Z", holdHours: 72 },
  { name: "Nouméa (Nouvelle-Calédonie)", nm: 19055, filmNm: 19177, iso: "2026-09-17T22:48:00Z", holdHours: 72 },
  { name: "Dzaoudzi (Mayotte)", nm: 28206, filmNm: 28328, iso: "2026-11-02T02:41:00Z", holdHours: 72 },
];
const now = Date.parse("2026-09-19T02:00:00Z");
const plain = (s) => s.replace(/[\u202f\u00a0]/g, " ");

describe("expeditionStory — chronologique, jambe par jambe", () => {
  it("départ, puis chaque jambe (départ, traversée, arrivée, quai), puis la jambe en cours et aujourd’hui", () => {
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main", kind: "forecast", windKnots: 12.4, dirFromDeg: 135, model: "GFS" };
    const leg = { fromStop: "Nouméa (Nouvelle-Calédonie)", toStop: "Dzaoudzi (Mayotte)", remainingNm: 9100, etaHours: 44 * 24 };
    const journal = { latest: [
      { kind: "grib", t: "2026-05-20T06:00:00Z", windKnots: 10, dirFromDeg: 270, model: "GFS" },
      { kind: "grib", t: "2026-05-22T06:00:00Z", windKnots: 18, dirFromDeg: 300, model: "GFS" },
      { kind: "note", t: "2026-05-21T10:00:00Z", text: "Première nuit au large, belle étoile." },
      { kind: "zee", t: "2026-05-16T09:00:00Z", event: "exit", name: "French Exclusive Economic Zone", mrgid: 5677 },
      { kind: "zee", t: "2026-05-17T15:00:00Z", event: "enter", name: "Spanish Exclusive Economic Zone", mrgid: 5693 },
      { kind: "zee", t: "2026-05-18T01:00:00Z", event: "exit", name: "Spanish Exclusive Economic Zone", mrgid: 5693 },
      { kind: "zee", t: "2026-05-18T09:00:00Z", event: "enter", name: "Spanish Exclusive Economic Zone", mrgid: 5693 },
      { kind: "amp", t: "2026-05-18T02:00:00Z", event: "nearby", name: "Cabrera", nm: 8 },
      { kind: "poe", t: "2026-05-15T12:00:00Z", event: "passed", name: "La Rochelle - La Pallice", poeId: "lr", nm: 1.6 },
      { kind: "poe", t: "2026-05-15T12:30:00Z", event: "passed", name: "La Rochelle - La Pallice", poeId: "lr", nm: 3 },
      { kind: "wx", t: "2026-05-22T06:00:00Z", event: "gale", windKnots: 36.5, dirFromDeg: 300, hs: 2.4 },
      { kind: "grib", t: "2026-09-18T06:00:00Z", windKnots: 14, dirFromDeg: 120, model: "GFS" },
    ] };
    const paras = expeditionStory({ clock, marks, live, leg, journal, now, lang: "fr" }).map(plain);
    const landKm = Math.round(122 * NM_TO_KM);
    assert.equal(paras[0], "L’expédition Berry-Mappemonde a quitté Saint-Maur le 15 mai 2026.");
    assert.equal(paras[1], `Puis, le 15 mai, départ vers La Rochelle : ${landKm} km par la route en 4 h de route. Arrivée à La Rochelle le 15 mai, 3 jours à quai.`);
    assert.equal(paras[2], "Le 15 mai, le bateau a pris la mer à La Rochelle, vers Ajaccio (Corse) : 1 820 nm en 9 jours. "
      + "Entre-temps — entré dans : les eaux espagnoles le 17 mai ; aire marine protégée à portée : Cabrera ; port d’entrée passé : La Rochelle - La Pallice. "
      + "Météo au bateau : coup de vent le 22 mai (37 kn, Hs 2,4 m) (GFS). "
      + "Vent au bateau : 14 kn en moyenne, 18 kn au plus fort (GFS, 2 relevés). "
      + "Le skipper a noté : « Première nuit au large, belle étoile. » "
      + "Arrivée à Ajaccio (Corse) le 24 mai, 3 jours à quai.");
    assert.equal(paras[3], "Ensuite, le 27 mai, départ vers Fort-de-France (Martinique) : 5 153 nm en 27 jours. Arrivée à Fort-de-France (Martinique) le 23 juin, 3 jours à quai.");
    assert.equal(paras[4], "Plus loin, le 26 juin, départ vers Nouméa (Nouvelle-Calédonie) : 12 082 nm en 84 jours. Arrivée à Nouméa (Nouvelle-Calédonie) le 17 septembre, 3 jours à quai.");
    assert.equal(paras[5], "Depuis le 20 septembre, en route de Nouméa (Nouvelle-Calédonie) vers Dzaoudzi (Mayotte) : encore 9 100 nm, arrivée prévue le 2 novembre.");
    assert.equal(paras[6], "Aujourd’hui, jour 126 (94 de mer) : le bateau est à 19 260 nm du départ.");
    assert.equal(paras[7], "Au bateau maintenant : vent 12 kn de SE (prévision GFS).");
    assert.equal(paras.length, 8);
    assert.equal(expeditionStoryText({ clock, marks, live, leg, journal, now }).split("\n\n").length, 8);
  });

  it("le paragraphe en cours suit la jambe de l'horloge, pas la jambe de départ", () => {
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
    const nowLeg = { fromStop: "Nouméa (Nouvelle-Calédonie)", toStop: "Dzaoudzi (Mayotte)", remainingNm: 9100 };
    const departure = { fromStop: "La Rochelle", toStop: "Ajaccio (Corse)", remainingNm: 1453 };
    const atNow = expeditionStory({ clock, marks, live, leg: nowLeg, now, lang: "fr" }).map(plain);
    const atCursor = expeditionStory({ clock, marks, live, leg: departure, now, lang: "fr" }).map(plain);
    const enRoute = atNow.find((p) => /en route/.test(p));
    const cursorRoute = atCursor.find((p) => /en route/.test(p));
    assert.match(enRoute, /Dzaoudzi \(Mayotte\)/);
    assert.doesNotMatch(enRoute, /Ajaccio/);
    assert.match(cursorRoute, /Ajaccio/);
    assert.notEqual(enRoute, cursorRoute);
  });

  it("deux paragraphes consécutifs n’ont pas le même connecteur", () => {
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
    const paras = expeditionStory({ clock, marks, live, now, lang: "fr" });
    const cons = FILM_CONNECTORS.fr;
    const used = [];
    for (const p of paras) {
      const hit = cons.find((c) => p.startsWith(`${c},`));
      if (hit) used.push(hit);
    }
    assert.ok(used.length >= 2, `connecteurs trouvés : ${used.join(" | ")}`);
    for (let i = 1; i < used.length; i++) {
      assert.notEqual(used[i], used[i - 1], `connecteur répété : ${used[i]}`);
    }
    assert.equal(storyConnector(0, "fr"), "Puis");
    assert.equal(storyConnector(1, "fr"), "Ensuite");
    assert.equal(storyConnector(6, "fr"), "Puis");
  });

  it("ne recolle pas la Corse sur les Açores", () => {
    const acores = [
      { name: "La Rochelle", nm: 0, filmNm: 0, iso: "2026-05-15T08:00:00Z", holdHours: 0 },
      { name: "Açores (Corse)", nm: 1100, filmNm: 1100, iso: "2026-05-22T08:00:00Z", holdHours: 24 },
    ];
    const later = Date.parse("2026-06-01T00:00:00Z");
    const frText = expeditionStory({ clock, marks: acores, live: null, now: later, lang: "fr" }).map(plain).join(" ");
    const enText = expeditionStory({ clock, marks: acores, live: null, now: later, lang: "en" }).map(plain).join(" ");
    assert.match(frText, /Açores/);
    assert.match(enText, /Açores/);
    assert.doesNotMatch(frText, /Corse|Corsica/);
    assert.doesNotMatch(enText, /Corse|Corsica/);
  });

  it("étape terrestre : km par la route, pas de nm", () => {
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
    const paras = expeditionStory({ clock, marks, live, now, lang: "fr" }).map(plain);
    const land = paras.find((p) => /départ vers La Rochelle/.test(p));
    assert.ok(land, "paragraphe terrestre Saint-Maur → La Rochelle");
    assert.match(land, /\bkm\b/);
    assert.match(land, /par la route/);
    assert.match(land, /h de route/);
    assert.doesNotMatch(land, /\bnm\b/);
    const km = Math.round(122 * NM_TO_KM);
    assert.match(land, new RegExp(`${km} km`));
  });

  it("anglais, à quai, vent du journal quand le GRIB live manque", () => {
    const live = { filmNm: 19177, sailNm: 19055, seaHours: 94 * 24, status: "live", vehicle: "quay", atQuay: true, kind: "absent" };
    const leg = { fromStop: "Nouméa (Nouvelle-Calédonie)", toStop: "Dzaoudzi (Mayotte)", remainingNm: 9151 };
    const journal = { latest: [
      { kind: "position", t: "2026-09-18T12:00:00Z" },
      { kind: "grib", t: "2026-09-18T06:00:00Z", windKnots: 17.6, dirFromDeg: 90, model: "GFS" },
      { kind: "grib", t: "2026-09-17T06:00:00Z", windKnots: 9, dirFromDeg: 45, model: "GFS" },
    ] };
    const paras = expeditionStory({ clock, marks, live, leg, journal, now, lang: "en" }).map(plain);
    assert.equal(paras[0], "The Berry-Mappemonde expedition left Saint-Maur on 15 May 2026.");
    assert.match(paras[1], /^Then, on 15 May, departure for La Rochelle : \d+ km by road in 4 h on the road/);
    assert.doesNotMatch(paras[1], /\bnm\b/);
    assert.match(paras[2], /^On 15 May, the boat put to sea at La Rochelle, bound for Ajaccio \(Corse\) : 1,820 nm in 9 days\. Arrival at Ajaccio \(Corse\) on 24 May, 3 days in port\.$/);
    assert.match(paras[3], /^Next, on 27 May, departure for Fort-de-France/);
    assert.equal(paras[5], "Today, day 126 (94 at sea): the boat is in port at Nouméa (Nouvelle-Calédonie), 19,055 nm from the start; next leg to Dzaoudzi (Mayotte), expected on 2 November.");
    assert.equal(paras[6], "On 18 September, at the boat: wind 18 kn from the E (GFS forecast).");
  });

  it("avant le départ : une seule phrase, au futur", () => {
    const paras = expeditionStory({ clock, marks, live: null, leg: null, now: Date.parse("2026-05-01T00:00:00Z"), lang: "fr" });
    assert.deepEqual(paras, ["L’expédition Berry-Mappemonde quitte Saint-Maur le 15 mai 2026 et prend la mer à La Rochelle."]);
  });

  it("sans horloge ni escales : rien ; sans live : départ + jambes franchies seulement", () => {
    assert.deepEqual(expeditionStory({ now }), []);
    const paras = expeditionStory({ clock, marks, live: null, now, lang: "fr" });
    assert.equal(paras.length, 5);
    assert.match(paras[4], /Nouméa/);
  });

  it("datedMarks dédoublonne et trie ; dayMonth écrit 1er en français", () => {
    const d = datedMarks([...marks, { name: "La Rochelle", filmNm: 122.2, iso: "2026-05-15T12:00:00Z" }, { name: "Sans date", filmNm: 5 }]);
    assert.equal(d.length, marks.length);
    assert.equal(dayMonth("2026-06-01T10:00:00Z", "fr"), "1er juin");
    assert.equal(dayMonth("2026-06-01T10:00:00Z", "en"), "1 June");
    assert.equal(dayMonth("bad"), "");
  });

  it("datedMarks fusionne Ajaccio et Ajaccio (Corse) ; une escale n’est pas citée deux fois", () => {
    const d = datedMarks([
      ...marks,
      { name: "Ajaccio", filmNm: 1942.3, iso: "2026-05-24T13:00:00Z", holdHours: 72 },
      { name: "Ajaccio (Corse)", filmNm: 9000, iso: "2026-07-01T00:00:00Z", holdHours: 0 },
    ]);
    assert.equal(d.filter((s) => /ajaccio/i.test(s.name)).length, 1);
    assert.equal(normStop("Ajaccio (Corse)"), "ajaccio");
    assert.equal(normStop("Fort-de-France (Martinique)"), "fort-de-france");
  });

  it("datedMarks ne fusionne que sameStop (Saint-Maur et La Rochelle à filmNm 0 restent)", () => {
    const d = datedMarks([
      { name: "Saint-Maur (Berry, Indre)", nm: 0, filmNm: 0, iso: "2026-05-15T08:00:00Z" },
      { name: "La Rochelle", nm: 0, filmNm: 0, iso: "2026-05-15T08:00:00Z" },
      { name: "Ajaccio (Corse)", nm: 1820, filmNm: 1942, iso: "2026-05-24T12:51:00Z" },
    ]);
    assert.ok(d.some((s) => normStop(s.name) === "saint-maur"));
    assert.ok(d.some((s) => /rochelle/i.test(s.name)));
    assert.ok(d.some((s) => /ajaccio/i.test(s.name)));
  });
});

const ROUTE_STOPS = ["Saint-Maur", "La Rochelle", "Ajaccio", "Fort-de-France", "Nouméa", "Dzaoudzi"];

function firstIndex(text, needle) {
  return String(text).search(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
}

function assertRouteOrder(text, label) {
  const hits = ROUTE_STOPS.map((n) => ({ n, i: firstIndex(text, n) })).filter((h) => h.i >= 0);
  assert.ok(hits.length >= 4, `${label} : escales manquantes (${hits.map((h) => h.n).join(", ")})`);
  for (let i = 1; i < hits.length; i++) {
    assert.ok(hits[i - 1].i < hits[i].i, `${label} : ${hits[i].n} avant ${hits[i - 1].n}`);
  }
}

function assertDepartureArrivalPairs(text, lang = "fr") {
  const depRe = lang === "en" ? /departure for (.+?)(?:\s*:|\.|$)/gi : /départ vers (.+?)(?:\s*:|\.|$)/gi;
  const arrRe = lang === "en" ? /Arrival at (.+?) on /gi : /Arrivée à (.+?) le /gi;
  const deps = [...String(text).matchAll(depRe)].map((m) => ({ name: m[1].trim(), i: m.index }));
  const arrs = [...String(text).matchAll(arrRe)].map((m) => ({ name: m[1].trim(), i: m.index }));
  assert.ok(deps.length >= 2, `départs vers : ${deps.map((d) => d.name).join(" | ")}`);
  assert.ok(arrs.length >= 2, `arrivées : ${arrs.map((a) => a.name).join(" | ")}`);
  const seenArr = [];
  for (const a of arrs) {
    const key = normStop(a.name);
    assert.ok(!seenArr.includes(key), `escale répétée : ${a.name}`);
    seenArr.push(key);
  }
  for (const d of deps) {
    const next = arrs.find((a) => a.i > d.i);
    assert.ok(next, `pas d’arrivée après départ vers ${d.name}`);
    assert.equal(normStop(next.name), normStop(d.name), `départ vers ${d.name} suivi de arrivée à ${next.name}`);
  }
  assert.doesNotMatch(text, /départ vers Fort-de-France[\s\S]{0,240}(?:Escale à|Arrivée à) Ajaccio/i);
  assert.doesNotMatch(text, /departure for Fort-de-France[\s\S]{0,240}(?:Stopover in|Arrival at) Ajaccio/i);
}

function filmFixture() {
  const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
  const journal = { latest: [
    { id: "zee:es", kind: "zee", t: "2026-05-17T15:00:00Z", event: "enter", name: "Spanish Exclusive Economic Zone", mrgid: 5693 },
    { id: "amp:cabrera", kind: "amp", t: "2026-05-18T02:00:00Z", event: "nearby", name: "Cabrera", nm: 8 },
    { id: "poe:lr", kind: "poe", t: "2026-05-15T12:00:00Z", event: "passed", name: "La Rochelle - La Pallice", poeId: "lr", nm: 1.6 },
    { id: "wx:gale", kind: "wx", t: "2026-05-22T06:00:00Z", event: "gale", windKnots: 36.5, maxWindKnots: 38, hours: 6, dirFromDeg: 300, hs: 2.4 },
    { id: "climo:rose", kind: "climo", t: "2026-06-02T12:00:00Z", event: "rose", facts: { deltaDeg: 120 }, name: "alizés" },
    { id: "sci:pirata", kind: "sci", t: "2026-06-10T06:00:00Z", name: "PIRATA", facts: { nm: 6, name: "PIRATA" } },
    { id: "wx:sea", kind: "wx", t: "2026-07-01T06:00:00Z", event: "sea", windKnots: 22, maxHs: 4.2, hours: 12, hs: 4.2 },
    { id: "note:1", kind: "note", t: "2026-05-21T10:00:00Z", text: "Première nuit au large." },
    { id: "zee:fr", kind: "zee", t: "2026-05-16T09:00:00Z", event: "enter", name: "French Exclusive Economic Zone", mrgid: 5677 },
    { id: "amp:pertuis", kind: "amp", t: "2026-05-15T18:00:00Z", event: "nearby", name: "Pertuis Charentais", nm: 3 },
    { id: "poe:aj", kind: "poe", t: "2026-05-24T12:00:00Z", event: "passed", name: "Ajaccio", poeId: "aj" },
    { id: "sci:argo", kind: "sci", t: "2026-08-01T06:00:00Z", name: "Argo", facts: { nm: 4 } },
  ] };
  return { clock, marks, live, journal, now: Date.parse("2026-09-19T02:00:00Z") };
}

describe("expeditionStory — script du film", () => {
  it("brut ≤ 2 400 caractères, Saint-Maur et La Rochelle au chapitre 1", () => {
    const plan = buildFilmScript({ ...filmFixture(), lang: "fr", seconds: 150 });
    assert.ok(plan.chapters.length >= 1);
    assert.ok(plan.chars <= FILM_MAX_CHARS, `chars=${plan.chars}`);
    assert.equal(plan.source, "rules");
    assert.match(plan.chapters[0].text, /Saint-Maur/);
    assert.match(plan.chapters[0].text, /La Rochelle/);
    const again = buildFilmScript({ ...filmFixture(), lang: "fr", seconds: 150 });
    assert.deepEqual(again.chapters.map((c) => c.text), plan.chapters.map((c) => c.text));
  });

  it("lang=en : chapitre 1 anglais (left / departed, Saint-Maur, La Rochelle)", () => {
    const plan = buildFilmScript({ ...filmFixture(), lang: "en", seconds: 150 });
    assert.ok(plan.chapters.length >= 1);
    const text = plan.chapters[0].text;
    assert.match(text, /Saint-Maur/);
    assert.match(text, /La Rochelle/);
    assert.match(text, /left|departed/i);
    assert.doesNotMatch(text, /quitté|a pris la route/);
  });

  it("connecteurs jamais deux fois de suite", () => {
    const plan = buildFilmScript({ ...filmFixture(), lang: "fr" });
    const cons = FILM_CONNECTORS.fr;
    const used = [];
    for (let i = 1; i < plan.chapters.length; i++) {
      const hit = cons.find((c) => plan.chapters[i].text.startsWith(`${c},`));
      if (hit) used.push(hit);
    }
    assert.ok(used.length >= 2, "il faut au moins deux jambes avec connecteur");
    for (let i = 1; i < used.length; i++) {
      assert.notEqual(used[i], used[i - 1], `connecteur répété : ${used[i]}`);
    }
  });

  it("événements ancrés à un charIdx valide", () => {
    const plan = buildFilmScript({ ...filmFixture(), lang: "fr" });
    let anchored = 0;
    for (const ch of plan.chapters) {
      for (const ev of ch.events || []) {
        assert.ok(Number.isFinite(ev.charIdx) && ev.charIdx >= 0 && ev.charIdx < ch.text.length, ev.id);
        assert.ok(ch.text.slice(ev.charIdx).trim().length > 0, ev.id);
        anchored += 1;
      }
    }
    assert.ok(anchored >= 3, `ancrés=${anchored}`);
  });

  it("sélection déterministe : départ, escales, aujourd'hui, puis score", () => {
    const fx = filmFixture();
    const { candidates, t0, tEnd } = filmCandidates(fx);
    const a = selectFilmEvents(candidates, { t0, tEnd }).map((e) => e.id);
    const b = selectFilmEvents(candidates, { t0, tEnd }).map((e) => e.id);
    assert.deepEqual(a, b);
    assert.ok(a.includes("depart") && a.includes("today"));
    assert.ok(a.length >= 6 && a.length <= 9);
    const wx = a.filter((id) => String(id).startsWith("wx"));
    assert.ok(wx.length >= 1, "un coup de vent est retenu");
  });

  it("tête du récit : Saint-Maur le 15 mai 2026 même avec une horloge de simulation", () => {
    const simClock = { t0: "2027-04-25T08:00:00Z" };
    const simMarks = [
      { name: "La Rochelle", nm: 0, filmNm: 122, iso: "2027-04-25T08:00:00Z", holdHours: 72 },
      { name: "Ajaccio (Corse)", nm: 1820, filmNm: 1942, iso: "2027-05-04T12:00:00Z", holdHours: 72 },
      { name: "Fort-de-France (Martinique)", nm: 6973, filmNm: 7095, iso: "2027-06-02T08:00:00Z", holdHours: 72 },
    ];
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
    const paras = expeditionStory({ clock: simClock, marks: simMarks, live, now, lang: "fr" }).map(plain);
    assert.match(paras[0], /Saint-Maur/);
    assert.match(paras[0], /15 mai 2026/);
    assert.doesNotMatch(paras[0], /2027/);
    assert.doesNotMatch(paras[0], /a quitté La Rochelle/i);
    const stops = officialDatedStops(simMarks, simClock);
    assert.match(stops[0].name, /Saint-Maur/i);
    assert.match(stops[0].iso, /^2026-05-15/);
  });

  it("script du film : pas de nm nu, unités en toutes lettres", () => {
    const filmFr = buildFilmScript({ ...filmFixture(), lang: "fr" });
    const filmEn = buildFilmScript({ ...filmFixture(), lang: "en" });
    const blobFr = filmFr.chapters.map((c) => c.text).join(" ");
    const blobEn = filmEn.chapters.map((c) => c.text).join(" ");
    assert.match(filmFr.chapters[0].text, /Saint-Maur/);
    assert.match(filmFr.chapters[0].text, /15 mai 2026/);
    assert.doesNotMatch(blobFr, /\bnm\b/);
    assert.doesNotMatch(blobEn, /\bnm\b/);
    const simFilm = buildFilmScript({
      clock: { t0: "2027-04-25T08:00:00Z" },
      marks: [
        { name: "La Rochelle", nm: 0, filmNm: 122, iso: "2027-04-25T08:00:00Z", holdHours: 72, lat: 46.15, lon: -1.16 },
        { name: "Ajaccio (Corse)", nm: 1820, filmNm: 1942, iso: "2027-05-04T12:00:00Z", holdHours: 72, lat: 41.9, lon: 8.7 },
      ],
      live: { filmNm: 19400, sailNm: 19260, iso: "2026-09-19T02:00:00Z", status: "live" },
      now: Date.parse("2026-09-19T02:00:00Z"),
      lang: "fr",
    });
    assert.match(simFilm.chapters[0].text, /Saint-Maur/);
    assert.match(simFilm.chapters[0].text, /15 mai 2026/);
    assert.doesNotMatch(simFilm.chapters[0].text, /2027/);
    assert.doesNotMatch(simFilm.chapters.map((c) => c.text).join(" "), /\bnm\b/);
  });

  it("T0 replay 2025 décale le texte, t0 absent reste 2026", () => {
    const fx = filmFixture();
    const official = buildFilmScript({ ...fx, lang: "fr" });
    assert.match(official.chapters[0].text, /15 mai 2026/);
    const shifted = buildFilmScript({ ...fx, lang: "fr", t0: "2025-05-15T08:00:00.000Z" });
    assert.match(shifted.chapters[0].text, /15 mai 2025/);
    assert.doesNotMatch(shifted.chapters[0].text, /15 mai 2026/);
    const story = expeditionStory({ clock, marks, live: fx.live, now, lang: "fr", t0: "2025-05-15T08:00:00.000Z" });
    assert.match(story[0], /15 mai 2025/);
  });

  it("voyage officiel : ordre de la route, sans répétition, départ vers X puis arrivée à X (FR et EN)", () => {
    const live = { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live", vehicle: "main" };
    const storyFr = expeditionStory({ clock, marks, live, now, lang: "fr" }).map(plain).join(" ");
    const storyEn = expeditionStory({ clock, marks, live, now, lang: "en" }).map(plain).join(" ");
    assertRouteOrder(storyFr, "récit FR");
    assertRouteOrder(storyEn, "récit EN");
    assertDepartureArrivalPairs(storyFr, "fr");
    assertDepartureArrivalPairs(storyEn, "en");

    const filmFr = buildFilmScript({ ...filmFixture(), lang: "fr" });
    const filmEn = buildFilmScript({ ...filmFixture(), lang: "en" });
    const blobFr = filmFr.chapters.map((c) => c.text).join(" ");
    const blobEn = filmEn.chapters.map((c) => c.text).join(" ");
    assertRouteOrder(blobFr, "film FR");
    assertRouteOrder(blobEn, "film EN");
    assertDepartureArrivalPairs(blobFr, "fr");
    assertDepartureArrivalPairs(blobEn, "en");
    for (const ch of filmFr.chapters) {
      const dep = ch.text.match(/départ vers (.+?)(?:\s*:|\.|$)/i);
      const arr = ch.text.match(/Arrivée à (.+?) le /i);
      if (dep && arr) assert.equal(normStop(dep[1]), normStop(arr[1]), ch.id);
    }
  });

  it("horloge live-like : Arrivée à La Rochelle avant départ vers Ajaccio", () => {
    const t0 = "2026-05-15T08:00:00Z";
    const variants = [
      { name: "La Rochelle", nm: 0, filmNm: 0, iso: t0, holdHours: 72, lat: 46.15, lon: -1.16 },
      { name: "La Rochelle", nm: 0, filmNm: 122, iso: t0, holdHours: 72, lat: 46.15, lon: -1.16 },
    ];
    for (const lr of variants) {
      const liveMarks = [
        { name: "Saint-Maur (Berry, Indre)", nm: 0, filmNm: 0, iso: t0, holdHours: 0 },
        lr,
        ...marks.slice(2),
      ];
      const plan = buildFilmScript({
        clock: { t0, marks: liveMarks },
        marks: liveMarks,
        live: { filmNm: 19400, sailNm: 19260, seaHours: 94 * 24, iso: "2026-09-19T02:00:00Z", status: "live" },
        journal: filmFixture().journal,
        now: Date.parse("2026-09-19T02:00:00Z"),
        lang: "fr",
      });
      const blob = plan.chapters.map((c) => c.text).join(" ");
      const iArr = blob.indexOf("Arrivée à La Rochelle");
      const iAj = blob.search(/départ vers Ajaccio/i);
      assert.ok(iArr >= 0, `Arrivée à La Rochelle manquante (filmNm=${lr.filmNm})`);
      assert.ok(iAj >= 0, "départ vers Ajaccio manquant");
      assert.ok(iArr < iAj, blob.slice(0, 500));
      assert.match(plan.chapters[0].text, /départ vers La Rochelle/i);
      assert.match(plan.chapters[0].text, /Arrivée à La Rochelle/);
      assert.doesNotMatch(blob, /vers La Rochelle[^.]*\.\s*Arrivée à Ajaccio/);
      for (const ch of plan.chapters) {
        const tA = Date.parse(ch.tA);
        const tB = Date.parse(ch.tB);
        assert.ok(tB > tA, `${ch.id} tB<=tA ${ch.tA} ${ch.tB}`);
      }
    }
  });
});
