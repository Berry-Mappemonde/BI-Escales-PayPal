import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FILM_BAR_HEIGHT_PX } from "../utils/filmBarLayout.js";

const here = dirname(fileURLToPath(import.meta.url));
const bar = readFileSync(join(here, "SimulationFilmBar.jsx"), "utf8");
const app = readFileSync(join(here, "../App.jsx"), "utf8");
const departure = readFileSync(join(here, "DepartureField.jsx"), "utf8");

function firstIndex(src, pattern) {
  const m = src.match(pattern);
  assert.ok(m, `motif introuvable : ${pattern}`);
  return m.index;
}

describe("film bar layout", () => {
  it("a une seule ListenButton, plus de replay-voice, testids conservés", () => {
    const listens = bar.match(/<ListenButton/g) || [];
    assert.equal(listens.length, 1, "un seul ListenButton dans la barre");
    assert.doesNotMatch(bar, /data-testid="replay-voice"/);
    assert.doesNotMatch(bar, /🔊/);
    assert.match(bar, /testId="listen"/);
    assert.match(bar, /data-testid="replay-start"/);
    assert.match(bar, /data-testid="replay-stop"/);
    assert.match(bar, /"view-suivre"/);
    assert.match(bar, /"view-tracer"/);
    assert.match(bar, /"mode-follow"/);
    assert.match(bar, /"mode-tracer"/);
    assert.match(bar, /data-testid="film-commands"/);
    assert.match(bar, /data-testid="film-subtitle"/);
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(bar, /data-testid="film-source"/);
    assert.match(bar, /data-testid="film-style"/);
    assert.match(bar, /data-testid="film-fullscreen"/);
    assert.match(bar, /data-drawing=\{drawing \? "1" : undefined\}/);
    assert.doesNotMatch(bar, /no playback, no speeds, no Suivre/);
  });

  it("La pilule de mode lit tracerButton, pas le libellé Simulation", () => {
    assert.match(bar, /t\("tracerButton"\)/);
    assert.match(bar, /t\("followExpeditionButton"\)/);
    assert.match(bar, /"view-tracer"/);
    assert.doesNotMatch(bar, />Simulation</);
    assert.doesNotMatch(bar, /["']Simulation["']/);
    assert.doesNotMatch(bar, /name:\s*["']Simulation["']/);
  });

  it("range les commandes : Masquer · Cinéma · Écouter · Suivre/Tracer · Revoir, lecture à droite", () => {
    const hideAt = firstIndex(bar, /t\("hideFilmBar"\)/);
    const cinemaAt = firstIndex(bar, /t\("cinema"\)/);
    const listenAt = firstIndex(bar, /testId="listen"/);
    const viewAt = firstIndex(bar, /data-testid="film-view-switch"/);
    const replayAt = firstIndex(bar, /data-testid="replay-controls"/);
    const playAt = firstIndex(bar, /onClick=\{onTogglePlay\}/);
    const speedsAt = firstIndex(bar, /data-testid="film-speed"/);
    assert.ok(hideAt < cinemaAt, "Masquer avant Cinéma");
    assert.ok(cinemaAt < listenAt, "Cinéma avant Écouter");
    assert.ok(listenAt < viewAt, "Écouter avant le commutateur de vue");
    assert.ok(viewAt < replayAt, "commutateur avant Revoir");
    assert.ok(replayAt < playAt, "Revoir à gauche, lecture à droite");
    assert.ok(playAt < speedsAt, "vitesse à droite, un bouton cyclique");
    assert.match(bar, /rounded-md text-\[9px\] font-semibold border whitespace-nowrap/);
  });

  it("garde Revoir au-dessus des commandes de lecture quand leurs zones se chevauchent", () => {
    const startAt = firstIndex(bar, /data-testid="replay-start"/);
    const startButton = bar.slice(bar.lastIndexOf("<button", startAt), bar.indexOf(">", startAt));
    assert.match(startButton, /className="relative z-10 /);
    assert.match(bar, /data-testid="prev-stop"/);
  });

  it("garde les commandes existantes hors le doublon son", () => {
    assert.match(bar, /t\("cinema"\)/);
    assert.match(bar, /t\("hideFilmBar"\)/);
    assert.match(bar, /t\("goToNextStop"\)/);
    assert.match(bar, /data-testid="stop-auto"/);
    assert.match(bar, /data-testid="film-speed"/);
    assert.match(bar, /nextFilmSpeed/);
    assert.doesNotMatch(bar, /PROFILES\.map/);
    assert.doesNotMatch(bar, /overflow-x-auto/);
    assert.match(bar, /onCinema/);
    assert.match(bar, /onFilmFullscreen/);
    assert.match(bar, /t\("filmFullscreen"\)/);
  });
});

describe("film bar", () => {
  it("n’a plus de légende des régimes, un prev-stop, hauteur contrat ≤ 96 px", () => {
    assert.doesNotMatch(bar, /t\("regimeLegend"\)/);
    assert.doesNotMatch(bar, /REGIME_COLORS/);
    assert.match(bar, /data-testid="regime-legend"/);
    assert.doesNotMatch(bar, /className="sr-only"/);
    assert.match(bar, /aria-label=\{regimeTitle\}/);
    assert.match(bar, /data-testid="prev-stop"/);
    assert.match(bar, /data-testid="next-stop"/);
    assert.match(bar, /t\("previousEscale"\)/);
    assert.match(bar, /data-testid="speed-regime-pill"/);
    assert.match(bar, /regimeTooltipHindcast/);
    const prevAt = firstIndex(bar, /data-testid="prev-stop"/);
    const nextAt = firstIndex(bar, /t\("goToNextStop"\)/);
    assert.ok(prevAt < nextAt, "Escale précédente à gauche de Prochaine escale");
    assert.ok(FILM_BAR_HEIGHT_PX.compact <= 96);
    assert.ok(FILM_BAR_HEIGHT_PX.controls <= 96);
  });

  it("montre Masquer la barre dès que onHideBar est fourni, Cinéma ou non", () => {
    assert.doesNotMatch(bar, /cinema && onHideBar/);
    assert.match(bar, /\{onHideBar \? \(/);
    assert.match(bar, /data-testid="hide-film-bar"/);
    assert.match(bar, /data-testid="show-film-bar"/);
    assert.match(app, /hideBar=\{hideFilmBar\}/);
    assert.doesNotMatch(app, /hideBar=\{cinemaMode && hideFilmBar\}/);
    assert.match(app, /onPrev=\{handleSimPrev\}/);
    assert.match(app, /canPrev=\{canPrevEscale/);
  });
});

describe("film bar", () => {
  it("info-bulle hindcast/prévision/climatologie sur la pilule, Suivre comme Simulation", () => {
    assert.match(bar, /title=\{regimeTitle\}/);
    assert.match(bar, /data-testid="speed-regime-pill" title=\{regimeTitle\}/);
    assert.match(bar, /regimeTooltipHindcast/);
    assert.match(bar, /regimeTooltipForecast/);
    assert.match(bar, /regimeTooltipClimatology/);
    assert.doesNotMatch(bar, /showPlaybackControls\s*\?\s*regimeTitle/);
    assert.doesNotMatch(bar, /isSimulation[\s\S]{0,40}regimeTitle/);
  });

  it("jambe terrestre en km par la route dans la barre", () => {
    assert.match(bar, /formatLandLegClock/);
    assert.match(bar, /isLandLegNames/);
    assert.match(bar, /data-testid="film-land-leg"/);
    assert.match(bar, /unitKm/);
    assert.match(bar, /byRoad/);
    assert.match(bar, /unitRoadHours/);
    assert.match(bar, /filmClockWithoutRoadNm\(clockLine\)/);
  });
});

describe("film bar", () => {
  it("garde 2:30 / 3:00 à côté de Revoir hors film, avec l'estimée", () => {
    const startAt = firstIndex(bar, /data-testid="replay-start"/);
    const durationAt = firstIndex(bar, /data-testid="film-duration"/);
    const stopAt = firstIndex(bar, /data-testid="replay-stop"/);
    assert.ok(stopAt < startAt, "Stop dans la branche film actif");
    assert.ok(startAt < durationAt, "2:30 / 3:00 à côté de Revoir l'expédition");
    const beforeStart = bar.slice(0, startAt);
    const afterStart = bar.slice(startAt);
    assert.doesNotMatch(beforeStart, /data-testid="film-duration"/);
    assert.match(afterStart, /data-testid="film-duration"/);
    const durBlock = bar.slice(durationAt, durationAt + 1600);
    assert.match(durBlock, /film-duration-estimate/);
    assert.match(durBlock, /=== sec \? 0 : sec/);
    assert.match(bar, /replay\.canStart \|\| replay\.active/);
    assert.match(bar, /disabled=\{!replay\.canStart\}/);
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(bar, /disabled:opacity-30 disabled:cursor-not-allowed/);
  });
});

describe("film bar", () => {
  it("garde 2:30 / 3:00 dans le cadre, sans « Récit : », date à la taille du format", () => {
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(bar, /data-testid="replay-start"/);
    assert.match(bar, /filmDuration150/);
    assert.match(bar, /filmDuration180/);
    assert.match(bar, /flex-wrap/);
    assert.match(bar, /overflow-hidden/);
    assert.doesNotMatch(bar, /overflow-x-auto/);
    assert.doesNotMatch(bar, /w-\[9\.75rem\]/);
    assert.doesNotMatch(bar, /filmStorySource/);
    assert.doesNotMatch(bar, /Récit :/);
    assert.match(bar, /data-testid="film-source"/);
    assert.match(bar, /testId="film-source"/);
    assert.match(bar, /hidden=\{\(replay\.style \|\| "raw"\) !== "written" \|\| !replay\.hasWritten\}/);
    assert.doesNotMatch(bar, /className="sr-only"/);
    assert.match(bar, /data-testid="replay-departure"/);
    assert.match(bar, /w-max/);
    assert.match(departure, /w-\[10ch\]/);
    assert.match(departure, /w-\[5ch\]/);
    assert.match(departure, /gap-\[1ch\]/);
    assert.match(departure, /w-max/);
    const startAt = firstIndex(bar, /data-testid="replay-start"/);
    const durationAt = firstIndex(bar, /data-testid="film-duration"/);
    assert.ok(startAt < durationAt, "2:30 / 3:00 à côté ou sous Revoir l'expédition");
    assert.match(
      bar,
      /flex flex-wrap items-center gap-1 min-w-0">[\s\S]*?data-testid="replay-start"/,
    );
  });
});

describe("crédits au-dessus de la barre", () => {
  it("App mesure la barre film et SimulationFilmBar expose la racine", () => {
    assert.match(app, /ref=\{filmBarRef\}/);
    assert.match(app, /ResizeObserver/);
    assert.match(app, /filmBarMeasuredPx/);
    assert.match(app, /measureFilmBarOccupiedPx/);
    assert.match(bar, /ref=\{rootRef\}/);
    assert.match(bar, /barRef/);
    assert.match(bar, /data-testid="film-bar"/);
  });
});

describe("plein écran film — sidebars masquées, pas démontées", () => {
  it("App pose .film-fullscreen et garde <Sidebar> / <ToolsSidebar> montés", () => {
    assert.match(app, /film-fullscreen/);
    assert.match(app, /setFilmFullscreen/);
    assert.match(app, /<Sidebar[\s\S]*open=\{sidebarOpen\}/);
    assert.match(app, /<ToolsSidebar[\s\S]*open=\{toolsOpen\}/);
    assert.doesNotMatch(app, /\{[^}]*filmFullscreen[^}]*&&\s*<Sidebar/);
    assert.doesNotMatch(app, /\{[^}]*!filmFullscreen[^}]*&&\s*<Sidebar/);
  });
});
