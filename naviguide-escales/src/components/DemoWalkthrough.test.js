import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  DEMO_STEP_IDS, DEMO_TOUR_TARGETS, TOUR_DEFAULT_MODELS, TOUR_EDITED_WAIT_MS, describeModelRoles, getDemoSteps, modelDisplayName,
  tourEditedOffer, tourEditedStep, wantsTourFromUrl,
  computePanelPosition, computeArrowDirection, getStagePadding,
} from "./demoWalkthrough.js";
import { readFileSync } from "node:fs";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";

const tr = (dict) => (key, vars = {}) => Object.entries(vars).reduce(
  (s, [k, v]) => s.replace(`{${k}}`, v),
  dict[key] ?? en[key] ?? key,
);

describe("visite guidée des juges", () => {
  it("8 étapes stables, chaque texte vient d'une clé demo* (fr et en)", () => {
    for (const dict of [en, fr]) {
      for (const opts of [{}, { custom: true }, { replayState: "ready" }, { replayState: "playing" }]) {
        const steps = getDemoSteps(tr(dict), opts);
        assert.deepEqual(steps.map((s) => s.id), DEMO_STEP_IDS);
        for (const s of steps) {
          assert.ok(s.title && !/^demo|^replay/.test(s.title), `titre traduit : ${s.id}`);
          assert.ok(s.body && !/^demo/.test(s.body), `texte traduit : ${s.id}`);
        }
      }
    }
  });

  it("titre de l'étape film = replayStart, comme la barre du film", () => {
    assert.equal(getDemoSteps(tr(fr)).find((s) => s.id === "replay").title, fr.replayStart);
    assert.equal(getDemoSteps(tr(en)).find((s) => s.id === "replay").title, en.replayStart);
  });

  it("route de l'utilisateur : ni « film officiel » ni « suit la route Berry-Mappemonde »", () => {
    for (const dict of [en, fr]) {
      for (const replayState of ["ready", "unavailable", "playing"]) {
        const steps = getDemoSteps(tr(dict), { custom: true, replayState });
        const all = steps.map((s) => s.body).join(" ");
        assert.doesNotMatch(all, /film officiel|official film|stock officiel|official store/i);
        assert.doesNotMatch(steps.find((s) => s.id === "live").body, /^La carte suit la route Berry|^The map follows the Berry/);
        assert.doesNotMatch(steps.find((s) => s.id === "trace").body, /Cliquez sur la carte|Click the map/);
      }
    }
  });

  it("trois états du film : prêt, en lecture, indisponible (sans faux film)", () => {
    const body = (replayState) => getDemoSteps(tr(fr), { replayState }).find((s) => s.id === "replay").body;
    assert.match(body("ready"), /bouton ci-dessous/);
    assert.equal(body("playing"), fr.demoPlaying);
    assert.doesNotMatch(body("playing"), /bouton ci-dessous/);
    assert.match(body("unavailable"), /faux film/);
  });

  it("formulation honnête de la position (calculée, pas observée)", () => {
    assert.doesNotMatch(fr.demoWelcomeBody, /données réelles/);
    assert.match(fr.demoWelcomeBody, /calculée à partir du plan officiel/);
    assert.match(en.demoWelcomeBody, /computed from the official plan/);
  });

  it("un seul nom en anglais, et aucun bouton qui ressemble à Terminer / Finish", () => {
    const enDemo = Object.entries(en).filter(([k]) => k.startsWith("demo")).map(([, v]) => v).join(" ");
    assert.doesNotMatch(enDemo, /walkthrough|guided demo/i);
    for (const dict of [en, fr]) {
      for (const k of ["demoEnd", "demoExit", "demoClose", "demoPrev", "demoNext"]) {
        assert.doesNotMatch(dict[k], /terminer|finish/i, `${k} ne doit pas matcher les specs du tracé`);
      }
    }
  });

  it("panneau du côté opposé au panneau que l'étape ouvre", () => {
    const side = Object.fromEntries(getDemoSteps(tr(en)).map((s) => [s.id, s.side]));
    assert.equal(side.layers, "left");
    assert.equal(side.trace, "left");
    assert.equal(side.briefing, "right");
  });

  it("étape 2 « Qui fait quoi » : Nemotron, Token Factory et Tavily nommés (fr et en)", () => {
    assert.equal(DEMO_STEP_IDS.length, 8);
    assert.equal(DEMO_STEP_IDS[1], "models");
    for (const dict of [en, fr]) {
      const step = getDemoSteps(tr(dict)).find((s) => s.id === "models");
      assert.ok(step, "étape models présente");
      assert.match(step.body, /Nemotron/);
      assert.match(step.body, /Nebius Token Factory/);
      assert.match(dict.demoModelsTavily, /^Tavily/);
      assert.equal(step.side, "right");
    }
    assert.match(en.demoModelsTitle, /^Who does what/);
    assert.match(fr.demoModelsTitle, /^Qui fait quoi/);
  });

  it("statut en direct : noms lus dans configuredModels, compteurs du jour", () => {
    const llm = {
      configuredModels: {
        nano: "nvidia/Nemotron-3_5-Lightning",
        fast: "nvidia/Nemotron-3_5-Lightning",
        write: "nvidia/Nemotron-3.5-Super-VL",
        deep: "nvidia/Nemotron-3-Ultra-550b-a55b",
        judge: "nvidia/Nemotron-3-Ultra-550b-a55b",
      },
      nano: { calls: 2 }, fast: { calls: 3 }, write: { calls: 1 }, deep: { calls: 0 }, judge: { calls: 4 },
      tavily: { calls: 5, credits: 5 },
    };
    const out = describeModelRoles(llm, tr(en));
    assert.equal(out.live, true);
    assert.deepEqual(out.rows.map((r) => r.id), ["quick", "write", "deep", "tavily"]);
    assert.match(out.rows[0].text, /^Nemotron 3\.5 Lightning: /);
    assert.match(out.rows[1].text, /^Nemotron 3\.5 Super VL: writes the film/);
    assert.match(out.rows[2].text, /^Nemotron 3 Ultra: edits and re-reads/);
    assert.match(out.rows[3].text, /^Tavily: /);
    assert.equal(out.today, "Today on this server: 10 Nemotron calls, 5 Tavily searches.");
  });

  it("override serveur : un id inconnu reste brut, deux modèles d'un même rôle sont tous deux cités", () => {
    const out = describeModelRoles({ configuredModels: { nano: "nvidia/nemotron-3-nano-30b-a3b", write: "acme/x-1" } }, tr(fr));
    assert.match(out.rows[0].text, /^Nemotron 3 Nano 30B \+ Nemotron 3\.5 Lightning : /);
    assert.match(out.rows[1].text, /^acme\/x-1 : /);
    assert.equal(modelDisplayName(""), "");
  });

  it("sans statut : défauts du code signalés (live=false), aucun compteur inventé", () => {
    const out = describeModelRoles(null, tr(en));
    assert.equal(out.live, false);
    assert.equal(out.today, null);
    assert.match(out.rows[1].text, /^Nemotron 3\.5 Super VL/);
    assert.equal(TOUR_DEFAULT_MODELS.write, "nvidia/Nemotron-3.5-Super-VL");
  });

  it("lien profond ?tour=1", () => {
    assert.equal(wantsTourFromUrl("?tour=1"), true);
    assert.equal(wantsTourFromUrl("?lang=en&tour=true"), true);
    assert.equal(wantsTourFromUrl("?tour=0"), false);
    assert.equal(wantsTourFromUrl(""), false);
    assert.equal(wantsTourFromUrl(undefined), false);
  });

  it("C4-c : phrase-thèse à l'étape « Qui fait quoi » (fr et en)", () => {
    assert.equal(en.demoModelsThesis, "The rules decide when, Nemotron decides how, sources decide what is true.");
    assert.match(fr.demoModelsThesis, /^Les règles décident quand, Nemotron décide comment, les sources décident de ce qui est vrai\.$/);
    const jsx = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
    assert.match(jsx, /data-testid="demo-models-thesis"[^>]*>\{t\("demoModelsThesis"\)\}/);
  });

  it("C2-b : bouton Rédigé seulement si le rédigé existe ; sinon repli Brut annoncé", () => {
    assert.equal(tourEditedOffer({ hasWritten: true }), "edited");
    assert.equal(tourEditedOffer({ hasWritten: false }), "fallback");
    assert.equal(tourEditedOffer(), "fallback");
    assert.equal(en.demoPlayEdited, "Play the Edited film");
    assert.equal(fr.demoPlayEdited, "Lire le film Rédigé");
    for (const dict of [en, fr]) {
      for (const k of ["demoEditedLoading", "demoEditedBy", "demoEditedFallback", "demoEditedFallbackCustom", "demoEditedFellBack"]) {
        assert.ok(dict[k], `${k} présent`);
      }
      assert.match(dict.demoEditedBy, /\{source\}/);
      // Repli annoncé : le texte nomme le film Brut et ne promet pas de rédigé.
      assert.match(dict.demoEditedFallback, /Brut|Raw/);
      assert.match(dict.demoEditedFellBack, /Brut|Raw/);
      // Aucune promesse d'IA absente : le Brut est « formulé par les règles », jamais « sans IA ».
      assert.doesNotMatch(dict.demoEditedFallback, /sans IA|no AI/i);
    }
    assert.match(en.demoEditedFallback, /Edited pill/);
    assert.match(fr.demoEditedFallback, /pastille Rédigé/);
  });

  it("C2-b : un clic Rédigé attend le plan rédigé, ou retombe sur le Brut", () => {
    const base = { pending: true, active: false, remoteStatus: "ready", canStart: true };
    assert.equal(tourEditedStep({ ...base, pending: false, filmStyle: "written", loadedStyle: "written" }), "idle");
    assert.equal(tourEditedStep({ ...base, active: true, filmStyle: "written", loadedStyle: "written" }), "idle");
    // Juste après le clic : style Rédigé demandé, plan Brut encore chargé → attendre.
    assert.equal(tourEditedStep({ ...base, filmStyle: "written", loadedStyle: "raw" }), "wait");
    assert.equal(tourEditedStep({ ...base, filmStyle: "written", loadedStyle: "written", remoteStatus: "pending" }), "wait");
    assert.equal(tourEditedStep({ ...base, filmStyle: "written", loadedStyle: "written", canStart: false }), "wait");
    assert.equal(tourEditedStep({ ...base, filmStyle: "written", loadedStyle: "written" }), "edited");
    // Le serveur sert le Brut à la demande Rédigé : attendre le rechargement Brut, puis le lancer.
    assert.equal(tourEditedStep({ ...base, filmStyle: "raw", loadedStyle: "mismatch" }), "wait");
    assert.equal(tourEditedStep({ ...base, filmStyle: "raw", loadedStyle: "raw" }), "raw");
    assert.equal(tourEditedStep(), "idle");
    assert.ok(TOUR_EDITED_WAIT_MS >= 30_000 && TOUR_EDITED_WAIT_MS <= 60_000);
  });

  it("R41b/c/f : retries use an attempt count, resize restarts tracking, and panel controls are keyboard operable", () => {
    const jsx = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
    assert.match(jsx, /let attempts = 0;[\s\S]*?\+\+attempts < (?:30|PULSE_MAX_ATTEMPTS)/);
    assert.match(jsx, /const onResize = \(\) => \{[\s\S]*?tries = 0;[\s\S]*?requestAnimationFrame\(track\)/);
    assert.match(jsx, /allowKeyboardControl: false/);
    assert.match(jsx, /headingRef\.current\?\.focus/);
    assert.match(jsx, /demo-walkthrough-prev[\s\S]*?onClick=\{\(\) => goTo\(index - 1\)\}/);
    assert.match(jsx, /demo-walkthrough-next[\s\S]*?onClick=\{\(\) => goTo\(index \+ 1\)\}/);
    assert.match(jsx, /window\.addEventListener\("keydown", onEsc, true\)/);
    assert.doesNotMatch(jsx, /tries < 600/);
    assert.match(jsx, /className="min-h-0 flex-1 overflow-y-auto"/);
  });
});

it("C3 : invariants front visite + journal (sans 97f061c0)", () => {
  const tour = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
  const chat = readFileSync(new URL("./LogbookChat.jsx", import.meta.url), "utf8");
  assert.match(tour, /naviguide-tour-pulse/);
  assert.match(tour, /data-arrow/);
  assert.match(tour, /step\?\.id !== "models"/);
  assert.match(tour, /fetchStatus\(\)/);
  assert.match(tour, /naviguide-demo-launch fixed right-3 top-14/);
  assert.match(chat, /LOGBOOK_EXAMPLES/);
  assert.match(chat, /logbook-chat-web-sources/);
  assert.match(chat, /data-tour="logbook"/);
  assert.match(chat, /logbook-chat-send/);
});

it("R13 : piège Tab documenté dans le panneau visite", () => {
  const src = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
  assert.match(src, /R13 : Tab[\s\S]*e\.key !== "Tab"/);
});

it("R11 : onResize relance le suivi du projecteur", () => {
  const src = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
  assert.match(src, /onResize[\s\S]*tries = 0[\s\S]*requestAnimationFrame\(track\)/);
});

it("R9 : le cleanup du projecteur appelle destroy() au changement d'étape", () => {
  const src = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
  assert.match(
    src,
    /return \(\) => \{[\s\S]*cancelAnimationFrame\(raf\)[\s\S]*driverRef\.current\?\.destroy\(\)/,
    "le cleanup rAF doit détruire driver.js",
  );
});

it("driver.js : chaque étape a un élément réel ou aucun (pas de cible inventée)", () => {
  assert.deepEqual(Object.keys(DEMO_TOUR_TARGETS), DEMO_STEP_IDS);
  assert.equal(DEMO_TOUR_TARGETS.briefing, '[data-tour="logbook"]');
  assert.equal(DEMO_TOUR_TARGETS.replay, '[data-tour="film"]');
  assert.equal(DEMO_TOUR_TARGETS.live, ".leaflet-container");
});

describe("placement logic (exported from demoWalkthrough.js)", () => {
  const anchorTop = { top: 100, bottom: 150, height: 50 };
  const anchorBottom = { top: 600, bottom: 650, height: 50 };

  it("computePanelPosition returns undefined for null anchor or mobile width", () => {
    assert.equal(computePanelPosition(null, "replay", 1024, 768), undefined);
    assert.equal(computePanelPosition(anchorTop, "replay", 500, 768), undefined);
  });

  it("computePanelPosition for replay step with anchor in bottom half returns bottom position", () => {
    const pos = computePanelPosition(anchorBottom, "replay", 1024, 768);
    assert.ok(pos && pos.bottom && pos.top === "auto");
    const bottom = Number(pos.bottom.replace("px", ""));
    assert.ok(bottom > 768 - 600);
  });

  it("R12 : replay borde le panneau haut quand la hauteur mesurée dépasse l'écran", () => {
    const tallPanel = 500;
    const minTop = 56;
    const minBottom = 56;
    for (const innerHeight of [400, 600, 900]) {
      const pos = computePanelPosition(anchorBottom, "replay", 1024, innerHeight, tallPanel);
      assert.ok(pos?.bottom, `replay bottom attendu pour h=${innerHeight}`);
      const bottom = Number(pos.bottom.replace("px", ""));
      const effective = Math.min(tallPanel, Math.max(120, innerHeight - minTop - minBottom));
      const topEdge = innerHeight - bottom - effective;
      assert.ok(topEdge >= minTop, `haut du panneau >= MIN_TOP pour h=${innerHeight}, got ${topEdge}`);
    }
  });

  it("computePanelPosition for replay step with anchor in top half returns top position", () => {
    const pos = computePanelPosition(anchorTop, "replay", 1024, 768);
    assert.ok(pos && pos.top && !pos.bottom);
  });

  it("computePanelPosition for other steps returns clamped top position", () => {
    const pos = computePanelPosition(anchorTop, "welcome", 1024, 768);
    assert.ok(pos && pos.top);
    const top = Number(pos.top.replace("px", ""));
    assert.ok(top >= 56 && top <= 768 - 420);
  });

  it("computeArrowDirection returns undefined for null anchor or mobile width", () => {
    assert.equal(computeArrowDirection(null, "replay", 1024, 768), undefined);
    assert.equal(computeArrowDirection(anchorTop, "replay", 500, 768), undefined);
  });

  it("computeArrowDirection for replay step with anchor in bottom half returns 'down'", () => {
    assert.equal(computeArrowDirection(anchorBottom, "replay", 1024, 768), "down");
  });

  it("computeArrowDirection for replay step with anchor in top half returns 'down'", () => {
    assert.equal(computeArrowDirection(anchorTop, "replay", 1024, 768), "down");
  });

  it("getStagePadding returns 14 for trace step, 6 for others", () => {
    assert.equal(getStagePadding("trace"), 14);
    assert.equal(getStagePadding("welcome"), 6);
    assert.equal(getStagePadding("models"), 6);
    assert.equal(getStagePadding("live"), 6);
    assert.equal(getStagePadding("replay"), 6);
  });
});

it("driver.js : chaque étape a un élément réel ou aucun (pas de cible inventée)", () => {
  assert.deepEqual(Object.keys(DEMO_TOUR_TARGETS), DEMO_STEP_IDS);
  assert.equal(DEMO_TOUR_TARGETS.briefing, '[data-tour="logbook"]');
  assert.equal(DEMO_TOUR_TARGETS.replay, '[data-tour="film"]');
  assert.equal(DEMO_TOUR_TARGETS.live, ".leaflet-container");
});

describe("placement logic (exported from demoWalkthrough.js)", () => {
  const anchorTop = { top: 100, bottom: 150, height: 50 };
  const anchorBottom = { top: 600, bottom: 650, height: 50 };

  it("computePanelPosition returns undefined for null anchor or mobile width", () => {
    assert.equal(computePanelPosition(null, "replay", 1024, 768), undefined);
    assert.equal(computePanelPosition(anchorTop, "replay", 500, 768), undefined);
  });

  it("computePanelPosition for replay step with anchor in bottom half returns bottom position", () => {
    const pos = computePanelPosition(anchorBottom, "replay", 1024, 768);
    assert.ok(pos && pos.bottom && pos.top === "auto");
    const bottom = Number(pos.bottom.replace("px", ""));
    assert.ok(bottom > 768 - 600);
  });

  it("computePanelPosition for replay step with anchor in top half returns top position", () => {
    const pos = computePanelPosition(anchorTop, "replay", 1024, 768);
    assert.ok(pos && pos.top && !pos.bottom);
  });

  it("computePanelPosition for other steps returns clamped top position", () => {
    const pos = computePanelPosition(anchorTop, "welcome", 1024, 768);
    assert.ok(pos && pos.top);
    const top = Number(pos.top.replace("px", ""));
    assert.ok(top >= 56 && top <= 768 - 420);
  });

  it("computeArrowDirection returns undefined for null anchor or mobile width", () => {
    assert.equal(computeArrowDirection(null, "replay", 1024, 768), undefined);
    assert.equal(computeArrowDirection(anchorTop, "replay", 500, 768), undefined);
  });

  it("computeArrowDirection for replay step with anchor in bottom half returns 'down'", () => {
    assert.equal(computeArrowDirection(anchorBottom, "replay", 1024, 768), "down");
  });

  it("computeArrowDirection for replay step with anchor in top half returns 'down'", () => {
    assert.equal(computeArrowDirection(anchorTop, "replay", 1024, 768), "down");
  });

  it("getStagePadding returns 14 for trace step, 6 for others", () => {
    assert.equal(getStagePadding("trace"), 14);
    assert.equal(getStagePadding("welcome"), 6);
    assert.equal(getStagePadding("models"), 6);
    assert.equal(getStagePadding("live"), 6);
    assert.equal(getStagePadding("replay"), 6);
  });
});

describe("R44 : pulse Tracer", () => {
  const jsx = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
  it("réessaie avec un vrai compteur, l'id rAF ne sert qu'à l'annulation", () => {
    assert.match(jsx, /export const PULSE_MAX_ATTEMPTS = 30;/);
    assert.match(jsx, /\+\+attempts < PULSE_MAX_ATTEMPTS/);
    assert.doesNotMatch(jsx, /checkRaf < 30/);
  });
});

describe("R44 : défilement du panneau", () => {
  it("garde la flèche sur le conteneur externe et le défilement sur la région", () => {
    const jsx = readFileSync(new URL("./DemoWalkthrough.jsx", import.meta.url), "utf8");
    assert.match(jsx, /<div\s+data-arrow=\{arrowDir \|\| undefined\}[\s\S]*?className=\{`naviguide-demo-panel fixed/);
    assert.match(jsx, /role="region"[\s\S]*?max-h-\[45dvh\] flex-col overflow-y-auto[\s\S]*?md:max-h-\[calc\(100dvh-5rem\)\]/);
  });
});
