import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  advance, calibrateRate, cardDwellMs, measuredCps, voiceLedStep, cardFromJournalEntry, cardsBetween, chapterAtElapsed, chapterAnchors, filmChaptersFromStory, filmPlan, FILM_RATE_MAX, FILM_RATE_MIN, FILM_VOICE_LOOKAHEAD_CHARS, FILM_V_MAX_PX_S, FILM_V_MIN_PX_S, journalTimeline, positionAt, replayProgress, replaySample, replayScale, replayWindow, sentenceStartsFromText, stepFilmTime, trimQueue, voiceShouldWait, windFromJournalAt,
} from "./replay.js";
const T0 = "2026-05-15T08:00:00.000Z";

it("rebuilds sentence anchors for the stale frozen English rules chapter", () => {
  const text = "On 15 May, Berry-Mappemonde leaves La Rochelle, heading southwest for Ajaccio (Corse). 1,820 miles, about twenty days at sea. Then, the boat passes near the marine protected area Lilleau-des-Niges, at five miles. Then, six miles away, project Côte À Côte. On 19 May, the boat skirts Galicia — Camariñas, Muxía. Then, the Strait of Gibraltar between Tanger and Algeciras. The next day, sardinia — Porto Torres. Arrival at Ajaccio (Corse) on 1 June.";
  const stale = [
    [0, "2026-05-15T08:00:01Z"], [96, "2026-05-15T11:00:00Z"], [180, "2026-05-15T11:00:00Z"],
    [279, "2026-05-15T11:00:00Z"], [303, "2026-05-15T11:00:00Z"], [370, "2026-05-15T11:00:00Z"],
    [418, "2026-05-15T11:00:00Z"], [499, "2026-05-15T11:00:00Z"], [561, "2026-05-19T00:00:00Z"],
    [649, "2026-05-24T00:00:00Z"], [661, "2026-05-24T00:00:00Z"], [663, "2026-05-24T00:00:00Z"],
    [679, "2026-05-26T00:00:00Z"], [688, "2026-06-01T00:00:00Z"], [738, "2026-06-01T22:13:28Z"],
    [746, "2026-06-01T22:13:28Z"], [756, "2026-06-01T22:13:28Z"],
  ].map(([charIdx, t]) => ({ charIdx, t }));
  const tA = Date.parse("2026-05-15T08:00:01Z");
  const tB = Date.parse("2026-06-01T22:13:28Z");
  const points = chapterAnchors({ tA, tB, text, anchors: stale });
  assert.deepEqual(points.map((p) => p.charIdx), [0, ...sentenceStartsFromText(text).slice(1), text.length]);
  assert.ok(points.every((p) => p.charIdx <= text.length));
  assert.ok(points.at(-1).t > points[0].t);
  let sameInstantRun = 1;
  const sentencePoints = points.slice(0, -1);
  for (let i = 1; i < sentencePoints.length; i += 1) {
    sameInstantRun = sentencePoints[i].t === sentencePoints[i - 1].t ? sameInstantRun + 1 : 1;
    assert.ok(sameInstantRun < 3, "no three sentence starts share one instant");
  }
});

/** A hand-made official clock: La Rochelle → 230 nm SW in 29 h → Ajaccio at 125 h, 3 days alongside. */
function clock() {
  const v = (tHours, filmNm, lat, lon, extra = {}) => ({
    tHours, filmNm, sailNm: filmNm, lat, lon, bearing: 240, speedKnots: 8, vehicle: "main", seaHours: tHours, kind: "climatology", windKnots: 11, ...extra,
  });
  return {
    t0: T0,
    vertices: [
      v(0, 0, 46.15, -1.16),
      v(29, 230, 44.0, -6.0),
      v(125, 1000, 41.9, 8.7),
      v(197, 1000, 41.9, 8.7, { vehicle: "quay", speedKnots: null }),
    ],
    marks: [
      { name: "La Rochelle", nm: 0, filmNm: 0, lat: 46.15, lon: -1.16, tHours: 0, holdHours: 0 },
      { name: "Ajaccio (Corse)", nm: 1000, filmNm: 1000, lat: 41.9, lon: 8.7, tHours: 125, holdHours: 72 },
    ],
  };
}

describe("replay — rejouer la route de Saint-Maur à aujourd'hui", () => {
  it("window runs from the official departure to now, never beyond; time advances at seconds-per-day", () => {
    const now = Date.parse("2026-05-25T08:00:00Z");
    const w = replayWindow({ t0: T0 }, now);
    assert.equal(w.days, 10);
    assert.equal(replayWindow({ t0: T0 }, Date.parse("2026-05-14T00:00:00Z")), null, "before departure: nothing to replay");
    // 1 s of wall clock = 1 day of expedition.
    const a = advance(w.startMs, 1000, w, 1);
    assert.equal(a.done, false);
    assert.equal(Math.round((a.tMs - w.startMs) / 3600000), 24);
    // Clamps at now and says so.
    const b = advance(w.startMs, 20_000, w, 1);
    assert.equal(b.done, true);
    assert.equal(b.tMs, w.endMs);
    assert.equal(replayProgress(a.tMs, w), 0.1);
    assert.ok(replayScale(2) > replayScale(1));
  });

  it("the sample at a replayed instant comes from the clock, dated, with the journaled wind when there is one", () => {
    const c = clock();
    const tl = journalTimeline({ latest: [
      { id: "grib:1", kind: "grib", t: "2026-05-16T06:00:00Z", windKnots: 14, dirFromDeg: 250, hs: 1.2, model: "GFS" },
      { id: "grib:1", kind: "grib", t: "2026-05-16T06:00:00Z", windKnots: 14 }, // duplicate dropped
    ] });
    assert.equal(tl.length, 1);
    const t = Date.parse("2026-05-16T07:00:00Z");
    const s = replaySample(c, t, tl);
    assert.ok(s && Number.isFinite(s.lat) && Number.isFinite(s.lon));
    assert.equal(s.iso, "2026-05-16T07:00:00.000Z");
    assert.equal(s.replay, true);
    assert.equal(s.kind, "forecast");
    assert.equal(s.windKnots, 14);
    // Five hours later, out of the 4 h window: the clock's typical wind, labelled so.
    const far = replaySample(c, Date.parse("2026-05-16T12:00:00Z"), tl);
    assert.equal(far.kind, "climatology");
    assert.equal(windFromJournalAt(tl, Date.parse("2026-05-20T00:00:00Z")), null);
  });

  it("journal lines become cards in order; positions and notes travel; grib and positions are not cards", () => {
    const tl = journalTimeline({ events: [
      { id: "zee:1", kind: "zee", t: "2026-05-15T20:00:00Z", event: "enter", name: "Spanish Exclusive Economic Zone", lat: 45.0, lon: -3.0 },
      { id: "poe:1", kind: "poe", t: "2026-05-15T09:00:00Z", event: "passed", name: "La Rochelle - La Pallice", nm: 1.6, lat: 46.16, lon: -1.22 },
      { id: "grib:1", kind: "grib", t: "2026-05-15T12:00:00Z", windKnots: 10 },
      { id: "position:x", kind: "position", t: "2026-05-15T12:00:00Z", lat: 46, lon: -2 },
      { id: "wx:1", kind: "wx", t: "2026-05-17T06:00:00Z", event: "gale", windKnots: 36, dirFromDeg: 250, hs: 2 },
      { id: "note:1", kind: "note", t: "2026-05-16T10:00:00Z", text: "Belle étoile.", author: "Clément" },
    ] });
    const cards = cardsBetween(tl, Date.parse("2026-05-15T08:00:00Z"), Date.parse("2026-05-16T12:00:00Z"), "fr");
    assert.deepEqual(cards.map((c) => c.kind), ["poe", "zee", "note"]);
    assert.equal(cards[0].title, "Port d’entrée · 15 mai");
    assert.equal(cards[0].text, "Port d’entrée passé : La Rochelle - La Pallice (1,6 nm)");
    assert.equal(cards[0].entity.kind, "poe");
    assert.equal(cards[2].text, "Clément : Belle étoile.");
    assert.equal(cards[2].entity, null);
    const gale = cardFromJournalEntry(tl.find((e) => e.kind === "wx"), "en");
    assert.equal(gale.severity, "alert");
    assert.match(gale.title, /Weather at the boat · 17 May/);
    assert.equal(cardFromJournalEntry({ kind: "grib", t: "2026-05-15T12:00:00Z" }), null);
    assert.equal(cardsBetween(tl, 0, 0).length, 0);
    // A ZEE exit is not a card (the next entry says it).
    const exits = journalTimeline({ events: [{ id: "zee:x", kind: "zee", t: "2026-05-15T21:00:00Z", event: "exit", name: "French EEZ" }] });
    assert.equal(cardsBetween(exits, 0, Date.parse("2026-05-16T00:00:00Z")).length, 0);
  });

  it("the queue never lags the boat: low-priority cards are dropped first, dwell shrinks with the backlog", () => {
    const mk = (kind, i) => ({ key: `${kind}:${i}`, kind });
    const q = [mk("poe", 1), mk("stop", 2), mk("zee", 3), mk("wx", 4), mk("poe", 5), mk("note", 6), mk("amp", 7)];
    const trimmed = trimQueue(q, 4);
    assert.equal(trimmed.length, 4);
    assert.deepEqual(trimmed.map((c) => c.kind), ["stop", "wx", "note", "amp"], "stops, weather and notes survive; ports of entry go first");
    assert.equal(trimQueue([mk("stop", 1)], 4).length, 1);
    assert.equal(cardDwellMs(0), 2500);
    assert.equal(cardDwellMs(1), 2500);
    assert.equal(cardDwellMs(5), 900);
  });
});

describe("replay — filmPlan", () => {
  it("répartit 150 s au prorata des caractères et timeAt est monotone", () => {
    const chapters = [
      { text: "aa", tA: 1_000, tB: 4_000 },
      { text: "bbbb", tA: 4_000, tB: 10_000 },
    ];
    const plan = filmPlan({ chapters, targetSeconds: 150 });
    assert.equal(plan.targetSeconds, 150);
    assert.ok(Math.abs(plan.chapters[0].seconds - 50) < 1e-9);
    assert.ok(Math.abs(plan.chapters[1].seconds - 100) < 1e-9);
    assert.ok(Math.abs(plan.chapters[0].seconds + plan.chapters[1].seconds - 150) < 1e-9);
    let prev = -Infinity;
    for (const ch of plan.chapters) {
      for (let c = 0; c <= ch.chars; c++) {
        const t = plan.timeAt(ch.idx, c);
        assert.ok(t >= prev - 1e-9, `timeAt(${ch.idx}, ${c}) = ${t} < ${prev}`);
        prev = t;
      }
    }
    assert.equal(plan.timeAt(0, 0), 1_000);
    assert.equal(plan.timeAt(0, 2), 4_000);
    assert.equal(plan.timeAt(1, 0), 4_000);
    assert.equal(plan.timeAt(1, 4), 10_000);
    const mid = chapterAtElapsed(plan, 50);
    assert.equal(mid.idx, 1);
    const squeezed = filmPlan({
      chapters: [
        { text: "x", tA: 1_000, tB: 2_000 },
        { text: "y".repeat(50), tA: 2_000, tB: 8_000 },
      ],
      targetSeconds: 150,
    });
    assert.equal(squeezed.chapters.length, 1, "un chapitre trop court est fusionné");
    assert.ok(squeezed.chapters[0].seconds >= 12);
  });

  it("2:30 ne fusionne plus les 15 chapitres du texte", () => {
    // Longueurs du film français 2:30 servi le 19 oct. (15 chapitres → 5 si fusion).
    const lengths = [117, 223, 202, 425, 138, 184, 83, 87, 179, 33, 221, 28, 56, 177, 270];
    const chapters = lengths.map((n, i) => ({
      text: "x".repeat(n),
      tA: 1_000_000 + i * 86_400_000,
      tB: 1_000_000 + (i + 1) * 86_400_000,
      fromName: `L${i}`,
      toName: `L${i + 1}`,
    }));
    const squeezed = filmPlan({ chapters, targetSeconds: 150 });
    assert.equal(squeezed.chapters.length, 5, "sans keepChapters, 2:30 fusionne 15 chapitres en 5");
    const kept = filmPlan({ chapters, targetSeconds: 150, keepChapters: true });
    assert.equal(kept.chapters.length, 15, "2:30 garde chaque chapitre du texte");
    assert.equal(kept.targetSeconds, 150);
    assert.equal(kept.chapters[0].text.length, 117);
    assert.equal(kept.chapters[9].text.length, 33);
    assert.equal(kept.chapters[14].text.length, 270);
    assert.equal(kept.chapters[0].fromName, "L0");
    assert.equal(kept.chapters[14].toName, "L15");
    const integral = filmPlan({ chapters, targetSeconds: 574, keepChapters: true });
    assert.equal(integral.chapters.length, 15, "l'intégral garde aussi chaque chapitre");
  });

  it("calibrage du rate borné dans [0,9 ; 1,25]", () => {
    assert.equal(calibrateRate({ chapterChars: 100, elapsedSeconds: 1, remainingChars: 10_000, remainingBudgetSeconds: 1 }), FILM_RATE_MAX);
    assert.equal(calibrateRate({ chapterChars: 100, elapsedSeconds: 100, remainingChars: 10, remainingBudgetSeconds: 100 }), FILM_RATE_MIN);
    const mid = calibrateRate({ chapterChars: 100, elapsedSeconds: 10, remainingChars: 200, remainingBudgetSeconds: 20 });
    assert.ok(mid >= FILM_RATE_MIN && mid <= FILM_RATE_MAX);
    assert.equal(calibrateRate({}), 1);
  });

  it("les chapitres sont les jambes du récit ; le premier texte dit Saint-Maur", () => {
    const t0 = "2026-05-15T08:00:00.000Z";
    const marks = [
      { name: "Saint-Maur (Berry, Indre)", iso: t0, filmNm: 0, lat: 46.8, lon: 1.7 },
      { name: "La Rochelle", iso: "2026-05-15T12:00:00.000Z", filmNm: 122, lat: 46.15, lon: -1.16 },
    ];
    const chapters = filmChaptersFromStory({
      clock: { t0, marks },
      marks,
      live: { iso: "2026-05-16T00:00:00.000Z", lat: 45, lon: -3, filmNm: 200, sailNm: 80 },
      lang: "fr",
    });
    assert.ok(chapters.length >= 1);
    assert.match(chapters[0].text, /Saint-Maur/);
    assert.ok(chapters[0].tB > chapters[0].tA);
    const plan = filmPlan({ chapters, targetSeconds: 150 });
    assert.ok(Math.abs(plan.chapters.reduce((s, c) => s + c.seconds, 0) - 150) < 1e-6);
  });

  it("positionAt(t) est continue aux sommets (limite gauche = limite droite)", () => {
    const c = clock();
    const mid = c.vertices[1];
    const t0 = Date.parse(c.t0);
    const tMid = t0 + mid.tHours * 3600000;
    const at = positionAt(c, tMid);
    const left = positionAt(c, tMid - 1);
    const right = positionAt(c, tMid + 1);
    assert.ok(at && left && right);
    assert.ok(Math.abs(at.lat - mid.lat) < 1e-9);
    assert.ok(Math.abs(at.lon - mid.lon) < 1e-9);
    assert.ok(Math.abs(left.lat - at.lat) < 1e-4);
    assert.ok(Math.abs(right.lat - at.lat) < 1e-4);
    assert.ok(Math.abs(left.lon - at.lon) < 1e-4);
    assert.ok(Math.abs(right.lon - at.lon) < 1e-4);
    const wrap = {
      t0: T0,
      vertices: [
        { tHours: 0, filmNm: 0, sailNm: 0, lat: 0, lon: 170 },
        { tHours: 10, filmNm: 600, sailNm: 600, lat: 0, lon: -170 },
      ],
    };
    const midWrap = positionAt(wrap, t0 + 5 * 3600000);
    assert.ok(midWrap.lon > 170, "lon dépliée : 170 → −170 passe par 180, pas par 0");
  });
});

describe("replay — ancres phrase → instant (27 sept.)", () => {
  const tA = Date.parse("2026-05-15T12:00:00Z");
  const tB = Date.parse("2026-06-01T09:00:00Z");
  const depart = Date.parse("2026-05-18T10:00:00Z");
  const approche = Date.parse("2026-05-31T18:00:00Z");
  const text = "À La Rochelle, 3 jours à quai. Puis, le 18 mai, départ vers Ajaccio. Le 31 mai, approche d’Ajaccio. Arrivée le 1er juin.";
  const chapter = {
    id: "leg-1", tA: new Date(tA).toISOString(), tB: new Date(tB).toISOString(), text,
    anchors: [
      { charIdx: 0, t: new Date(tA).toISOString() },
      { charIdx: text.indexOf("Puis"), t: new Date(depart).toISOString() },
      { charIdx: text.indexOf("Le 31"), t: new Date(approche).toISOString() },
      { charIdx: text.indexOf("Arrivée"), t: new Date(tB).toISOString() },
    ],
  };

  it("le bateau est là où la phrase le dit : « approche d’Ajaccio » = instant de l’approche", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    assert.equal(plan.timeAt(0, 0), tA);
    assert.equal(plan.timeAt(0, text.indexOf("Puis")), depart);
    assert.equal(plan.timeAt(0, text.indexOf("Le 31")), approche);
    assert.equal(plan.timeAt(0, ch.chars), tB);
    // pendant « 3 jours à quai » le bateau reste entre tA et le départ, pas au milieu de la jambe
    const midQuay = plan.timeAt(0, 10);
    assert.ok(midQuay >= tA && midQuay <= depart, "à quai avant le départ");
    // la correspondance est monotone : la voix avance, le bateau ne recule jamais
    let prev = -Infinity;
    for (let c = 0; c <= ch.chars; c += 3) {
      const t = plan.timeAt(0, c);
      assert.ok(t >= prev, `monotone à ${c}`);
      prev = t;
    }
  });

  it("sans ancres : linéaire ; ancres hors chronologie : rendues croissantes et bornées", () => {
    const lin = filmPlan({ chapters: [{ ...chapter, anchors: [] }], targetSeconds: 150 });
    const half = lin.timeAt(0, lin.chapters[0].chars / 2);
    assert.ok(Math.abs(half - (tA + tB) / 2) < 1000);
    const messy = filmPlan({
      chapters: [{
        ...chapter,
        anchors: [
          { charIdx: 40, t: "2026-07-01T00:00:00Z" }, // après tB → borné à tB
          { charIdx: 80, t: "2026-05-01T00:00:00Z" }, // avant tA et avant l'ancre précédente → remonté
        ],
      }],
      targetSeconds: 150,
    });
    const at40 = messy.timeAt(0, 40);
    const at80 = messy.timeAt(0, 80);
    assert.equal(at40, tB);
    assert.ok(at80 >= at40, "jamais de retour en arrière");
  });
});

describe("replay — le bateau suit la voix, jamais l'inverse (27 sept.)", () => {
  const tA = Date.parse("2026-05-15T12:00:00Z");
  const depart = Date.parse("2026-05-18T10:00:00Z");
  const tB = Date.parse("2026-06-01T09:00:00Z");
  const text = "Trois jours à quai à La Rochelle, stations et pétoncles. Puis, le 18 mai, départ vers Ajaccio. Arrivée le 1er juin.";
  const chapter = {
    id: "leg-1", tA: new Date(tA).toISOString(), tB: new Date(tB).toISOString(), text,
    anchors: [
      { charIdx: 0, t: new Date(tA).toISOString() },
      { charIdx: text.indexOf("Puis"), t: new Date(depart).toISOString() },
      { charIdx: text.indexOf("Arrivée"), t: new Date(tB).toISOString() },
    ],
  };

  it("pendant la phrase de quai, le bateau reste à quai même après plusieurs secondes sans nouveau mot", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    let t = ch.tA;
    // 6 s de frames à 60 Hz, la voix est au caractère 10 (« Trois jours à quai… »)
    for (let i = 0; i < 360; i += 1) {
      t = voiceLedStep({ t, dt: 1 / 60, chapter: ch, plan, chapterIdx: 0, charIdx: 10, cps: 15 }).t;
    }
    assert.ok(t <= plan.timeAt(0, 10) + 1, "jamais plus loin que le caractère dit");
    assert.ok(t < depart, "toujours avant le départ du 18 mai");
  });

  it("Le bateau suit le caractère dit, sans second lookahead de 12", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    const c = text.indexOf("Puis") + 5;
    let t = plan.timeAt(0, text.indexOf("Puis"));
    for (let i = 0; i < 120; i += 1) {
      t = voiceLedStep({ t, dt: 1 / 60, chapter: ch, plan, chapterIdx: 0, charIdx: c, cps: 15 }).t;
    }
    const spoken = plan.timeAt(0, c);
    const oldLead = plan.timeAt(0, c + FILM_VOICE_LOOKAHEAD_CHARS);
    assert.ok(t <= spoken + 1, "plafonné à la voix");
    assert.ok(t < oldLead, "ne reprend pas le double décalage");
  });

  it("measuredCps : défaut au début, puis mesuré et borné", () => {
    assert.equal(measuredCps(5, 500), 12);
    assert.equal(measuredCps(150, 10000), 15);
    assert.equal(measuredCps(400, 10000), 40);
    assert.equal(measuredCps(30, 10000), 6);
  });
});

describe("replay — vitesse continue (revue du 28 sept.)", () => {
  const tA = Date.parse("2026-05-29T00:00:00Z");
  const tB = tA + 26 * 86400000;
  const tQuay = tB + 3 * 86400000;
  const seaText = "À partir du 31 mai, onze stations scientifiques croisées sur la route atlantique.";
  const quayText = "Arrivée à Fort-de-France le 28 juin, 3 jours à quai.";
  const text = `${seaText} ${quayText}`;
  const seaClock = {
    t0: "2026-05-29T00:00:00.000Z",
    vertices: [
      { tHours: 0, filmNm: 0, sailNm: 0, lat: 41.9, lon: 8.7, bearing: 250 },
      { tHours: 26 * 24, filmNm: 5153, sailNm: 5153, lat: 14.6, lon: -61.07, bearing: 250 },
      { tHours: 26 * 24 + 72, filmNm: 5153, sailNm: 5153, lat: 14.6, lon: -61.07, bearing: 0 },
    ],
  };
  const chapter = {
    id: "leg-atl",
    tA: new Date(tA).toISOString(),
    tB: new Date(tQuay).toISOString(),
    text,
    fromLat: 41.9,
    fromLon: 8.7,
    toLat: 14.6,
    toLon: -61.07,
    anchors: [
      { charIdx: 0, t: new Date(tA).toISOString() },
      { charIdx: seaText.length, t: new Date(tB).toISOString() },
      { charIdx: text.length, t: new Date(tQuay).toISOString() },
    ],
  };

  it("pente continue aux ancres (Fritsch-Carlson) : dérivées gauche et droite proches", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    const x = seaText.length;
    const left = (plan.timeAt(0, x) - plan.timeAt(0, x - 0.2)) / 0.2;
    const right = (plan.timeAt(0, x + 0.2) - plan.timeAt(0, x)) / 0.2;
    const scale = Math.max(1, Math.abs(left), Math.abs(right));
    assert.ok(Math.abs(left - right) / scale < 0.2, `pentes ${left} vs ${right}`);
    assert.equal(plan.timeAt(0, 0), tA);
    assert.equal(plan.timeAt(0, x), tB);
  });

  it("frontières synthétiques : rapport max/min d'avance ≤ 1,5, aucune frame à l'arrêt hors escale, v dans les bornes", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    const dt = 1 / 60;
    const wordEvery = 6;
    const wordS = 0.375;
    const cps = 16;
    let t = ch.tA;
    let charIdx = 0;
    let lastB = 0;
    let since = 0;
    let recale = 0;
    const advances = [];
    const speeds = [];
    const frames = Math.round(5 / dt);
    for (let i = 0; i < frames; i += 1) {
      const wall = i * dt;
      const wordIdx = Math.floor(wall / wordS);
      const prevWord = Math.floor((wall - dt) / wordS);
      if (i > 0 && wordIdx !== prevWord) {
        charIdx = Math.min(seaText.length - 2, wordIdx * wordEvery);
        lastB = charIdx;
        since = 0;
        recale = 300;
      } else {
        since += dt;
      }
      const step = stepFilmTime({
        t,
        dt,
        chapter: ch,
        plan,
        chapterIdx: 0,
        charIdx,
        cps,
        lookahead: FILM_VOICE_LOOKAHEAD_CHARS,
        lastBoundaryChar: lastB,
        sinceBoundaryS: since,
        recaleRemainMs: recale,
        clock: seaClock,
        zoom: 4,
        lat: 30,
        voiceLed: true,
        phraseEnded: false,
        nowMs: wall * 1000,
      });
      recale = step.recaleRemainMs;
      const dT = step.t - t;
      if (wall > 0.4 && wall < 4.6 && dT > 1) advances.push(dT);
      if (wall > 0.4 && wall < 4.6 && Number.isFinite(step.pxPerS) && step.pxPerS > 0.5) {
        speeds.push(step.pxPerS);
      }
      t = step.t;
    }
    assert.ok(advances.length > 30, `trop peu d'avances (${advances.length})`);
    const ratio = Math.max(...advances) / Math.min(...advances);
    assert.ok(ratio <= 1.5, `rapport ${ratio.toFixed(2)} > 1,5`);
    assert.ok(advances.every((a) => a > 0), "frame à l'arrêt hors escale");
    assert.ok(speeds.every((v) => v <= FILM_V_MAX_PX_S + 8), "v_max dépassée");
    assert.ok(speeds.some((v) => v >= FILM_V_MIN_PX_S - 8), "aucune vitesse dans les bornes");
    assert.ok(t > tA, "le bateau a avancé");
  });

  it("l'attente de la voix ne coupe jamais une phrase", () => {
    const mid = voiceShouldWait({ phraseEnded: false, t: 0, sentenceEndT: 1e12, atQuay: false });
    assert.equal(mid.wait, false);
    assert.equal(mid.cut, false);
    const late = voiceShouldWait({ phraseEnded: true, t: 0, sentenceEndT: 1e12, atQuay: false });
    assert.equal(late.wait, true);
    assert.equal(late.cut, false);
    assert.equal(late.skip, false);
    const quay = voiceShouldWait({ phraseEnded: true, t: tB, sentenceEndT: tQuay, atQuay: true });
    assert.equal(quay.wait, true);
    assert.equal(quay.cut, false);
    assert.equal(quay.skip, true);
    const done = voiceShouldWait({ phraseEnded: true, t: tB, sentenceEndT: tB, atQuay: false });
    assert.equal(done.wait, false);
    assert.equal(done.cut, false);
  });

  it("après la phrase d'escale, rampe ≤ 1 s vers le départ suivant, voix en attente", () => {
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    const start = stepFilmTime({
      t: tB,
      dt: 1 / 60,
      chapter: ch,
      plan,
      chapterIdx: 0,
      charIdx: seaText.length + 2,
      clock: seaClock,
      zoom: 4,
      voiceLed: false,
      phraseEnded: true,
      nowMs: 0,
    });
    assert.equal(start.voiceHold, true);
    assert.ok(start.skipRamp, "rampe d'escale");
    assert.ok(start.skipRamp.durationMs <= 1000);
    let t = start.t;
    let ramp = start.skipRamp;
    for (let i = 1; i <= 60; i += 1) {
      const step = stepFilmTime({
        t,
        dt: 1 / 60,
        chapter: ch,
        plan,
        chapterIdx: 0,
        charIdx: seaText.length + 2,
        clock: seaClock,
        zoom: 4,
        voiceLed: false,
        phraseEnded: true,
        skipRamp: ramp,
        nowMs: (i / 60) * 1000,
      });
      t = step.t;
      ramp = step.skipRamp;
    }
    assert.equal(ramp, null);
    assert.ok(t >= tQuay - 1, "a rejoint le départ suivant");
  });
});

describe("replay — ancres au mot", () => {
  it("chapterAnchors garde le charIdx serveur (déjà compensé) et reste monotone", () => {
    const tA = Date.parse("2026-05-15T12:00:00Z");
    const tGib = Date.parse("2026-05-21T12:00:00Z");
    const tB = Date.parse("2026-05-24T12:00:00Z");
    const text = "Le 21 mai, le détroit de Gibraltar entre Tanger et Algeciras. Arrivée à Ajaccio le 26 mai.";
    const nameAt = text.indexOf("Gibraltar");
    const compensated = Math.max(0, nameAt - FILM_VOICE_LOOKAHEAD_CHARS);
    const lastWord = text.lastIndexOf("mai");
    const ch = {
      tA,
      tB,
      text,
      chars: text.length,
      anchors: [
        { charIdx: compensated, t: new Date(tGib).toISOString() },
        { charIdx: Math.max(0, lastWord - FILM_VOICE_LOOKAHEAD_CHARS), t: new Date(tB).toISOString() },
      ],
    };
    const points = chapterAnchors(ch);
    assert.ok(points.length >= 3);
    let prev = -1;
    for (const p of points) {
      assert.ok(p.charIdx >= prev);
      prev = p.charIdx;
    }
    const atName = points.find((p) => p.charIdx === compensated);
    assert.ok(atName);
    assert.equal(atName.t, tGib);
    const plan = filmPlan({ chapters: [{ ...ch, tA: new Date(tA).toISOString(), tB: new Date(tB).toISOString() }], targetSeconds: 150 });
    assert.equal(plan.timeAt(0, compensated), tGib);
  });
});
