import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { advanceReplayTime, filmPlan, positionAt, sentenceSpan, stepFilmTime } from "../engine/replay.js";
import { abandonVoiceToLinear, applyReplayStop, approachStopEvent, arrivalBubbleFitsDestination, canStartOfficialReplay, closingSubtitle, FILM_CHAPTER_HOLD_EPS_MS, FILM_ESTIMATE_CPS, FILM_PREPARE_POLL_MS, FILM_VISIBILITY_CATCHUP_MS, FILM_VOICE_STALL_MS, filmBarSubtitle, filmBoatAtPhrase, filmBoatTimeAtPhrase, filmBudgetCanPlay, filmCharRatesStable, filmChapterPlayheadCapped, filmEndCharIdx, filmEstimatedSeconds, filmHasRg6Rg7Fingerprint, filmQueryKeepsReady, filmRequestPath, filmRequestStyle, filmResponseShouldRetry, filmScriptCharIdx, filmShouldFinish, filmSourceKey, filmSpeakSeconds, filmSubtitleAt, filmSubtitleHighlight, filmSubtitleShowsAir, filmTextHasT0Year, filmTimeWhileChapterSpeaks, followClockLineFromT0, followEtaFromClock, formatFilmEstimateClock, isOfficialFilmVoyage, isPreparingFilm, isRe7OfficialFilm, isReadyRemoteFilm, isWrittenFilmSource, linearFilmAt, officialFilmStatus, pickFilmChapters, pickFilmEstimateSeconds, resolveFilmTargetSeconds, resolveServedFilm, shouldApplyChapterFromClock, shouldHoldFilmForBudget, shouldReturnToLive, spokenCharsSoFar, splitFilmSentences, stepAlongPlan, toggleFilmDuration, visibilityCatchupStep, visibleFilmSubtitle, voiceContinueElapsed, voiceLeadPolicy, voiceStalled, wallClockSpeakSeconds, WRITTEN_FILM_SOURCE, writtenPillEnabled } from "./useReplay.js";
import { briefingForReplayPosition, replayPlace } from "./useReplay.js";
import { VOICE_LEAD_MS, VOICE_MS_PER_CHAR } from "../utils/speak.js";
import { shouldStopSpeakingOnChapterChange } from "./useReplayVoice.js";
import { DEFAULT_T0_ISO, simulationT0Iso } from "../engine/voyageClock.js";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";

const here = dirname(fileURLToPath(import.meta.url));
const hook = readFileSync(join(here, "useReplay.js"), "utf8");
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
const bar = readFileSync(join(here, "..", "components", "SimulationFilmBar.jsx"), "utf8");

describe("useReplay contract", () => {
  it("expose un état de chargement récupérable pour le film officiel, avec libellés FR/EN", () => {
    assert.match(hook, /setTimeout\(\(\) => \{\s*requestTimedOut = true;\s*ac\.abort\(\);\s*\}, 30_000\)/);
    assert.match(hook, /setFilmStatus\("timeout"\)/);
    assert.match(hook, /setFilmStatus\("absent"\)/);
    assert.match(hook, /const retryFilmLoad = useCallback/);
    assert.match(app, /onRetryLoad: replay\.retryFilmLoad/);
    assert.match(bar, /data-testid="film-load-status"/);
    assert.match(bar, /data-testid="film-load-retry"/);
    for (const key of ["filmLoadPending", "filmLoadPreparing", "filmLoadEmpty", "filmLoadError", "filmLoadTimeout", "filmLoadStale", "filmLoadRetry"]) {
      assert.ok(fr[key], `fr.${key}`);
      assert.ok(en[key], `en.${key}`);
      assert.notEqual(fr[key], en[key], `${key} traduit`);
    }
  });

  it("replays on the official clock, consumes the film plan, and hands back to live at the end or on Stop", () => {
    assert.match(hook, /replayWindow\(clockToUse, Date\.now\(\)\)/);
    assert.match(hook, /fromLat: c\.fromLat/);
    assert.match(hook, /toLon: c\.toLon/);
    assert.match(hook, /requestAnimationFrame\(tick\)/);
    assert.match(hook, /if \(done\)/);
    assert.match(hook, /const stop = useCallback/);
    assert.match(hook, /\/voyage\/official\/film/);
    assert.match(hook, /t0=\$\{encodeURIComponent\(t0\)\}/);
    assert.match(hook, /t0 = DEFAULT_T0_ISO/);
    assert.match(hook, /buildFilmScript/);
    assert.match(hook, /FILM_UI_MS/);
    assert.match(hook, /if \(uiDue\) setTMs\(next\)/);
    assert.doesNotMatch(hook, /Tavily|Nebius/i);
  });

  it("App swaps the live boat for the replayed one in Suivre, jumps the playhead each frame, reads each new leg aloud", () => {
    // La position live vient de la source (official.live en Berry,
    // vessel.live sur ma route) — le replay la remplace pareil.
    assert.match(app, /replay\.active && replay\.live \? replay\.live : sourceLive/);
    assert.match(app, /const sourceLive = suivreCustom \? \(vessel\.live \|\| customClientLive\) : official\.live;/);
    assert.match(app, /jump: Boolean\(live\.replay\)/);
    // The voice lives in hooks/useReplayVoice.js; App mounts it.
    assert.match(app, /useReplayVoice\(\{/);
    assert.match(app, /chapterText: replay\.chapterText/);
    assert.match(readFileSync(join(here, "useReplayVoice.js"), "utf8"), /speakSentence|speak\(/);
    assert.match(readFileSync(join(here, "useReplayVoice.js"), "utf8"), /isVoiceHeld/);
    assert.match(app, /onSentenceEnd: replay\.onSentenceEnd/);
    assert.match(app, /momentNow=\{replay\.active \? replay\.card/);
    assert.match(app, /storyReplay=\{replay\.active\}/);
  });

  it("le récit du panneau pendant Revoir reste sur l'horloge officielle", () => {
    assert.match(app, /const storyLive = replay\.active && sourceLive \? sourceLive : live/);
    assert.match(app, /live: storyLive/);
    assert.match(app, /now: storyLive\?\.iso \|\| Date\.now\(\)/);
  });

  it("the film bar offers Revoir / Stop ; voice follows Écouter (no 🔊)", () => {
    assert.match(bar, /data-testid="replay-start"/);
    assert.match(bar, /data-testid="replay-stop"/);
    assert.doesNotMatch(bar, /data-testid="replay-voice"/);
    assert.match(bar, /testId="listen"/);
    assert.match(bar, /onListening=\{replay\?\.onVoice\}/);
    assert.match(bar, /deferSpeak=\{Boolean\(replay\?\.active\)\}/);
    assert.match(hook, /voice is piloted by the film-bar/);
  });

  it("App feeds the current paragraph to speech while a replay is active", () => {
    assert.match(app, /const speechText = replay\.active/);
    assert.match(app, /replay\.chapterText/);
  });

  it("le film est chapitré : filmPlan, onboundary, durée cible, sous-titre", () => {
    assert.match(hook, /filmPlan\(/);
    assert.match(hook, /onVoiceBoundary/);
    // 27 sept. / RG12 : le pas de temps mené par la voix passe par stepFilmTime
    // (prédiction, gouverneur) ; la voix n'est plus recalibrée (débit constant).
    assert.match(hook, /stepFilmTime\(/);
    assert.match(hook, /voiceHoldRef/);
    assert.doesNotMatch(hook, /calibrateRate/);
    assert.match(hook, /targetSeconds/);
    assert.match(hook, /if \(done\)/);
    assert.match(bar, /data-testid="film-subtitle"/);
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(hook, /useState\(0\)/);
    assert.match(bar, /=== sec \? 0 : sec/);
  });

  it("Durées décochables, budget tenu, temps naturel sans case", () => {
    assert.equal(toggleFilmDuration(0, 150), 150);
    assert.equal(toggleFilmDuration(150, 150), 0);
    assert.equal(toggleFilmDuration(150, 180), 180);
    assert.equal(toggleFilmDuration(180, 180), 0);
    const chapters = [{ text: "x".repeat(320) }];
    assert.equal(resolveFilmTargetSeconds(150, chapters), 150);
    assert.equal(resolveFilmTargetSeconds(0, chapters), filmSpeakSeconds(chapters));
    assert.equal(shouldHoldFilmForBudget({ userBudget: 150, wallElapsed: 121, lastChapter: true }), true);
    assert.equal(shouldHoldFilmForBudget({ userBudget: 150, wallElapsed: 150, lastChapter: true }), false);
    assert.equal(shouldHoldFilmForBudget({ userBudget: 0, wallElapsed: 80, lastChapter: true }), false);
    assert.match(hook, /shouldHoldFilmForBudget/);
    assert.match(hook, /budgetSeconds/);
    assert.match(hook, /resolveFilmTargetSeconds\(userBudget, chapters\)/);
    assert.match(hook, /keepChapters: true/);
    assert.doesNotMatch(hook, /userBudget > 0 \? userBudget : FILM_TARGET_SECONDS/);
    assert.doesNotMatch(hook, /keepChapters: userBudget <= 0/);
  });

  it("2:30 : les 15 chapitres sont joués et ended seulement au dernier", () => {
    const lengths = [117, 223, 202, 425, 138, 184, 83, 87, 179, 33, 221, 28, 56, 177, 270];
    const chapters = lengths.map((n, i) => ({
      text: "x".repeat(n),
      tA: 1_000_000 + i * 86_400_000,
      tB: 1_000_000 + (i + 1) * 86_400_000,
    }));
    const plan = filmPlan({
      chapters,
      targetSeconds: resolveFilmTargetSeconds(150, chapters),
      keepChapters: true,
    });
    assert.equal(plan.chapters.length, 15);
    assert.equal(plan.targetSeconds, 150);
    const speakSec = wallClockSpeakSeconds(plan, FILM_ESTIMATE_CPS);
    const seen = new Set();
    let ended = false;
    let finishAt = null;
    for (let t = 0; t <= speakSec + 1; t += 0.25) {
      const at = linearFilmAt(t, plan);
      seen.add(at.chapterIdx);
      const done = filmShouldFinish({
        voiceClock: false,
        speaking: false,
        voiceAllDone: false,
        linearFinish: at.finish,
        lastReached: at.lastReached,
        stopping: false,
      });
      if (t + 1e-6 < speakSec) assert.equal(done, false, `fini trop tôt à ${t} s`);
      if (done) {
        ended = true;
        finishAt = t;
        assert.equal(at.chapterIdx, 14);
        assert.equal(at.lastReached, true);
        break;
      }
    }
    assert.equal(ended, true);
    assert.ok(finishAt + 1e-6 >= speakSec);
    assert.equal(seen.size, 15);
    for (let i = 0; i < 15; i += 1) assert.ok(seen.has(i), `chapitre ${i} joué`);
  });

  it("Durée estimée = caractères ÷ 15, sans recalibrer la voix", () => {
    assert.equal(filmEstimatedSeconds(2250), 150);
    assert.equal(filmEstimatedSeconds(2700), 180);
    assert.equal(filmEstimatedSeconds(0), 0);
    assert.equal(formatFilmEstimateClock(160), "2:40");
    assert.equal(formatFilmEstimateClock(0), "");
    assert.equal(pickFilmEstimateSeconds(150, { 150: { estimatedSeconds: 160 } }, 0), 160);
    assert.equal(pickFilmEstimateSeconds(0, { 0: { estimatedSeconds: 240 } }, 99), 240);
    assert.equal(pickFilmEstimateSeconds(180, null, 195), 195);
    const q0 = "lang=fr&seconds=0&style=raw&t0=2026-05-15T08%3A00%3A00.000Z";
    const q150 = "lang=fr&seconds=150&style=raw&t0=2026-05-15T08%3A00%3A00.000Z";
    assert.equal(filmQueryKeepsReady(q0, q150), false);
    assert.equal(filmQueryKeepsReady(q150, q150), true);
    assert.equal(filmQueryKeepsReady(q150, "lang=en&seconds=150&style=raw&t0=2026-05-15T08%3A00%3A00.000Z"), false);
    assert.equal(filmBudgetCanPlay({ chars: 5312, budgetSeconds: 150 }), false);
    assert.equal(filmBudgetCanPlay({ chars: 2068, budgetSeconds: 150 }), true);
    assert.equal(filmBudgetCanPlay({ chars: 5312, budgetSeconds: 0 }), true);
    assert.equal(filmBudgetCanPlay({ chars: 3375, budgetSeconds: 150 }), true);
    assert.equal(filmBudgetCanPlay({ chars: 3376, budgetSeconds: 150 }), false);
    assert.match(hook, /filmQueryKeepsReady/);
    assert.match(hook, /filmBudgetCanPlay\(\{ chars:/);
    assert.doesNotMatch(hook, /seconds=\[\^&\]/);
    assert.doesNotMatch(hook, /calibrateRate/);
    assert.match(hook, /estimatedSeconds/);
    assert.match(app, /estimatedSeconds: replay\.estimatedSeconds/);
  });

  it("Les événements du chapitre ouvrent la bulle (même texte que la carte NOW)", () => {
    assert.match(hook, /pickFilmEvent/);
    assert.match(hook, /publishEventBubble/);
    assert.match(hook, /filmBubbleRef/);
    assert.match(hook, /FilmEventScoreGate/);
    assert.match(hook, /filmEventCard/);
    assert.match(app, /momentNow=\{replay\.active \? replay\.card/);
  });
});

describe("useReplay — onend immédiat sans boundary", () => {
  const t0 = Date.parse("2026-05-15T08:00:00Z");
  const chapters = [
    { tA: t0, tB: t0 + 86400000, text: "A".repeat(80), fromLat: 48.8, fromLon: 2.4, toLat: 46.1, toLon: -1.1 },
    { tA: t0 + 86400000, tB: t0 + 2 * 86400000, text: "B".repeat(80), fromLat: 46.1, fromLon: -1.1, toLat: 41.9, toLon: 8.7 },
    { tA: t0 + 2 * 86400000, tB: t0 + 3 * 86400000, text: "C".repeat(80), fromLat: 41.9, fromLon: 8.7, toLat: 14.6, toLon: -61.0 },
    { tA: t0 + 3 * 86400000, tB: t0 + 4 * 86400000, text: "D".repeat(80), fromLat: 14.6, fromLon: -61.0, toLat: 4.9, toLon: -52.3 },
  ];

  it("relance une fois, puis linéaire : film non terminé, dernier chapitre à la durée cible", () => {
    const retry = voiceLeadPolicy({
      hadBoundary: false, elapsedMs: 80, alreadyRetried: false, chapterIdx: 0, chapterCount: 4,
    });
    assert.equal(retry.mode, "retry");
    assert.equal(retry.finish, false);
    assert.equal(retry.chapterIdx, 0);

    const linear = voiceLeadPolicy({
      hadBoundary: false, elapsedMs: 80, alreadyRetried: true, chapterIdx: 0, chapterCount: 4,
    });
    assert.equal(linear.mode, "linear");
    assert.equal(linear.finish, false, "le film ne se termine pas sur l'échec voix");
    assert.equal(linear.chapterIdx, 0);

    const plan = filmPlan({ chapters, targetSeconds: 150 });
    const mid = linearFilmAt(5, plan);
    assert.equal(mid.finish, false);
    assert.equal(mid.lastReached, false);

    const end = linearFilmAt(150, plan);
    assert.equal(end.finish, true);
    assert.equal(end.lastReached, true);
    assert.equal(end.chapterIdx, plan.chapters.length - 1);

    assert.match(hook, /voiceFailedRef/);
    assert.match(hook, /waitForVoices/);
    assert.match(hook, /onVoiceLeadFailed/);
    assert.match(hook, /pickFilmChapters/);
    assert.match(hook, /AbortError/);
    assert.doesNotMatch(hook, /targetSeconds \+ 20/);

    const lastOk = voiceLeadPolicy({
      hadBoundary: true, elapsedMs: 800, alreadyRetried: false, chapterIdx: 3, chapterCount: 4,
    });
    assert.equal(lastOk.mode, "advance");
    assert.equal(lastOk.finish, true);

    const lastIncident = voiceLeadPolicy({
      hadBoundary: false, elapsedMs: 80, alreadyRetried: true, chapterIdx: 3, chapterCount: 4,
    });
    assert.equal(lastIncident.mode, "linear");
    assert.equal(lastIncident.finish, false, "un incident de voix ne met pas finish");

    const midCut = voiceLeadPolicy({
      hadBoundary: false, elapsedMs: 80, alreadyRetried: false,
      chapterIdx: 3, chapterCount: 4, hasMoreChunks: true,
    });
    assert.equal(midCut.mode, "advance");
    assert.equal(midCut.finish, false);

    assert.equal(shouldReturnToLive({ voiceIncident: true }), false);
    assert.equal(shouldReturnToLive({ filmFinished: true }), true);
    assert.equal(shouldReturnToLive({ userStopped: true }), true);
    assert.equal(shouldReturnToLive({ voiceIncident: true, filmFinished: true }), true);
  });

  it("script API sans emprise : texte serveur + coords locales (id / from+to)", () => {
    const remote = {
      chapters: [{
        id: "leg-0",
        text: "Arrivée à La Rochelle",
        fromName: "Saint-Maur",
        toName: "La Rochelle",
        fromLat: null,
        fromLon: null,
        toLat: null,
        toLon: null,
      }],
      source: "rules",
    };
    const local = {
      chapters: [{
        id: "leg-0",
        text: "quitté Saint-Maur vers La Rochelle. Aujourd'hui, le bateau est à 19 260 milles nautiques du départ",
        fromName: "Saint-Maur",
        toName: "La Rochelle",
        fromLat: 48.8,
        fromLon: 2.4,
        toLat: 46.1,
        toLon: -1.1,
      }],
      source: "rules",
    };
    const picked = pickFilmChapters(remote, local, []);
    assert.equal(picked.remote, true);
    assert.match(picked.chapters[0].text, /Arrivée à La Rochelle/);
    assert.doesNotMatch(picked.chapters[0].text, /Aujourd'hui, le bateau est à/);
    assert.equal(picked.chapters[0].fromLat, 48.8);
    assert.equal(picked.chapters[0].toLat, 46.1);
    assert.ok(chapterHasFirstLeg(picked.chapters[0]));
  });

  it("Un script distant qui ignore t0 n'est pas retenu", () => {
    const ch2026 = [{ text: "L’expédition a quitté Saint-Maur le 15 mai 2026." }];
    assert.equal(filmTextHasT0Year(ch2026, "2026-05-15T08:00:00.000Z"), true);
    assert.equal(filmTextHasT0Year(ch2026, "2025-05-15T08:00:00.000Z"), false);
    assert.match(hook, /filmTextHasT0Year\(remoteToUse\.chapters, t0\)/);
  });
});

describe("Ligne d'état pilotée par le t0 de la barre", () => {
  const sample = {
    sailNm: 14220,
    seaHours: 112 * 24,
    iso: "2026-09-26T09:14:00.000Z",
  };
  const t0_2025 = "2025-05-15T08:00:00.000Z";

  it("changer le t0 change l'année et garde le jour de voyage dérivé des heures de mer", () => {
    const live = followClockLineFromT0({ ...sample, t0: DEFAULT_T0_ISO, lang: "fr" });
    const shifted = followClockLineFromT0({ ...sample, t0: t0_2025, lang: "fr" });
    assert.match(live, /2026/);
    assert.match(live, /j112/);
    assert.match(shifted, /2025/);
    assert.match(shifted, /j112/);
    assert.notEqual(live, shifted);
    assert.match(shifted, /26 sept\. 2025 · 09:14 UTC/);
  });

  it("remettre le t0 par défaut restaure la ligne d'origine", () => {
    const live = followClockLineFromT0({ ...sample, t0: DEFAULT_T0_ISO, lang: "fr" });
    const shifted = followClockLineFromT0({ ...sample, t0: t0_2025, lang: "fr" });
    const restored = followClockLineFromT0({ ...sample, t0: DEFAULT_T0_ISO, lang: "fr" });
    assert.notEqual(shifted, live);
    assert.equal(restored, live);
  });

  it("restants et ETA viennent des durées de jambes, pas du t0 Simulation", () => {
    const clock = {
      t0: DEFAULT_T0_ISO,
      vertices: [
        { filmNm: 0, tHours: 0, iso: DEFAULT_T0_ISO, seaHours: 0, sailNm: 0 },
        { filmNm: 83, tHours: 10, iso: "2026-05-15T18:00:00.000Z", seaHours: 10, sailNm: 83 },
      ],
    };
    const eta = followEtaFromClock(clock, 0, 83);
    const shiftedClock = { ...clock, t0: t0_2025 };
    assert.equal(followEtaFromClock(shiftedClock, 0, 83), eta);
    assert.equal(eta, 10);
    const simT0 = simulationT0Iso(new Date("2026-09-26T12:00:00.000Z"));
    assert.notEqual(simT0, DEFAULT_T0_ISO);
    assert.notEqual(simT0, t0_2025);
  });

  it("App décale la ligne dès le champ date, sans toucher au t0 Simulation", () => {
    assert.match(app, /followClockLineFromT0/);
    // ReplayT0 ne décale que la ligne Suivre × Berry ; ma route lit le
    // t0 de son propre voyage (date de départ choisie).
    assert.match(app, /t0: suivreBerry \? replayT0/);
    assert.doesNotMatch(app, /iso: isSuivre && replay\.active/);
    assert.match(app, /onDepartureT0=\{suivreBerry \? setReplayT0 : voyage\.setT0\}/);
    assert.match(app, /onT0: suivreBerry \? setReplayT0/);
    assert.doesNotMatch(app, /voyage\.setT0\(replayT0\)/);
    assert.doesNotMatch(app, /voyage\.setT0\(DEFAULT_T0_ISO\)/);
  });
});

function chapterHasFirstLeg(ch) {
  return Number.isFinite(ch.fromLat) && Number.isFinite(ch.toLat);
}

describe("Film officiel, pas la Simulation", () => {
  it("empreinte RE7 : pas Bay of Biscay, pas milles nautiques du départ ; court sans jargon ready", () => {
    assert.equal(isRe7OfficialFilm({
      chapters: [{ text: "Départ de Saint-Maur. golfe de Gascogne. Aujourd’hui, le bateau est à Nouméa." }],
    }), true);
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: "Bay of Biscay ".repeat(10) }] }), false);
    assert.equal(isRe7OfficialFilm({
      chapters: [{ text: "Aujourd'hui, le bateau est à 19 260 milles nautiques du départ." }],
    }), false);
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: `${"mot ".repeat(801)}` }] }), false);
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: `${"mot ".repeat(2501)}` }] }), false);
    assert.equal(isRe7OfficialFilm({ chapters: [] }), false);
  });

  it("801 mots : gabarit RG6 ready, Bay of Biscay stale, remplissage stale", () => {
    const pad = (prefix) => `${prefix} ${"mot ".repeat(801)}`;
    const rg6 = pad("Le 15 mai, Berry-Mappemonde quitte La Rochelle pour Ajaccio. 432 milles, 9 jours de mer.");
    assert.equal(filmHasRg6Rg7Fingerprint(rg6), true);
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: rg6 }] }), true);
    assert.equal(officialFilmStatus({ chapters: [{ text: rg6 }] }), "ready");
    const biscay = pad("Bay of Biscay");
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: biscay }] }), false);
    assert.equal(officialFilmStatus({ chapters: [{ text: biscay }] }), "stale");
    const filler = `${"mot ".repeat(801)}`;
    assert.equal(filmHasRg6Rg7Fingerprint(filler), false);
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: filler }] }), false);
    assert.equal(officialFilmStatus({ chapters: [{ text: filler }] }), "stale");
    assert.equal(isRe7OfficialFilm({
      chapters: [{ text: "Départ de Saint-Maur. golfe de Gascogne. Cap au sud-ouest." }],
    }), true);
  });

  it("officialFilmStatus : absent si fetch échoue, stale si empreinte manquante", () => {
    assert.equal(officialFilmStatus(null, { fetchFailed: true }), "absent");
    assert.equal(officialFilmStatus(null), "pending");
    assert.equal(officialFilmStatus({
      chapters: [{ text: "Saint-Maur golfe de Gascogne Gibraltar. Aujourd’hui, le bateau est à Nouméa." }],
    }), "ready");
    assert.equal(officialFilmStatus({
      chapters: [{ text: "Bay of Biscay and milles nautiques du départ" }],
    }), "stale");
    const live = "The Berry-Mappemonde expedition left Saint-Maur on 15 May 2026. "
      + "The route goes through Bay of Biscay, Western Med. "
      + `${"miles ".repeat(900)} `
      + "Today, the boat is at sea, 10,161 nautical miles from Dzaoudzi.";
    assert.equal(isRe7OfficialFilm({ chapters: [{ text: live }] }), true);
    assert.equal(officialFilmStatus({ chapters: [{ text: live }], status: "ready" }), "ready");
  });

  it("Revoir attend l'horloge officielle + /film RE7 ; absent + requireOfficialFilm → false", () => {
    assert.equal(canStartOfficialReplay({ officialClock: { t0: "x" }, remoteStatus: "ready" }), true);
    assert.equal(canStartOfficialReplay({ officialClock: null, remoteStatus: "ready" }), false);
    assert.equal(canStartOfficialReplay({
      requireOfficialFilm: true,
      officialClock: { t0: "x" },
      fallbackClock: { t0: "y" },
      remoteStatus: "absent",
    }), false);
    assert.equal(canStartOfficialReplay({
      officialClock: null, fallbackClock: { t0: "y" }, remoteStatus: "absent",
    }), false);
    assert.equal(canStartOfficialReplay({ officialClock: { t0: "x" }, remoteStatus: "pending" }), false);
    assert.equal(canStartOfficialReplay({ officialClock: { t0: "x" }, remoteStatus: "stale" }), false);
    assert.equal(canStartOfficialReplay({
      requireOfficialFilm: false, fallbackClock: { t0: "y" }, remoteStatus: "absent",
    }), true);
  });

  it("App : replayControls dès officialClock, canStart passé à la barre", () => {
    assert.match(app, /const filmClock = suivreBerry \? official\.clock : voyage\.clock/);
    assert.match(app, /clock: filmClock/);
    assert.match(app, /fallbackClock: voyage\.clock/);
    assert.match(app, /requireOfficialFilm: isSuivre/);
    assert.match(app, /isSuivre && officialClock \?/);
    assert.doesNotMatch(app, /officialClock && replay\.canStart/);
    assert.match(app, /canStart: replay\.canStart/);
    assert.match(hook, /keepReady/);
    assert.match(hook, /remoteStatusRef\.current === "ready"/);
    assert.match(hook, /isReadyRemoteFilm/);
    assert.match(hook, /seekChapter/);
    assert.match(hook, /pinnedIdxRef/);
    const seekFn = hook.slice(
      hook.indexOf("const seekChapter = useCallback"),
      hook.indexOf("seekChapterRef.current = seekChapter"),
    );
    assert.match(seekFn, /Number\(charIdx\) === 0/, "seekChapter(i, 0) = départ de jambe (RC51)");
    assert.match(seekFn, /filmElapsedRef\.current/, "seekChapter(i, 0) recale l'horloge linéaire");
    assert.match(seekFn, /pinnedIdxRef\.current = null/);
    const replayCall = app.slice(app.indexOf("const replay = useReplay"), app.indexOf("const live = isSuivre"));
    assert.match(replayCall, /clock: filmClock/);
    assert.doesNotMatch(replayCall, /clock: officialClock/);
    assert.match(replayCall, /voyageId: suivreCustom \? customVoyageId : "official"/);
    const startFn = hook.slice(hook.indexOf("const start = useCallback"), hook.indexOf("const onVoiceBoundary"));
    assert.match(startFn, /status === "ready"/);
    assert.match(startFn, /isReadyRemoteFilm/);
    assert.match(startFn, /jamais le brut local/);
    assert.doesNotMatch(startFn, /fallbackClock \|\| clock/);
    assert.doesNotMatch(startFn, /status === "absent"/);
  });

  it("L'URL du film suit le mode ; preparing n'est pas un film", () => {
    assert.equal(filmRequestPath("official"), "/voyage/official/film");
    assert.equal(filmRequestPath(""), "/voyage/official/film");
    assert.equal(filmRequestPath(null), "/voyage/official/film");
    assert.equal(filmRequestPath("abc-123"), "/voyage/abc-123/film");
    assert.equal(isOfficialFilmVoyage("official"), true);
    assert.equal(isOfficialFilmVoyage("abc-123"), false);
    assert.equal(isPreparingFilm({ status: "preparing", chapters: [] }), true);
    assert.equal(isPreparingFilm({ status: "ready", chapters: [{ text: "x" }] }), false);
    assert.equal(officialFilmStatus({ status: "preparing", chapters: [] }), "preparing");
    const customReady = {
      status: "ready",
      chapters: [{ text: `${"La Rochelle vers les Antilles. ".repeat(250)}` }],
    };
    assert.equal(isRe7OfficialFilm(customReady), false);
    assert.equal(isReadyRemoteFilm(customReady, { official: true }), false);
    assert.equal(isReadyRemoteFilm(customReady, { official: false }), true);
    assert.equal(isReadyRemoteFilm({ status: "preparing", chapters: [] }, { official: false }), false);
    assert.equal(isReadyRemoteFilm({ status: "ready", chapters: [] }, { official: false }), false);
    assert.equal(canStartOfficialReplay({ officialClock: { t0: "x" }, remoteStatus: "preparing" }), false);
    assert.equal(FILM_PREPARE_POLL_MS, 10_000);
    assert.match(hook, /FILM_PREPARE_POLL_MS/);
    assert.match(hook, /if \(applied === "preparing"\) \{\s*retryTimer = setTimeout\(load, FILM_PREPARE_POLL_MS\);/);
    assert.doesNotMatch(hook, /prepareStarted|FILM_PREPARE_MAX_MS/);
    assert.match(hook, /filmRequestPath\(voyageId\)/);
    assert.doesNotMatch(hook, /fetch\(`\$\{API\}\/voyage\/official\/film\?\$\{q\}`/);
  });
});

describe("useReplay — temps continu entre deux boundaries", () => {
  it("60 frames entre deux boundaries : 60 positions croissantes, pas < 1/30 de la jambe", () => {
    const t0 = Date.parse("2026-05-15T08:00:00Z");
    const clock = {
      t0: "2026-05-15T08:00:00.000Z",
      vertices: [
        { tHours: 0, filmNm: 0, sailNm: 0, lat: 46.8, lon: 1.7, bearing: 260 },
        { tHours: 4, filmNm: 122, sailNm: 122, lat: 46.15, lon: -1.16, bearing: 260 },
      ],
    };
    const plan = filmPlan({
      chapters: [{
        tA: t0,
        tB: t0 + 4 * 3600000,
        text: "x".repeat(200),
        fromLat: 46.8,
        fromLon: 1.7,
        toLat: 46.15,
        toLon: -1.16,
      }],
      targetSeconds: 150,
    });
    const ch = plan.chapters[0];
    const startPos = positionAt(clock, ch.tA);
    const endPos = positionAt(clock, ch.tB);
    const jambe = Math.hypot(endPos.lat - startPos.lat, endPos.lon - startPos.lon);
    const progress = (p) => {
      const ux = endPos.lon - startPos.lon;
      const uy = endPos.lat - startPos.lat;
      return ((p.lon - startPos.lon) * ux + (p.lat - startPos.lat) * uy) / (jambe * jambe);
    };

    let t = plan.timeAt(0, 10);
    let recale = 0;
    const target = t;
    const positions = [];
    const dt = 1 / 60;
    for (let i = 0; i < 60; i++) {
      const stepped = advanceReplayTime({
        t, dt, chapter: ch, targetT: target, recaleRemainMs: recale,
      });
      t = stepped.t;
      recale = stepped.recaleRemainMs;
      positions.push(positionAt(clock, t));
    }

    assert.equal(positions.length, 60);
    for (let i = 1; i < 60; i++) {
      assert.ok(
        progress(positions[i]) > progress(positions[i - 1]),
        `frame ${i} ne progresse pas le long de la jambe`,
      );
      const step = Math.hypot(
        positions[i].lat - positions[i - 1].lat,
        positions[i].lon - positions[i - 1].lon,
      );
      assert.ok(step < jambe / 30, `écart frame ${i} = ${step} ≥ jambe/30`);
    }

    const behind = t + 60_000;
    const slowed = advanceReplayTime({
      t: behind, dt, chapter: ch, targetT: t, recaleRemainMs: 300,
    });
    assert.ok(slowed.t >= behind, "pas de saut arrière si la cible est derrière");
    assert.match(hook, /FILM_RECALE_MS/);
    assert.match(hook, /voiceTargetRef/);
  });
});

describe("useReplay — interpolation jusqu'au dernier chapitre", () => {
  const t0 = Date.parse("2026-05-15T08:00:00Z");
  const hour = 3600000;
  const clock = {
    t0: "2026-05-15T08:00:00.000Z",
    vertices: [
      { tHours: 0, filmNm: 0, sailNm: 0, lat: 46.8, lon: 1.7, bearing: 260 },
      { tHours: 4, filmNm: 122, sailNm: 122, lat: 46.15, lon: -1.16, bearing: 260 },
      { tHours: 8, filmNm: 400, sailNm: 400, lat: 41.9, lon: 8.7, bearing: 140 },
      { tHours: 12, filmNm: 900, sailNm: 900, lat: 14.6, lon: -61.0, bearing: 250 },
    ],
  };
  const chapters = [
    { tA: t0, tB: t0 + 4 * hour, text: "A".repeat(80), fromLat: 46.8, fromLon: 1.7, toLat: 46.15, toLon: -1.16, toName: "La Rochelle" },
    { tA: t0 + 4 * hour, tB: t0 + 8 * hour, text: "B".repeat(80), fromLat: 46.15, fromLon: -1.16, toLat: 41.9, toLon: 8.7, toName: "Ajaccio (Corse)" },
    { tA: t0 + 8 * hour, tB: t0 + 12 * hour, text: "C".repeat(80), fromLat: 41.9, fromLon: 8.7, toLat: 14.6, toLon: -61.0, toName: "Fort-de-France" },
  ];

  it("60 frames entre deux boundaries : positions monotones le long du trait jusqu'au dernier chapitre", () => {
    const plan = filmPlan({ chapters, targetSeconds: 150 });
    const lastIdx = plan.chapters.length - 1;
    const midA = plan.timeAt(0, 10);
    const midB = plan.timeAt(0, 40);
    let t = midA;
    let recale = 0;
    const positions = [];
    const dt = 1 / 60;
    for (let i = 0; i < 60; i++) {
      const ch = plan.chapters[0];
      const stepped = advanceReplayTime({
        t, dt, chapter: ch, targetT: midB, recaleRemainMs: recale,
      });
      t = stepped.t;
      recale = stepped.recaleRemainMs;
      positions.push(positionAt(clock, t));
    }
    for (let i = 1; i < positions.length; i++) {
      assert.ok(
        positions[i].filmNm > positions[i - 1].filmNm,
        `frame ${i} ne progresse pas le long du trait`,
      );
    }

    const along = stepAlongPlan({
      plan,
      clock,
      frames: 60,
      dt: plan.targetSeconds / 60,
      elapsed0: 0,
    });
    assert.equal(along.length, 60);
    assert.equal(along[along.length - 1].chapterIdx, lastIdx);
    assert.equal(along[along.length - 1].lastReached, true);
    for (let i = 1; i < along.length; i++) {
      assert.ok(
        along[i].filmNm >= along[i - 1].filmNm - 1e-9,
        `chapitre ${along[i].chapterIdx} frame ${i} recule (filmNm)`,
      );
    }
    assert.ok(along[along.length - 1].filmNm > along[0].filmNm);
    assert.match(hook, /stepAlongPlan|positionAt\(clockRef/);
    assert.match(hook, /approachStopEvent/);
    assert.match(hook, /lastReached/);
  });

  it("bulle d'approche : une escale proche, rien trop tôt", () => {
    const late = approachStopEvent(chapters[1], { frac: 0.9 });
    assert.equal(late.kind, "stop");
    assert.match(late.card.title, /Ajaccio/);
    assert.equal(approachStopEvent(chapters[1], { frac: 0.2 }), null);
    assert.equal(approachStopEvent({ idx: 0, toName: "", text: "" }, { frac: 0.99 }), null);
  });

  it("ferme la carte d'arrivée quand la barre a changé de jambe", () => {
    const halifax = {
      kind: "stop",
      id: "stop:halifax",
      title: "Halifax",
      text: "Arrival at Halifax (Nouvelle-Écosse) on 26 August.",
    };
    assert.equal(arrivalBubbleFitsDestination(halifax, "Cayenne (Guyane)"), false);
    assert.equal(arrivalBubbleFitsDestination(halifax, "Saint-Pierre-et-Miquelon"), false);
    assert.equal(arrivalBubbleFitsDestination(halifax, "Halifax"), true);
    const papeete = {
      kind: "stop",
      title: "Papeete",
      text: "Arrival at Papeete (Polynésie française) on 4 October.",
    };
    assert.equal(arrivalBubbleFitsDestination(papeete, "Mata-Utu (Wallis-et-Futuna)"), false);
    assert.equal(arrivalBubbleFitsDestination(papeete, "Papeete (Polynésie française)"), true);
    const sentence = {
      kind: "stop",
      title: "Arrival at Papeete on 4 October",
      text: "Arrival at Papeete on 4 October.",
    };
    assert.equal(arrivalBubbleFitsDestination(sentence, "Papeete (Polynésie française)"), true);
    assert.equal(arrivalBubbleFitsDestination(sentence, "Mata-Utu"), false);
    assert.equal(arrivalBubbleFitsDestination({ kind: "wx", title: "Vent", text: "12 kn" }, "Mata-Utu"), true);
    const approach = approachStopEvent(
      { idx: 2, toName: "Ajaccio (Corse)", text: "Arrival at Ajaccio on 24 May." },
      { frac: 0.9 },
    );
    assert.equal(arrivalBubbleFitsDestination(approach.card, "Ajaccio (Corse)"), true);
    assert.equal(arrivalBubbleFitsDestination(approach.card, "Fort-de-France"), false);
    assert.match(hook, /arrivalBubbleFitsDestination/);
    assert.match(hook, /filmBubbleRef\.current\.dismiss\(\)/);
  });
});

describe("FM1 — briefing et Stop", () => {
  it("le briefing suit la position rejouée et Stop rend la vue Suivre", () => {
    const now = "Le bateau est aujourd’hui à Nouméa.";
    const stopped = briefingForReplayPosition({ active: false, nowBriefing: now, replayText: "ailleurs" });
    assert.equal(stopped.view, "suivre");
    assert.equal(stopped.briefing, now);
    assert.equal(stopped.follows, false);
    const live = { lat: -22.27, lon: 166.44 };
    assert.deepEqual(replayPlace(true, live), { lat: live.lat, lon: live.lon });
    const playing = briefingForReplayPosition({
      active: true,
      live,
      nowBriefing: now,
      replayText: "Le bateau navigue dans les eaux de la Nouvelle-Calédonie.",
    });
    assert.equal(playing.view, "suivre");
    assert.equal(playing.follows, true);
    assert.equal(playing.lat, live.lat);
    assert.match(playing.briefing, /Nouvelle-Calédonie/);
    const hidden = briefingForReplayPosition({ active: true, live, nowBriefing: now, replayText: "  " });
    assert.equal(hidden.hidden, true);
    assert.equal(hidden.briefing, "");
    const stopFn = hook.slice(hook.indexOf("const stop = useCallback"));
    assert.ok(stopFn.indexOf("stoppingRef.current = true") < stopFn.indexOf("applyReplayStop("));
    assert.ok(stopFn.indexOf("finishedRef.current = true") < stopFn.indexOf("applyReplayStop("));
    assert.match(stopFn, /exitDocumentFullscreen/);
    assert.match(stopFn, /restoreFollowView/);
    assert.match(app, /setFilmFullscreen\(false\)/);
    assert.match(app, /setCameraFollow\(true\)/);
    assert.match(app, /VIEW_SUIVRE/);
    assert.match(app, /replay\.stop\(\)/);
  });
});

describe("useReplay — Stop coupe voix, animation, caméra", () => {
  it("stop() met active=false, coupe la voix, libère la caméra", () => {
    const calls = { voice: 0, camera: 0, raf: 0 };
    const next = applyReplayStop({
      cancelRaf: () => { calls.raf += 1; },
      stopVoice: () => { calls.voice += 1; },
      releaseCamera: () => { calls.camera += 1; },
    });
    assert.equal(next.active, false);
    assert.equal(next.tMs, null);
    assert.equal(next.card, null);
    assert.equal(next.progress, 0);
    assert.equal(next.chapterText, "");
    assert.equal(calls.voice, 1);
    assert.equal(calls.camera, 1);
    assert.equal(calls.raf, 1);
    assert.match(hook, /applyReplayStop\(/);
    assert.match(hook, /stopSpeaking/);
    assert.match(hook, /publishFilmEnd/);
    assert.match(app, /onStop: \(\) => \{/);
    assert.match(app, /replay\.stop\(\)/);
    assert.match(app, /VIEW_SUIVRE/);
  });

  it("passer en Suivre/Revoir met escaleStop à null", () => {
    assert.match(app, /shouldCloseEscaleSheet/);
    assert.match(app, /closeEscaleSheet\(\)/);
    assert.match(app, /replayStarting: true/);
    assert.match(app, /nextView: next/);
    assert.match(app, /stop=\{replay\.active \? null : escaleStop\}/);
    assert.match(app, /filmActive: replay\.active/);
    assert.match(app, /clearToken: escaleClear/);
    assert.match(app, /setEscaleClear/);
    assert.match(bar, /data-testid="replay-stop"/);
    assert.match(bar, /data-testid="stop-auto"/);
    assert.match(bar, /testId="listen"/);
    assert.doesNotMatch(bar, /disabled=\{Boolean\(replay\.active\)\}[\s\S]{0,80}replay-stop/);
  });
});

describe("useReplay — voix sans coupure, Stop total, pas de live sur incident", () => {
  it("stop() pendant la lecture coupe voix + animation + caméra au premier geste", () => {
    const order = [];
    const next = applyReplayStop({
      stopVoice: () => { order.push("voice"); },
      releaseCamera: () => { order.push("camera"); },
      cancelRaf: () => { order.push("raf"); },
    });
    assert.deepEqual(order, ["voice", "camera", "raf"]);
    assert.equal(next.active, false);
    assert.equal(next.tMs, null);
    assert.equal(next.progress, 0);

    const stopFn = hook.slice(hook.indexOf("const stop = useCallback"));
    assert.match(stopFn, /stoppingRef\.current = true/);
    assert.ok(
      stopFn.indexOf("stoppingRef.current = true") < stopFn.indexOf("applyReplayStop("),
      "Stop pose le garde-fou avant cancel (onend de Chrome ne relance pas)",
    );
    assert.ok(
      stopFn.indexOf("finishedRef.current = true") < stopFn.indexOf("applyReplayStop("),
      "finish est bloqué avant l'arrêt de la voix",
    );
    assert.match(hook, /shouldReturnToLive/);
    assert.match(hook, /stoppingRef\.current \|\| finishedRef\.current/);
  });
});

describe("useReplay — fin du film : sous-titre de clôture conservé", () => {
  it("applyReplayStop garde le dernier sous-titre si keepChapterText", () => {
    const close = "Aujourd’hui, le bateau est à Nouméa.";
    const merged = `Départ vers Fort-de-France. ${close}`;
    assert.equal(closingSubtitle(merged), close);
    const kept = applyReplayStop({
      keepChapterText: true,
      chapterText: merged,
    });
    assert.equal(kept.active, false);
    assert.equal(kept.chapterText, close);
    assert.equal(kept.progress, 1);
    const cleared = applyReplayStop({});
    assert.equal(cleared.chapterText, "");
    assert.equal(cleared.progress, 0);
  });

  it("finish() arrête sans effacer le sous-titre ; Stop utilisateur l'efface", () => {
    assert.match(hook, /keepSubtitle: true/);
    assert.match(hook, /keepChapterText: keep/);
    assert.match(hook, /chapterTextRef/);
    assert.match(bar, /replay\?\.active \|\| replay\?\.subtitle/);
  });
});

describe("useReplay — sous-titre visible : phrases avion RF5", () => {
  it("choisit les phrases avion déjà dans le chapitre, sans inventer", () => {
    const long = [
      "Puis, le 18 août, départ vers Saint-Pierre-et-Miquelon, escale prévue.",
      "Puis, le 18 août, l'équipage prend l'avion pour Halifax.",
      "Ensuite, le 22 août, retour en avion vers Cayenne.",
    ].join(" ");
    const shown = visibleFilmSubtitle(long);
    assert.match(shown, /prend l'avion pour Halifax/);
    assert.match(shown, /retour en avion vers Cayenne/);
    assert.doesNotMatch(shown, /départ vers Saint-Pierre/);
    assert.equal(filmSubtitleShowsAir(shown), true);
    const plain = "Départ de Saint-Maur vers La Rochelle.";
    assert.equal(visibleFilmSubtitle(plain), plain);
    assert.equal(filmSubtitleShowsAir(plain), false);
    const en = "Then, on 18 August, the crew flies to Halifax. Later, return flight to Cayenne.";
    assert.match(visibleFilmSubtitle(en), /the crew flies to Halifax/);
    assert.match(visibleFilmSubtitle(en), /return flight to Cayenne/);
    assert.equal(visibleFilmSubtitle(""), "");
  });

  it("App passe le sous-titre choisi ; la barre ne tronque pas l'avion", () => {
    assert.match(app, /visibleFilmSubtitle\(replay\.subtitle \|\| replay\.chapterText/);
    assert.match(app, /fromName:\s*replay\.fromName/);
    assert.match(app, /toName:\s*replay\.toName/);
    assert.match(bar, /visibleFilmSubtitle/);
    assert.match(bar, /filmSubtitleHighlight/);
    assert.match(bar, /data-testid="film-subtitle-place"/);
    assert.match(bar, /filmSubtitleShowsAir/);
    assert.match(bar, /filmSubtitleAir \? "whitespace-normal" : "truncate"/);
    assert.doesNotMatch(bar, /data-testid="film-subtitle" className="[^"]*truncate/);
  });
});

describe("useReplay — client robuste (E2, E3, E4)", () => {
  const t0 = Date.parse("2026-05-15T08:00:00Z");
  const hour = 3600000;

  function longChapters(n = 7, chars = 200) {
    return Array.from({ length: n }, (_, i) => ({
      tA: t0 + i * 4 * hour,
      tB: t0 + (i + 1) * 4 * hour,
      text: `${"Phrase une du chapitre. ".padEnd(80)}Phrase deux vers le lieu ${i}. `.padEnd(chars, "x"),
      fromLat: 46 - i,
      fromLon: -1 - i,
      toLat: 45 - i,
      toLon: -2 - i,
      fromName: "La Rochelle",
      toName: "Ajaccio",
    }));
  }

  it("sans voix : durée ≥ 90 % de l'estimée, ended seulement à la dernière phrase", () => {
    assert.equal(FILM_VOICE_STALL_MS, 2000);
    assert.equal(FILM_VISIBILITY_CATCHUP_MS, 2000);
    const chapters = longChapters(7, 200);
    const plan = filmPlan({ chapters, targetSeconds: 150 });
    const speakSec = wallClockSpeakSeconds(plan, FILM_ESTIMATE_CPS);
    assert.ok(speakSec >= 90, `estimée trop courte: ${speakSec}`);
    const early = linearFilmAt(53, plan);
    assert.equal(early.finish, false, "53 s ne termine pas un film de 7 chapitres");
    assert.ok(early.chapterIdx < plan.chapters.length - 1);
    assert.equal(linearFilmAt(speakSec * 0.89, plan).finish, false);

    let ended = false;
    let elapsed = 0;
    const dt = 0.5;
    let finishAt = null;
    while (elapsed <= speakSec + 2) {
      const at = linearFilmAt(elapsed, plan);
      if (at.finish) {
        ended = true;
        finishAt = elapsed;
        assert.equal(at.lastReached, true);
        assert.equal(at.chapterIdx, plan.chapters.length - 1);
        break;
      }
      elapsed += dt;
    }
    assert.equal(ended, true);
    assert.ok(finishAt >= speakSec * 0.9, `fini à ${finishAt} s < 90 % de ${speakSec}`);
    assert.match(hook, /visibilitychange/);
    assert.match(hook, /voiceBoundaryAtRef\.current === 0/);
    assert.match(hook, /voiceCharRef\.current > 0/);
    assert.match(hook, /filmBarSubtitle/);
    assert.match(hook, /filmSubtitleAt/);
    assert.match(readFileSync(join(here, "useReplayVoice.js"), "utf8"), /onLeadFailedRef\.current/);
  });

  it("sous-titre : une phrase à la fois, lieu mis en avant quand il est dit", () => {
    const text = "Départ vers La Rochelle. Ensuite cap sur Ajaccio. Arrivée à Fort-de-France.";
    const starts = splitFilmSentences(text).map((s) => s.start);
    assert.ok(starts.length >= 3);
    const first = filmSubtitleAt(text, text.indexOf("La Rochelle") + 1, {
      toName: "La Rochelle", sentenceStarts: starts,
    });
    const second = filmSubtitleAt(text, text.indexOf("Ajaccio") + 1, {
      toName: "Ajaccio", sentenceStarts: starts,
    });
    const third = filmSubtitleAt(text, text.indexOf("Fort-de-France") + 1, {
      toName: "Fort-de-France", sentenceStarts: starts,
    });
    assert.notEqual(first.sentence, second.sentence);
    assert.notEqual(second.sentence, third.sentence);
    assert.match(first.sentence, /La Rochelle/);
    assert.doesNotMatch(first.sentence, /Ajaccio/);
    assert.equal(first.place, "La Rochelle");
    assert.equal(second.place, "Ajaccio");
    assert.equal(third.place, "Fort-de-France");
    const beforeName = filmSubtitleAt(text, text.indexOf("Fort-de-France") - 1, {
      toName: "Fort-de-France", sentenceStarts: starts,
    });
    assert.equal(beforeName.place, "");
    const hi = filmSubtitleHighlight(third.sentence, third.place);
    assert.equal(hi.place, "Fort-de-France");
    assert.ok(hi.before.includes("Arrivée"));
  });

  it("barre : charIdx=0 = 1re phrase, pas le chapitre ; lieu seulement une fois dit", () => {
    const text = "L’expédition a quitté Saint-Maur. Puis La Rochelle. Ensuite l’avion pour Halifax.";
    const starts = splitFilmSentences(text).map((s) => s.start);
    const atStart = filmBarSubtitle({ chapterText: text, charIdx: 0, sentenceStarts: starts, toName: "Saint-Maur" });
    assert.equal(atStart.sentenceMode, true);
    assert.match(atStart.text, /Saint-Maur/);
    assert.doesNotMatch(atStart.text, /La Rochelle/);
    assert.doesNotMatch(atStart.text, /avion/);
    assert.equal(atStart.place, "");
    const named = filmBarSubtitle({
      chapterText: text,
      charIdx: text.indexOf("Saint-Maur") + 1,
      sentenceStarts: starts,
      toName: "Saint-Maur",
    });
    assert.equal(named.place, "Saint-Maur");
    const later = filmBarSubtitle({
      chapterText: text,
      charIdx: text.indexOf("La Rochelle"),
      sentenceStarts: starts,
      toName: "La Rochelle",
    });
    assert.equal(later.sentenceMode, true);
    assert.match(later.text, /La Rochelle/);
    assert.doesNotMatch(later.text, /avion/);
    assert.doesNotMatch(later.text, /Saint-Maur/);
    assert.equal(later.place, "La Rochelle");
    const pinned = filmBarSubtitle({
      chapterText: text,
      charIdx: text.length,
      pinned: true,
      sentenceStarts: starts,
    });
    assert.equal(pinned.sentenceMode, true);
    assert.match(pinned.text, /avion/);
    assert.doesNotMatch(pinned.text, /Saint-Maur/);
    const air = [
      "Mer calme.",
      "Puis, le 18 août, l'équipage prend l'avion pour Halifax.",
      "Ensuite, le 22 août, retour en avion vers Cayenne.",
    ].join(" ");
    const airAt = filmBarSubtitle({ chapterText: air, charIdx: 0 });
    assert.match(airAt.text, /prend l'avion pour Halifax/);
    assert.match(airAt.text, /retour en avion vers Cayenne/);
    assert.doesNotMatch(airAt.text, /Mer calme/);
    assert.ok(airAt.text.length < air.length);
    const airPinned = filmBarSubtitle({ chapterText: air, charIdx: air.length, pinned: true });
    assert.match(airPinned.text, /prend l'avion pour Halifax/);
    assert.match(airPinned.text, /retour en avion vers Cayenne/);
    assert.ok(airPinned.text.length < air.length);
    assert.doesNotMatch(airPinned.text, /Mer calme/);
    const officialCh1 = "L’expédition Berry-Mappemonde a quitté Saint-Maur le 15 mai 2026. Puis, le 15 mai, départ vers La Rochelle.";
    const rb5 = filmBarSubtitle({ chapterText: officialCh1, charIdx: 0 });
    assert.match(rb5.text, /Saint-Maur/);
    assert.doesNotMatch(rb5.text, /La Rochelle/);
    assert.ok(rb5.text.length < officialCh1.length);
    assert.match(filmSubtitleAt(officialCh1, 0).sentence, /Saint-Maur/);
    assert.doesNotMatch(filmSubtitleAt(officialCh1, 0).sentence, /La Rochelle/);
  });

  it("Chapitre side « second voilier » — pas le s'envole d'un autre chapitre", () => {
    const side = "À Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre.";
    const airElsewhere = "Le 19 juillet, l'équipage s'envole de Cayenne pour Halifax ; le catamaran attend à Cayenne.";
    const glued = `${side} ${airElsewhere}`;
    const fromSide = filmBarSubtitle({
      chapterText: glued,
      charIdx: 0,
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Saint-Pierre (Saint-Pierre-et-Miquelon)",
    });
    assert.match(fromSide.text, /second voilier/);
    assert.doesNotMatch(fromSide.text, /s'envole/);
    const clean = filmBarSubtitle({
      chapterText: side,
      charIdx: 0,
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Saint-Pierre (Saint-Pierre-et-Miquelon)",
    });
    assert.match(clean.text, /second voilier/);
    assert.doesNotMatch(clean.text, /s'envole/);
    assert.equal(visibleFilmSubtitle(glued, {
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Saint-Pierre (Saint-Pierre-et-Miquelon)",
    }), glued);
  });

  it("Un chapitre vol n'extrait que CE vol ; reprise sans s'envole", () => {
    const glued = [
      "Le 19 juillet, l'équipage s'envole de Cayenne pour Halifax ; le catamaran attend à Cayenne.",
      "Le 30 juillet, l'équipage s'envole de Halifax pour Cayenne.",
    ].join(" ");
    const out = filmBarSubtitle({
      chapterText: glued,
      charIdx: 0,
      fromName: "Cayenne (Guyane)",
      toName: "Halifax (Nouvelle-Écosse)",
    });
    assert.match(out.text, /s'envole de Cayenne pour Halifax/);
    assert.doesNotMatch(out.text, /s'envole de Halifax pour Cayenne/);
    const back = filmBarSubtitle({
      chapterText: glued,
      charIdx: glued.indexOf("s'envole de Halifax"),
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Cayenne (Guyane)",
    });
    assert.match(back.text, /s'envole de Halifax pour Cayenne/);
    assert.doesNotMatch(back.text, /s'envole de Cayenne pour Halifax/);
    const resume = filmBarSubtitle({
      chapterText: "Le 2 août, le catamaran reprend la mer, départ vers Papeete. L'équipage s'envole de Cayenne pour Halifax.",
      charIdx: 0,
      fromName: "Cayenne (Guyane)",
      toName: "Papeete (Polynésie française)",
    });
    assert.match(resume.text, /reprend la mer|départ vers Papeete/);
    assert.doesNotMatch(resume.text, /s'envole/);
  });

  it("Vol retour élidé « s'envole d’Halifax » (et apostrophe typographique) reconnu", () => {
    const glued = [
      "Le 18 août, l’équipage s’envole de Cayenne pour Halifax ; le catamaran attend à Cayenne.",
      "Le 28 août, l'équipage s'envole d’Halifax pour Cayenne.",
    ].join(" ");
    const back = visibleFilmSubtitle(glued, {
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Cayenne (Guyane)",
    });
    assert.equal(back, "Le 28 août, l'équipage s'envole d’Halifax pour Cayenne.");
    const out = visibleFilmSubtitle(glued, {
      fromName: "Cayenne (Guyane)",
      toName: "Halifax (Nouvelle-Écosse)",
    });
    assert.equal(out, "Le 18 août, l’équipage s’envole de Cayenne pour Halifax ; le catamaran attend à Cayenne.");
    assert.ok(filmSubtitleShowsAir("Le 28 août, l’équipage s’envole d’Halifax pour Cayenne."));
  });

  it("Phrase side sous le curseur même si le chapitre fusionné est étiqueté vol", () => {
    const merged = [
      "À Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre.",
      "Le 26 août, l'équipage s'envole de Halifax pour Cayenne.",
    ].join(" ");
    const atSide = filmBarSubtitle({
      chapterText: merged,
      charIdx: merged.indexOf("second voilier"),
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Cayenne (Guyane)",
    });
    assert.match(atSide.text, /second voilier/);
    assert.doesNotMatch(atSide.text, /s'envole/);
    const atAir = filmBarSubtitle({
      chapterText: merged,
      charIdx: merged.indexOf("s'envole"),
      fromName: "Halifax (Nouvelle-Écosse)",
      toName: "Cayenne (Guyane)",
    });
    assert.match(atAir.text, /s'envole de Halifax pour Cayenne/);
    assert.doesNotMatch(atAir.text, /second voilier/);
  });

  it("Un énoncé qui finit après tB — pas d'applyChapter / pas de stopSpeaking avant onEnd, tMs dans [tA, tB]", () => {
    const tA = Date.parse("2026-06-02T08:00:00Z");
    const tB = tA + 4 * 3600 * 1000;
    const ch = {
      tA,
      tB,
      fromName: "Ajaccio",
      toName: "Fort-de-France",
    };
    // Voix encore en train de dire la dernière phrase : le playhead linéaire
    // a déjà dépassé tB — on le retient.
    const held = filmTimeWhileChapterSpeaks({ t: tB + 60_000, chapter: ch, hold: true });
    assert.ok(held >= tA && held <= tB, `tMs ${held} hors [tA, tB]`);
    assert.equal(held, tB - FILM_CHAPTER_HOLD_EPS_MS);
    assert.equal(shouldApplyChapterFromClock({ voiceClock: true, speaking: true }), false);
    assert.equal(shouldApplyChapterFromClock({ voiceClock: true, speaking: false }), false);
    assert.equal(shouldApplyChapterFromClock({ voiceClock: false, speaking: true }), false);
    assert.equal(shouldApplyChapterFromClock({ voiceClock: false, speaking: false }), true);
    assert.equal(shouldStopSpeakingOnChapterChange({
      spokenText: "Le 2 juin, le bateau quitte Ajaccio.",
      chapterText: "Le 2 juin, le bateau quitte Ajaccio.",
    }), false);
    assert.equal(shouldStopSpeakingOnChapterChange({
      spokenText: "Le 2 juin, le bateau quitte Ajaccio.",
      chapterText: "Cap sur Pointe-à-Pitre.",
    }), true);
    assert.equal(shouldStopSpeakingOnChapterChange({
      spokenText: "",
      chapterText: "Cap sur Pointe-à-Pitre.",
    }), false);
    const clock = {
      t0: "2026-06-02T08:00:00Z",
      vertices: [
        { lat: 41.9, lon: 8.7, tHours: 0, sailNm: 0, filmNm: 0 },
        { lat: 14.6, lon: -61.0, tHours: 4, sailNm: 100, filmNm: 100 },
      ],
    };
    const nearMark = filmTimeWhileChapterSpeaks({ t: tB, chapter: ch, hold: true, clock });
    const nm = positionAt(clock, nearMark)?.sailNm;
    assert.ok(nearMark >= tA && nearMark <= tB);
    assert.ok(nm <= 100 - 0.06, `sailNm ${nm} trop près de la marque d'arrivée`);
    const capped = filmChapterPlayheadCapped({ t: tB + 60_000, chapter: ch, clock });
    assert.equal(capped.atCap, true);
    assert.ok(capped.t >= tA && capped.t <= tB);
    assert.match(hook, /filmTimeWhileChapterSpeaks/);
    assert.match(hook, /shouldApplyChapterFromClock/);
    assert.match(hook, /ingestHeld/);
    assert.match(hook, /isSpeaking\(\) && canLeadWithVoice\(\)/);
    const isoHeld = filmTimeWhileChapterSpeaks({
      t: tB + 60_000,
      chapter: { tA: new Date(tA).toISOString(), tB: new Date(tB).toISOString() },
      hold: true,
    });
    assert.equal(isoHeld, tB - FILM_CHAPTER_HOLD_EPS_MS);
    const voiceSrc = readFileSync(join(here, "useReplayVoice.js"), "utf8");
    assert.match(voiceSrc, /shouldStopSpeakingOnChapterChange/);
    assert.match(voiceSrc, /\[active, voice, chapterText, rate, lang\]/);
    assert.doesNotMatch(voiceSrc, /\[active, voice, chapterText, chapterIdx/);
  });

  it("Speaking vrai sans mot depuis > 2 s = voix coincée ; une frontière récente mène encore", () => {
    assert.equal(VOICE_LEAD_MS, 2500);
    assert.equal(VOICE_MS_PER_CHAR, 60);
    // Chrome laisse speaking à vrai alors que les frontières se sont tues.
    assert.equal(voiceStalled({
      chapterAgeMs: 5000, sinceBoundaryMs: 5000, speaking: true, hold: false,
    }), true);
    // Un hold sans mot nouveau n'est pas une voix vivante non plus.
    assert.equal(voiceStalled({
      chapterAgeMs: 5000, sinceBoundaryMs: 5000, speaking: false, hold: true,
    }), true);
    // Une frontière récente : la voix mène, silence court OK.
    assert.equal(voiceStalled({
      chapterAgeMs: 5000, sinceBoundaryMs: 200, speaking: true, hold: false,
    }), false);
    assert.equal(voiceStalled({
      chapterAgeMs: 5000, sinceBoundaryMs: 400, speaking: false, hold: true,
    }), false);
    // Avant le premier mot : attendre VOICE_LEAD_MS, pas couper à 2 s.
    assert.equal(voiceStalled({
      chapterAgeMs: FILM_VOICE_STALL_MS, sinceBoundaryMs: Infinity, speaking: true, hold: false,
    }), false);
    assert.equal(voiceStalled({
      chapterAgeMs: VOICE_LEAD_MS, sinceBoundaryMs: Infinity, speaking: true, hold: false,
    }), true);
    assert.equal(voiceStalled({
      chapterAgeMs: 500, sinceBoundaryMs: Infinity, speaking: false, hold: false,
    }), false);
  });

  it("Après abandon, le pas suivant avance charIdx et le film ne se termine pas", () => {
    const chapters = Array.from({ length: 7 }, (_, i) => ({
      tA: Date.parse("2026-05-15T08:00:00Z") + i * 4 * 3600000,
      tB: Date.parse("2026-05-15T08:00:00Z") + (i + 1) * 4 * 3600000,
      text: `${"Phrase une du chapitre. ".padEnd(80)}Phrase deux vers le lieu ${i}. `.padEnd(400, "x"),
      fromLat: 46 - i,
      fromLon: -1 - i,
      toLat: 45 - i,
      toLon: -2 - i,
      fromName: "La Rochelle",
      toName: "Ajaccio",
    }));
    const plan = filmPlan({ chapters, targetSeconds: 150 });
    assert.equal(spokenCharsSoFar(plan, 0, 231), 231);
    const stuck = abandonVoiceToLinear({ plan, chapterIdx: 0, charIdx: 231 });
    assert.equal(stuck.reached, 231);
    assert.ok(Math.abs(stuck.elapsed - voiceContinueElapsed(231)) < 1e-9);
    const a = linearFilmAt(stuck.elapsed, plan, stuck.cps);
    assert.ok(Math.abs(a.charIdx - 231) < 1.5, `reprise à ${a.charIdx}, pas un saut`);
    assert.equal(a.chapterIdx, 0);
    assert.equal(a.finish, false);
    const b = linearFilmAt(stuck.elapsed + 0.5, plan, stuck.cps);
    assert.ok(b.charIdx > a.charIdx || b.chapterIdx > a.chapterIdx, "le pas suivant avance charIdx");
    assert.equal(filmShouldFinish({
      voiceClock: false, speaking: false, voiceAllDone: false,
      linearFinish: a.finish, lastReached: a.lastReached,
    }), false);
    assert.equal(shouldReturnToLive({ voiceIncident: true }), false);
    assert.equal(shouldReturnToLive({ voiceIncident: true, filmFinished: true }), true);
  });

  it("La fin du film attend la fin de la clôture — budgetDone ne précède jamais voiceSpokenAll", () => {
    // Le temps-film a atteint la fin (linear.finish) mais la voix dit encore
    // « Aujourd'hui, le bateau est… » : pas de finish().
    assert.equal(filmShouldFinish({
      voiceClock: true, speaking: true, voiceAllDone: false,
      linearFinish: true, lastReached: true,
    }), false);
    // Même la voix « décrochée » qui parle encore n'est pas coupée.
    assert.equal(filmShouldFinish({
      voiceClock: false, speaking: true, voiceAllDone: false,
      linearFinish: true, lastReached: true,
    }), false);
    // La clôture dite en entier : le film finit.
    assert.equal(filmShouldFinish({
      voiceClock: true, speaking: false, voiceAllDone: true,
      linearFinish: false, lastReached: true,
    }), true);
    // Sans voix (mode linéaire), la fin linéaire garde la main.
    assert.equal(filmShouldFinish({
      voiceClock: false, speaking: false, voiceAllDone: false,
      linearFinish: true, lastReached: true,
    }), true);
    // Stop demandé : rien ne finit tout seul.
    assert.equal(filmShouldFinish({
      voiceClock: false, speaking: false, voiceAllDone: true,
      linearFinish: true, lastReached: true, stopping: true,
    }), false);
  });

  it("reprise d'onglet : rampe ≤ 2 s, aucun pas égal au saut", () => {
    const fromT = 1_000;
    const toT = fromT + 20 * 3600 * 1000;
    const gap = toT - fromT;
    const frames = 60;
    let prev = fromT;
    let maxStep = 0;
    for (let i = 1; i <= frames; i += 1) {
      const stepped = visibilityCatchupStep({
        fromT,
        toT,
        elapsedMs: (i / frames) * FILM_VISIBILITY_CATCHUP_MS,
        durationMs: FILM_VISIBILITY_CATCHUP_MS,
      });
      maxStep = Math.max(maxStep, Math.abs(stepped.t - prev));
      prev = stepped.t;
    }
    assert.ok(maxStep < gap / 2, `pas max ${maxStep} trop proche du saut ${gap}`);
    assert.ok(Math.abs(prev - toT) < 1);
    const mid = visibilityCatchupStep({
      fromT, toT, elapsedMs: 1000, durationMs: 2000,
    });
    assert.equal(mid.done, false);
    assert.ok(mid.t > fromT && mid.t < toT);
    const end = visibilityCatchupStep({
      fromT, toT, elapsedMs: 2000, durationMs: 2000,
    });
    assert.equal(end.done, true);
    assert.equal(end.t, toT);
  });
});

describe("Pilule Rédigé, hasWritten, étiquette", () => {
  it("hasWritten true → pilule active, étiquette Nemotron ; false → désactivée, règles", () => {
    const on = resolveServedFilm({
      hasWritten: true,
      source: WRITTEN_FILM_SOURCE,
      chapters: [{ text: "Le 15 mai, Berry-Mappemonde quitte La Rochelle.", anchors: [{ t: 0, i: 0 }] }],
    }, "written");
    assert.equal(on.hasWritten, true);
    assert.equal(on.effectiveStyle, "written");
    assert.equal(on.source, WRITTEN_FILM_SOURCE);
    assert.equal(writtenPillEnabled(on.hasWritten), true);
    assert.equal(filmSourceKey(on.source), "storySourceSuper");
    assert.equal(isWrittenFilmSource(on.source), true);

    const off = resolveServedFilm({ hasWritten: false, source: "rules" }, "written");
    assert.equal(off.hasWritten, false);
    assert.equal(off.effectiveStyle, "raw");
    assert.equal(off.source, "rules");
    assert.equal(writtenPillEnabled(off.hasWritten), true);
    assert.equal(writtenPillEnabled({ hasWritten: false, filmReady: true }), true);
    assert.equal(writtenPillEnabled({ hasWritten: false, customFilm: true }), false);
    assert.equal(writtenPillEnabled({ hasWritten: true, customFilm: true }), false);
    assert.equal(writtenPillEnabled({ hasWritten: false, customFilm: false }), true);
    assert.equal(filmSourceKey(off.source), "storySourceRules");
    assert.equal(filmSourceKey("nemotron-super-reviewed-ultra"), "storySourceSuperReviewed");
    assert.equal(filmSourceKey("nemotron-super", "nemotron-ultra"), "storySourceSuperReviewed");
    assert.equal(filmSourceKey("nemotron-super"), "storySourceSuper");
    assert.equal(filmSourceKey("nemotron-nano"), "storySourceNano");
    assert.equal(filmSourceKey("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"), "storySourceNano");
    assert.equal(en.storySourceNano, "Nemotron 3 Nano 30B · Token Factory");
    assert.equal(fr.storySourceNano, "Nemotron 3 Nano 30B · Token Factory");
    // Le palier write sert Super VL : « nemotron-super » sans modèle se lit Super VL.
    assert.equal(filmSourceKey("nemotron-super-vl"), "storySourceSuperVl");
    assert.equal(filmSourceKey("nemotron-super", "", "nvidia/Nemotron-3.5-Super-VL"), "storySourceSuper");
    assert.equal(filmSourceKey("nemotron-super", "", "nvidia/nemotron-3-super-120b-a12b"), "storySourceSuper120b");
    assert.equal(filmSourceKey("nemotron-super", "nemotron-ultra", "nvidia/nemotron-3-super-120b-a12b"), "storySourceSuper120bReviewed");
    assert.equal(filmSourceKey("nemotron-super", "", "nvidia/Nemotron-3_5-Lightning"), "storySourceLightning");
    assert.equal(en.filmModels, "Models");
    assert.equal(fr.filmModels, "Modèles");
    assert.equal(filmSourceKey("openrouter"), "storySourceOpenrouter");
    assert.equal(filmSourceKey("nvidia-gpt-oss-20b"), "storySourceNim");
    assert.match(en.storySourceSuper, /Nemotron 3\.5 Super VL/);
    assert.match(fr.storySourceSuper, /Nemotron 3\.5 Super VL/);
    assert.match(en.storySourceSuper120b, /Nemotron 3 Super 120B/);
    assert.match(en.storySourceSuper, /Token Factory/);
    assert.match(en.storySourceSuperReviewed, /Token Factory/);
    assert.match(en.storySourceSuperReviewed, /reviewed by Ultra/);
    assert.match(fr.storySourceSuperReviewed, /Token Factory/);
    assert.match(fr.storySourceSuperReviewed, /relu par Ultra/);
    assert.doesNotMatch(en.storySourceNim, /Token Factory/);
    assert.doesNotMatch(en.storySourceOpenrouter, /Token Factory/);
    assert.doesNotMatch(fr.storySourceNim, /Token Factory/);
    assert.doesNotMatch(fr.storySourceOpenrouter, /Token Factory/);
    assert.equal(en.ed2WritingNemotron, "Writing…");
    assert.equal(fr.ed2WritingNemotron, "Rédaction en cours…");
    assert.doesNotMatch(en.ed2WritingNemotron, /Nemotron|Token Factory|NIM|OpenRouter|Claude|Nebius/i);
    assert.doesNotMatch(fr.ed2WritingNemotron, /Nemotron|Token Factory|NIM|OpenRouter|Claude|Nebius/i);
    const served = resolveServedFilm({
      hasWritten: true,
      source: "nemotron-super",
      reviewedBy: "nemotron-ultra",
      model: "nvidia/nemotron-3-super-120b-a12b",
    }, "written");
    assert.equal(served.source, "nemotron-super");
    assert.equal(served.reviewedBy, "nemotron-ultra");
    assert.equal(served.model, "nvidia/nemotron-3-super-120b-a12b");

    const raw = resolveServedFilm({ hasWritten: false, source: "rules" }, "raw");
    assert.equal(raw.updateHasWritten, false);
    assert.equal(raw.effectiveStyle, "raw");
    assert.equal(filmRequestStyle("written"), "written");
    assert.equal(filmRequestStyle("raw"), "raw");
  });

  it("n'essaie pas Rédigé pour une route personnalisée et arrête un 405", () => {
    assert.equal(filmResponseShouldRetry(405), false);
    assert.equal(filmResponseShouldRetry(404), true);
    const hook = readFileSync(new URL("./useReplay.js", import.meta.url), "utf8");
    const styleHandler = hook.slice(hook.indexOf("const chooseFilmStyle"), hook.indexOf("return {\n    active,"));
    assert.match(styleHandler, /if \(!isOfficialFilmVoyage\(voyageId\)\)/);
    const probe = hook.slice(hook.indexOf("const probeWritten"), hook.indexOf("const load ="));
    assert.match(probe, /style !== "raw" \|\| !official/);
    assert.match(hook, /!filmResponseShouldRetry\(pack\?\.status\)/);
  });

  it("demande style=written, lit hasWritten / source / ancres, aucun LLM navigateur", () => {
    assert.match(hook, /filmRequestStyle\(filmStyle\)/);
    assert.match(hook, /style=\$\{style\}/);
    assert.match(hook, /style=written/);
    assert.match(hook, /style=written/);
    const chooseAt = hook.indexOf("const chooseFilmStyle");
    const chooseBlock = hook.slice(chooseAt, hook.indexOf("return {\n    active", chooseAt));
    assert.match(chooseBlock, /if \(filmWritingRef\.current\) return/);
    assert.match(chooseBlock, /if \(active && !hasWritten\) return/);
    assert.match(chooseBlock, /if \(active\) stop\(\)/);
    assert.match(chooseBlock, /filmWriteGenerationRef\.current/);
    assert.match(chooseBlock, /generation !== filmWriteGenerationRef\.current/);
    assert.match(chooseBlock, /filmWriteRequestRef\.current\?\.abort\(\)/);
    assert.match(chooseBlock, /setTimeout\(\(\) => controller\.abort\(\), 30_000\)/);
    assert.match(chooseBlock, /signal: controller\.signal/);
    assert.match(chooseBlock, /if \(generation === filmWriteGenerationRef\.current\)[\s\S]*filmWritingRef\.current = false/);
    assert.match(chooseBlock, /filmWritingRef\.current = true/);
    assert.match(chooseBlock, /filmWritingRef\.current = false/);
    assert.match(chooseBlock, /style=written/);
    assert.match(hook, /chooseFilmStyle/);
    assert.match(hook, /filmWritePollGenRef\.current \+= 1;\s+filmWritePollAbortRef\.current\?\.abort\(\);\s+filmWritePollAbortRef\.current = null;/);
    assert.match(hook, /const writeGen = \+\+filmWritePollGenRef\.current;/);
    assert.match(hook, /if \(writeGen !== filmWritePollGenRef\.current\) return;/);
    assert.match(hook, /\.catch\(\(\) => \{\s+if \(writeGen !== filmWritePollGenRef\.current\) return;\s+setFilmWriteError\(true\);\s+setFilmWriting\(false\);/);
    assert.match(hook, /\.finally\(\(\) => \{[\s\S]*?if \(writeGen === filmWritePollGenRef\.current\) \{\s+filmWriteStartingRef\.current = false;/);
    assert.match(hook, /finally \{\s+if \(gen === filmWritePollGenRef\.current\) \{\s+filmWriteStartingRef\.current = false;\s+\}\s+\}/);
    assert.match(hook, /filmWritePollAbortRef\.current = null;\s+filmWriteStartingRef\.current = false;/);
    assert.match(hook, /resolveServedFilm/);
    assert.match(hook, /probeWritten/);
    assert.match(hook, /applyResolvedMeta/);
    assert.match(hook, /data\?\.hasWritten/);
    assert.match(hook, /anchors du stock/);
    assert.doesNotMatch(hook, /Tavily|Nebius/i);
    assert.doesNotMatch(hook, /https?:\/\/\S*tokenfactory/i);
    assert.match(bar, /nemotron-super-token-factory|filmSourceKey/);
    assert.match(bar, /LlmSourceBadge/);
    assert.match(bar, /data-testid="film-source"/);
    assert.match(bar, /testId="film-source"/);
    assert.match(bar, /textOnly/);
    assert.match(bar, /ed2WritingNemotron/);
    assert.match(bar, /ed2WriteFailed/);
    const probeAt = hook.indexOf("const probeWritten");
    assert.ok(probeAt > 0);
    const probe = hook.slice(probeAt, probeAt + 900);
    assert.match(probe, /setFilmSource\(resolved\.source\)/);
    assert.match(probe, /setFilmReviewedBy\(resolved\.reviewedBy \|\| ""\)/);
    assert.doesNotMatch(bar, /filmStoryWrittenSoon/);
    assert.match(bar, /replay\.hasWritten/);
    assert.match(bar, /film-style-\$\{id\}/);
    assert.match(bar, /\["raw", "filmStoryRaw"\], \["written", "filmStoryWritten"\]/);
    assert.match(bar, /hidden=\{\(replay\.style \|\| "raw"\) !== "written" \|\| !replay\.hasWritten\}/);
  });

  it("signale l’indisponibilité seulement après l’échec de toute la cascade", () => {
    assert.match(hook, /data\?\.reason === "all-providers-failed"/);
    assert.match(hook, /setWrittenUnavailable\("unavailable"\)/);
    // RL191 (#191) on #159's async write: a network miss or an empty answer
    // flags the write error but never "unavailable".
    assert.match(hook, /\.catch\(\(\) => \{[^}]*?if \(generation === filmWriteGenerationRef\.current\) setWrittenUnavailable\(null\);/s);
    assert.match(hook, /if \(!data\) \{[^}]*?setWrittenUnavailable\(null\);/s);
    assert.doesNotMatch(hook, /if \(!data\) \{\s*setWrittenUnavailable\("unavailable"\)/);
    assert.match(hook, /setWrittenUnavailable\(data\?\.reason === "all-providers-failed" \? "unavailable" : null\)/);
    assert.match(hook, /writtenUnavailable,/);
    assert.match(app, /writtenUnavailable: replay\.writtenUnavailable/);
    assert.match(bar, /filmStoryWrittenUnavailable/);
    assert.match(bar, /role="status"/);
    assert.match(bar, /filmStoryWrittenRetry/);
    assert.match(bar, /if \(!replay\.active\) replay\.onStyle\?\.\("written"\)/);
    assert.match(hook, /setWrittenUnavailable\("unavailable"\)/);
    assert.equal(fr.filmStoryWrittenUnavailable, "Le film rédigé est momentanément indisponible.");
    assert.equal(en.filmStoryWrittenUnavailable, "The edited film is temporarily unavailable.");
    assert.match(bar, /<span role="status">\{t\("filmStoryWrittenUnavailable"\)\}<\/span>/);
  });
});

describe("Débit écrit stable, pas de sprint puis calage", () => {
  it("voix : charIdx dès la 1re phrase à FILM_ESTIMATE_CPS, jamais le budget", () => {
    assert.equal(filmScriptCharIdx({
      voiceClock: true, phraseOn: false, linearChar: 203,
    }), 0, "avant la 1re phrase : pas le sprint linéaire");
    const at10 = filmScriptCharIdx({
      voiceClock: true, phraseOn: true, phraseChar0: 0, phraseElapsedS: 10,
      sentenceEndChar: 800, chapterChars: 800, linearChar: 203,
    });
    const at20 = filmScriptCharIdx({
      voiceClock: true, phraseOn: true, phraseChar0: 0, phraseElapsedS: 20,
      sentenceEndChar: 800, chapterChars: 800, linearChar: 406,
    });
    const at30 = filmScriptCharIdx({
      voiceClock: true, phraseOn: true, phraseChar0: 0, phraseElapsedS: 30,
      sentenceEndChar: 800, chapterChars: 800, linearChar: 609,
    });
    const at40 = filmScriptCharIdx({
      voiceClock: true, phraseOn: true, phraseChar0: 0, phraseElapsedS: 40,
      sentenceEndChar: 800, chapterChars: 800, linearChar: 812,
    });
    assert.equal(at10, FILM_ESTIMATE_CPS * 10);
    assert.equal(at20, FILM_ESTIMATE_CPS * 20);
    const early = (at20 - at10) / 10;
    const late = (at40 - at30) / 10;
    assert.equal(filmCharRatesStable(early, late), true);
    assert.equal(filmCharRatesStable(20.3, 15.0), false);
    assert.match(hook, /filmScriptCharIdx/);
    assert.match(hook, /voiceMayLead/);
    assert.match(hook, /voiceFailedRef\.current = !voiceMayLead\(\)/);
    assert.match(readFileSync(join(here, "useReplayVoice.js"), "utf8"), /RC41/);
  });

  it("sans voix : un seul régime — FILM_ESTIMATE_CPS", () => {
    const a = filmScriptCharIdx({ voiceClock: false, linearChar: 150 });
    const b = filmScriptCharIdx({ voiceClock: false, linearChar: 300 });
    assert.equal(a, 150);
    assert.equal(b, 300);
    assert.equal(filmCharRatesStable(15, 15), true);
    const ended = filmScriptCharIdx({
      voiceClock: true, phraseOn: true, phraseEnded: true,
      phraseChar0: 0, phraseElapsedS: 40, sentenceEndChar: 120, linearChar: 600,
    });
    assert.equal(ended, 120, "fin de phrase : on tient l'ancre, on ne sprinte pas");
  });
});

describe("Bateau sur la phrase, pas à tB", () => {
  it("à charIdx au milieu d'un chapitre, la position est l'instant de la phrase, pas tB ni aujourd'hui", () => {
    const tA = Date.parse("2026-06-02T08:00:00Z");
    const tCape = Date.parse("2026-06-27T12:00:00Z");
    const tB = Date.parse("2026-07-15T16:00:00Z");
    const tToday = Date.parse("2026-10-16T14:00:00Z");
    const text = [
      "On 2 June the catamaran leaves Ajaccio.",
      "On 27 June the project Cape Verde sits twenty-eight miles to port.",
      "Arrival at Fort-de-France.",
    ].join(" ");
    const capeAt = text.indexOf("Cape Verde");
    const chapter = {
      tA,
      tB,
      text,
      chars: text.length,
      fromName: "Ajaccio",
      toName: "Fort-de-France",
      fromLat: 41.93,
      fromLon: 8.74,
      toLat: 14.59,
      toLon: -61.07,
      anchors: [
        { charIdx: 0, t: tA },
        { charIdx: capeAt, t: tCape },
        { charIdx: text.length, t: tB },
      ],
    };
    const plan = filmPlan({ chapters: [chapter], targetSeconds: 150 });
    const ch = plan.chapters[0];
    const clock = {
      t0: "2026-06-02T08:00:00Z",
      vertices: [
        { lat: 41.93, lon: 8.74, tHours: 0, sailNm: 0, filmNm: 0 },
        { lat: 16.9, lon: -25.0, tHours: (tCape - tA) / 3600000, sailNm: 1800, filmNm: 1800 },
        { lat: 14.59, lon: -61.07, tHours: (tB - tA) / 3600000, sailNm: 3600, filmNm: 3600 },
        { lat: -17.54, lon: -149.57, tHours: (tToday - tA) / 3600000, sailNm: 8000, filmNm: 8000 },
      ],
    };
    const mid = capeAt + 1;
    const racedT = tB;
    const { t: phraseT, pos } = filmBoatAtPhrase({
      clock, chapter: ch, charIdx: mid, plan, chapterIdx: 0,
      phraseEnded: false, t: racedT,
    });
    const atB = positionAt(clock, tB);
    const today = positionAt(clock, tToday);
    const atPhrase = positionAt(clock, plan.timeAt(0, mid));
    assert.ok(phraseT < tB - 1000, `playhead ${phraseT} encore à tB`);
    assert.ok(Math.abs(pos.lat - 16.9) < 3, `lat ${pos.lat} pas Cap-Vert`);
    assert.ok(Math.abs(pos.lat - atB.lat) > 1.5, "pas Fort-de-France (tB)");
    assert.ok(Math.abs(pos.lat - today.lat) > 8, "pas la position du jour");
    assert.ok(Math.abs(pos.lat - atPhrase.lat) < 0.5, "même instant que timeAt(charIdx)");
    assert.ok(filmBoatTimeAtPhrase({
      chapter: ch, charIdx: mid, plan, chapterIdx: 0, phraseEnded: false, t: racedT,
    }) < tB - 1000);

    const linear = linearFilmAt(128, plan);
    assert.ok(linear.charIdx > mid || linear.chapterIdx > 0 || linear.finish, "elapsed 128 s a filé");
    const fromElapsed = filmBoatTimeAtPhrase({
      chapter: ch, charIdx: mid, plan, chapterIdx: 0, phraseEnded: false,
      t: plan.timeAt(0, linear.charIdx) ?? tB,
    });
    assert.ok(fromElapsed < tB - 1000, "elapsed ne gagne pas sur la phrase");

    const stepped = stepFilmTime({
      t: tB,
      dt: 1 / 60,
      chapter: ch,
      plan,
      chapterIdx: 0,
      charIdx: mid,
      clock,
      voiceLed: false,
      phraseEnded: false,
    });
    assert.ok(stepped.t < tB - 1000, `stepFilmTime reste à tB (${stepped.t})`);
    const sent = sentenceSpan(ch, mid);
    assert.ok(stepped.t <= sent.endT + 1, "pas au-delà de la phrase en cours");
    assert.match(text.slice(sent.start, sent.end), /Cape Verde/);

    const lastLinear = linearFilmAt(400, plan);
    assert.equal(filmShouldFinish({
      voiceClock: false, speaking: false, voiceAllDone: false,
      linearFinish: lastLinear.finish, lastReached: lastLinear.lastReached,
    }), true, "le 2:30 finit encore");
    assert.equal(voiceStalled({
      chapterAgeMs: 5000, sinceBoundaryMs: 5000, speaking: true, hold: false,
    }), true, "VF1 : voix coincée toujours détectée");
    assert.match(hook, /filmBoatTimeAtPhrase/);
    assert.match(hook, /filmBoatAtPhrase/);
    assert.match(hook, /RC52/);
    assert.doesNotMatch(hook, /FILM_FLIP_HOLD_MS|panBy/);
  });
});

describe("useReplay — fin du film (fl1)", () => {
  const text = "Le 17 octobre, départ vers Mata-Utu : 1 642 milles, une dizaine de jours de mer. "
    + "Arrivée à Mata-Utu (Wallis-et-Futuna) le 27 octobre, à la marina de Fineveke. "
    + "Aujourd’hui, le bateau est à Mata-Utu (Wallis-et-Futuna). "
    + "Les escales à venir : Nouméa, Dzaoudzi, Tromelin, Saint-Gilles, Europa, La Rochelle.";
  const last = { text, chars: text.length };

  it("au tick de fin, le sous-titre montre la clôture et pas la 1re phrase du dernier chapitre", () => {
    const charIdx = filmEndCharIdx(last, 12, 13, 0);
    assert.equal(charIdx, text.length);
    const end = filmBarSubtitle({ chapterText: text, charIdx, pinned: false });
    assert.match(end.text, /Dzaoudzi/);
    const before = filmBarSubtitle({ chapterText: text, charIdx: 0, pinned: false });
    assert.doesNotMatch(before.text, /Dzaoudzi/);
  });

  it("hors dernier chapitre ou sans longueur, garde l'index courant", () => {
    assert.equal(filmEndCharIdx(last, 5, 13, 7), 7);
    assert.equal(filmEndCharIdx(null, 12, 13, 3), 3);
    assert.equal(filmEndCharIdx({ chars: 0 }, 12, 13, 4), 4);
  });
});
