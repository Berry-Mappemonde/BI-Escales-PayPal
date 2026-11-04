import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import {
  clockRegimeText,
  clockWeatherTooltip,
  nextFilmSpeed,
  PROFILES,
  weatherUsesGfs,
} from "./filmBarClock.js";

const here = dirname(fileURLToPath(import.meta.url));
const bar = readFileSync(join(here, "SimulationFilmBar.jsx"), "utf8");

const DICT = {
  clockRegimeHindcast: "hindcast",
  clockRegimeRealUntil: "réel jusqu'au {date}",
  clockRegimeForecast: "prévision",
  clockRegimeClimatology: "climatologie",
  clockWeatherGfs: "GFS",
  clockWeatherClimoGfs: "climatologie + GFS",
  clockRegimeSources: "{n} sources ±{spread} kn",
  clockRegimeSourcesPlain: "{n} sources",
};

function t(key, vars = {}) {
  return Object.entries(vars).reduce(
    (s, [k, v]) => s.replace(`{${k}}`, v),
    DICT[key] ?? key,
  );
}

describe("barre film — vitesse cyclique", () => {
  it("annonce l’état du chargement du film et propose une reprise", () => {
    assert.match(bar, /data-testid="film-load-status"[\s\S]*?role=\{replay\.writtenUnavailable \? undefined : "status"\}/);
    assert.match(bar, /className="flex min-w-0 max-w-full items-center gap-1/);
    assert.match(bar, /className="min-w-0 truncate"/);
    assert.match(bar, /data-testid="film-load-retry"/);
    assert.match(bar, /\["empty", "absent", "timeout", "stale"\]/);
    assert.match(bar, /animate-spin/);
  });

  it("4 clics : réel → lecture → normale → accélérée → réel", () => {
    assert.deepEqual(PROFILES.map((p) => p.id), ["real", "read", "normal", "fast"]);
    let id = "real";
    id = nextFilmSpeed(id);
    assert.equal(id, "read");
    id = nextFilmSpeed(id);
    assert.equal(id, "normal");
    id = nextFilmSpeed(id);
    assert.equal(id, "fast");
    id = nextFilmSpeed(id);
    assert.equal(id, "real");
  });

  it("un seul bouton de vitesse, plus de pilules", () => {
    assert.equal((bar.match(/data-testid="film-speed"/g) || []).length, 1);
    assert.doesNotMatch(bar, /PROFILES\.map/);
    assert.match(bar, /onClick=\{\(\) => onProfile\(nextFilmSpeed\(profile\)\)\}/);
  });
});

describe("barre film — film officiel indisponible", () => {
  it("explique l’état vide dans la langue active au lieu d’annoncer une préparation", () => {
    const unavailableBranch = bar.slice(bar.indexOf("replay?.unavailable"));
    assert.match(unavailableBranch, /title=\{t\("replayUnavailable"\)\}/);
    assert.match(unavailableBranch, /aria-label=\{`\$\{t\("replayStart"\)\}: \$\{t\("replayUnavailable"\)\}`\}/);
    assert.match(unavailableBranch, /<span role="status"[\s\S]*?\{t\("replayUnavailable"\)\}/);
    assert.notEqual(en.replayUnavailable, en.replayPreparing);
    assert.notEqual(fr.replayUnavailable, fr.replayPreparing);
    assert.match(en.replayUnavailable, /^The official expedition film is unavailable right now\.$/);
    assert.match(fr.replayUnavailable, /^Le film officiel de l’expédition est momentanément indisponible\.$/);
  });
});

describe("badge de modèle par chapitre", () => {
  it("n'affiche le badge qu'avec une provenance explicite du chapitre actif", () => {
    assert.match(bar, /replay\?\.chapterProvenance\?\.model && replay\?\.chapterProvenance\?\.source/);
    assert.match(bar, /source=\{replay\.chapterProvenance\.source\}/);
    assert.match(bar, /replay\.chapterProvenance\.model\)/);
    assert.match(bar, /replay\.chapterProvenance\.tier/);
    assert.ok(bar.includes("${replay.chapterProvenance.model} · ${replay.chapterProvenance.tier}"));
    assert.match(bar, /testId="film-chapter-served-model"/);
    assert.doesNotMatch(bar, /receipt\.models.*chapterProvenance/s);
  });
});

describe("barre film — noms accessibles des commandes", () => {
  it("nomme les boutons de progression, événements et lecture/pause", () => {
    assert.match(bar, /aria-label=\{showPlaybackControls \? t\("filmScrub"\) : undefined\}/);
    assert.match(bar, /aria-label=\{ev\.phrase \|\| ev\.type\}/);
    assert.match(bar, /aria-label=\{playing \? t\("pause"\) : t\("play"\)\}/);
    assert.match(bar, /aria-label=\{t\("showFilmBar"\)\}/);
  });
});

describe("barre film — pilule Rédigé sur une route personnalisée", () => {
  it("désactive la pilule et explique la restriction en français et en anglais", () => {
    assert.match(bar, /writtenPillEnabled\(\{ customFilm: replay\.customFilm \}\)/);
    assert.match(bar, /disabled=\{id === "written" && !writtenPillEnabled/);
    assert.match(bar, /aria-disabled=\{locked\}/);
    assert.match(bar, /t\("filmStoryWrittenCustomUnavailable"\)/);
    assert.notEqual(fr.filmStoryWrittenCustomUnavailable, en.filmStoryWrittenCustomUnavailable);
    assert.match(fr.filmStoryWrittenCustomUnavailable, /route personnalisée/);
    assert.match(en.filmStoryWrittenCustomUnavailable, /custom route/);
  });
});

describe("barre film — libellé météo du point", () => {
  it("climatology + weatherLine global + sources vides → climatologie seule", () => {
    assert.equal(
      clockRegimeText({
        regime: "climatology",
        sources: [],
        weatherLine: "GFS + GFS-Wave (Open-Meteo)",
        t,
      }),
      "climatologie",
    );
    assert.equal(
      weatherUsesGfs({
        regime: "climatology",
        sources: [],
        weatherLine: "GFS + GFS-Wave (Open-Meteo)",
      }),
      false,
    );
  });

  it("climatology + sources om-forecast → climatologie + GFS", () => {
    assert.equal(
      clockRegimeText({
        regime: "climatology",
        sources: ["om-forecast"],
        weatherLine: "",
        t,
      }),
      "climatologie + GFS",
    );
    assert.equal(
      weatherUsesGfs({ regime: "climatology", sources: ["om-forecast"] }),
      true,
    );
  });

  it("un seul : climatologie, ou GFS, ou hindcast (N sources ±spread inchangé)", () => {
    assert.equal(
      clockRegimeText({ regime: "climatology", sources: [], weatherLine: "", t }),
      "climatologie",
    );
    assert.equal(
      clockRegimeText({
        regime: "forecast",
        sources: ["om-forecast"],
        weatherLine: "GFS + GFS-Wave (Open-Meteo)",
        t,
      }),
      "GFS",
    );
    const hindcast = clockRegimeText({
      regime: "hindcast",
      sources: ["om-era5"],
      spread: 1.5,
      t,
      lang: "fr",
    });
    assert.match(hindcast, /hindcast/);
    assert.match(hindcast, /1 sources/);
    assert.match(hindcast, /±1[,.]5 kn/);
    assert.equal(weatherUsesGfs({ regime: "climatology", sources: [], weatherLine: "" }), false);
    assert.equal(weatherUsesGfs({ regime: "forecast", sources: [], weatherLine: "" }), true);
  });

  it("détail des modèles en info-bulle, pas dans le libellé", () => {
    const both = clockRegimeText({
      regime: "climatology",
      sources: ["om-forecast"],
      weatherLine: "GFS + GFS-Wave (Open-Meteo)",
      t,
    });
    assert.equal(both, "climatologie + GFS");
    assert.doesNotMatch(both, /GFS-Wave|Open-Meteo|sources/);
    const tip = clockWeatherTooltip({
      sources: ["atlas"],
      weatherLine: "GFS + GFS-Wave (Open-Meteo)",
      regimeTitle: "hindcast · prévision · climatologie",
      t,
    });
    assert.match(tip, /GFS-Wave/);
    assert.match(tip, /Open-Meteo/);
  });

  it("weather-line reste vide ; weatherUsesGfs n'ouvre plus weatherLine", () => {
    const clockSrc = readFileSync(join(here, "filmBarClock.js"), "utf8");
    assert.doesNotMatch(clockSrc, /\/gfs\/i\.test\(weatherLine\)/);
    assert.match(bar, /<span data-testid="weather-line" className="text-cyan-200\/85"><\/span>/);
  });
});

describe("barre film — sous-titre = phrase en cours", () => {
  it("garde le sous-titre et met le lieu en avant, sans rangée ajoutée", () => {
    assert.match(bar, /data-testid="film-subtitle"/);
    assert.match(bar, /data-testid="film-subtitle-place"/);
    assert.match(bar, /filmSubtitleHighlight/);
    assert.match(bar, /replay\?\.active \|\| replay\?\.subtitle/);
    assert.equal((bar.match(/data-testid="film-subtitle"/g) || []).length, 1);
  });
});

describe("barre film — pilules et durée estimée", () => {
  it("garde les pilules focusables pendant la lecture et explique le verrou", () => {
    assert.match(bar, /aria-disabled=\{locked\}/);
    assert.match(bar, /filmStoryLockedPlaying/);
    assert.match(bar, /if \(locked\) return/);
    assert.doesNotMatch(bar, /\sdisabled=\{locked\}/);
  });

  it("garde 2:30 / 3:00 et l'estimée hors film, aucune cochée par défaut", () => {
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(bar, /filmDuration150/);
    assert.match(bar, /filmDuration180/);
    assert.match(bar, /data-testid="film-duration-estimate"/);
    assert.match(bar, /replay\.canStart \|\| replay\.active/);
    assert.match(bar, /\{replay\.active \? \(/);
    assert.doesNotMatch(bar, /calibrateRate/);
  });

  it("pendant le film : les pilules restent, boutons disabled / opacity", () => {
    assert.match(bar, /data-testid="film-duration"/);
    assert.match(bar, /\{\.\.\.\(replay\.active \? \{ "data-testid": undefined \} : \{\}\)\}/);
    assert.match(bar, /replay\.canStart \|\| replay\.active/);
    const lockAt = bar.indexOf('data-testid="film-duration"');
    assert.ok(lockAt >= 0);
    const durBlock = bar.slice(lockAt, lockAt + 1800);
    assert.match(durBlock, /disabled=\{Boolean\(replay\.active\)\}/);
    assert.match(durBlock, /aria-disabled=\{Boolean\(replay\.active\)\}/);
    assert.match(durBlock, /disabled:opacity-30 disabled:cursor-not-allowed/);
    assert.match(durBlock, /data-testid="film-duration-estimate"/);
    assert.match(bar, /data-testid="replay-stop"/);
    assert.doesNotMatch(bar, /calibrateRate/);
  });
});

describe("barre film — réel jusqu'au <date>", () => {
  it("hindcast + realUntil → « réel jusqu'au 9 oct. », sources conservées", () => {
    const label = clockRegimeText({
      regime: "hindcast",
      sources: ["om-era5"],
      realUntil: "2026-10-09",
      t,
      lang: "fr",
    });
    assert.match(label, /^réel jusqu'au 9 oct\./);
    assert.match(label, /1 sources?/);
  });

  it("hindcast sans realUntil → « hindcast » comme avant ; sans realUntil rien ne change", () => {
    const label = clockRegimeText({ regime: "hindcast", sources: [], t, lang: "fr" });
    assert.equal(label, "hindcast");
    assert.equal(
      clockRegimeText({ regime: "climatology", sources: [], t }),
      "climatologie",
    );
  });

  it("climatologie d'une horloge à part réelle → suffixe « réel jusqu'au … »", () => {
    assert.equal(
      clockRegimeText({ regime: "climatology", sources: [], realUntil: "2026-10-09", t, lang: "fr" }),
      "climatologie · réel jusqu'au 9 oct.",
    );
  });

  it("la barre passe clock.realUntil au libellé", () => {
    assert.match(bar, /realUntil: clock\?\.realUntil/);
  });
});
