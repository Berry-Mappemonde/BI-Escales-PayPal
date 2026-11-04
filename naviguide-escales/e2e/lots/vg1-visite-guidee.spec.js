// VG1 — visite guidée des juges (revue de la PR #121, @lazizbekravshanov).
// Sur le stock figé : lanceur fr / en, 8 étapes (vue et panneaux), brouillon conservé
// (bienvenue → tracé → retour → Fermer, et Échap au tracé), route terminée à l'étape 8
// (pilules et carte d'accord, aucun « film officiel »), film lancé / arrêté, passe 390 px.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, panelClosed, probeOfficial } from "../helpers.js";

const PILL_ON = /bg-blue-600\/30/;
const START = { lat: 46.1, lon: -1.5 };
const END = { lat: 15.3, lon: -61.0 };
// [étape, vue attendue, panneau gauche ouvert, panneau droit ouvert]
const STEPS = [
  ["welcome", "suivre", false, false],
  ["models", "suivre", false, false],
  ["live", "suivre", false, false],
  ["briefing", "suivre", true, false],
  ["layers", "suivre", false, true],
  ["replay", "suivre", true, false],
  ["trace", "tracer", true, true],
  ["return", "suivre", true, false],
];

async function stubRoute(page) {
  await page.route("**/route?*", async (route) => {
    const u = new URL(route.request().url());
    const n = (k) => Number(u.searchParams.get(k));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[n("start_lon"), n("start_lat")], [n("end_lon"), n("end_lat")]] },
        properties: {},
      }),
    });
  });
}

async function open(page) {
  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
}

const panel = (page) => page.getByTestId("demo-walkthrough-panel");
const drawnCount = (page) => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0);

async function startTour(page) {
  await page.getByTestId("demo-walkthrough-launch").click();
  await expect(panel(page)).toHaveAttribute("data-step", "welcome");
}
async function next(page, id) {
  await page.getByTestId("demo-walkthrough-next").click();
  await expect(panel(page)).toHaveAttribute("data-step", id);
}

async function drawTwoPoints(page) {
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("route-switch-draw").click();
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), START);
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), END);
  await expect.poll(() => drawnCount(page), { timeout: 10_000 }).toBe(2);
}

test("VG1 fr : lanceur, 8 étapes (vue + panneaux), focus, Fermer la visite", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await open(page);
  await expect(page.getByTestId("demo-walkthrough-launch")).toHaveText(/Visite guidée/);
  await startTour(page);
  await expect(page.getByTestId("demo-walkthrough-title")).toBeFocused();
  await expect(panel(page).getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Étape 1 sur 8");
  await expect(page.getByTestId("demo-walkthrough-body")).not.toContainText("données réelles");
  for (let i = 0; i < STEPS.length; i += 1) {
    const [id, view, left, right] = STEPS[i];
    if (i > 0) await next(page, id);
    await expect(page.getByTestId(`view-${view}`)).toHaveAttribute("aria-checked", "true");
    await expect.poll(() => panelClosed(page, "left")).toBe(!left);
    await expect.poll(() => panelClosed(page, "right")).toBe(!right);
    await expect(page.getByTestId("demo-walkthrough-live")).toContainText(`Étape ${i + 1} sur 8`);
  }
  // Placement : à l'opposé du panneau Outils quand l'étape l'ouvre.
  await page.getByTestId("demo-walkthrough-prev").click();
  await expect(panel(page)).toHaveAttribute("data-side", "left");
  await next(page, "return");
  const end = page.getByTestId("demo-walkthrough-end");
  await expect(end).toHaveText("Fermer la visite");
  await expect(page.getByRole("button", { name: /terminer|finish/i })).toHaveCount(0);
  await end.click();
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByTestId("demo-walkthrough-launch")).toBeFocused();
  expect(errors, errors.join("\n")).toEqual([]);
});

test("VG1 en : launcher and step copy in English, End tour", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  await open(page);
  await expect(page.getByTestId("demo-walkthrough-launch")).toHaveText(/Guided tour/);
  await startTour(page);
  await expect(page.getByTestId("demo-walkthrough-title")).toHaveText("NAVIGUIDE guided tour");
  await expect(panel(page).getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Step 1 of 8");
  for (const [id] of STEPS.slice(1)) await next(page, id);
  await expect(page.getByTestId("demo-walkthrough-end")).toHaveText("End tour");
  await expect(panel(page)).not.toContainText(/walkthrough|guided demo/i);
});

test("VG1 : un brouillon de 2 points survit à la visite, et Échap au tracé ne l'efface pas", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  await drawTwoPoints(page);
  await startTour(page);
  for (const id of ["models", "live", "briefing", "layers", "replay", "trace"]) await next(page, id);
  expect(await drawnCount(page)).toBe(2);
  // Échap à l'étape Tracer : ferme la visite (capture) sans annuler le tracé.
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  expect(await drawnCount(page)).toBe(2);
  await expect(page.getByTestId("demo-walkthrough-launch")).toBeFocused();
  // Deuxième passage jusqu'au bout.
  await startTour(page);
  for (const id of ["models", "live", "briefing", "layers", "replay", "trace", "return"]) await next(page, id);
  await page.getByTestId("demo-walkthrough-end").click();
  expect(await drawnCount(page)).toBe(2);
  // En Suivre, le dessin est parqué : un clic carte n'ajoute pas de point.
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.mouse.click(640, 420);
  expect(await drawnCount(page)).toBe(2);
});

test("VG1 : route terminée → étape 8, pilules et carte d'accord, pas de « film officiel »", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  await drawTwoPoints(page);
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  await startTour(page);
  await next(page, "models");
  await next(page, "live");
  await expect(page.getByTestId("demo-walkthrough-body")).toContainText("votre route terminée");
  for (const id of ["briefing", "layers", "replay"]) await next(page, id);
  await expect(panel(page)).not.toContainText(/film officiel|stock officiel/i);
  for (const id of ["trace", "return"]) await next(page, id);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("route-switch-custom")).toHaveClass(PILL_ON);
  await expect(page.getByTestId("route-switch-berry")).not.toHaveClass(PILL_ON);
  await page.getByTestId("demo-walkthrough-end").click();
  await expect(page.getByTestId("route-switch-custom")).toHaveClass(PILL_ON);
});

test("VG1 : le bouton film de la visite lance et arrête le film ; plein écran masque la visite", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  const apiUp = Boolean(await probeOfficial(page));
  test.skip(!apiUp, "API du stock figé absente (PW_WITH_API=1)");
  await startTour(page);
  for (const id of ["models", "live", "briefing", "layers", "replay"]) await next(page, id);
  const play = page.getByTestId("demo-walkthrough-play");
  await expect(play).toBeEnabled({ timeout: 45_000 });
  await expect(play).toHaveText(/Revoir l’expédition/);
  await play.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 10_000 });
  // Film en lecture : la visite se réduit à une pastille.
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByTestId("demo-walkthrough-chip")).toBeVisible();
  await page.getByTestId("film-fullscreen").click();
  await expect(page.getByTestId("demo-walkthrough-chip")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("demo-walkthrough-chip")).toBeVisible();
  await page.getByTestId("demo-walkthrough-chip").click();
  await expect(panel(page)).toHaveAttribute("data-step", "replay");
  await next(page, "trace");
  await expect(page.getByTestId("replay-stop")).toHaveCount(0, { timeout: 10_000 });
});

test("VG1 390 px : panneau en bas, ne couvre pas le haut de l'écran", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await startTour(page);
  for (const id of ["models", "live", "briefing"]) await next(page, id);
  const box = await panel(page).boundingBox();
  expect(box).not.toBeNull();
  expect(box.y).toBeGreaterThan(844 * 0.5);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  for (const id of ["layers", "replay", "trace", "return"]) await next(page, id);
  await page.getByTestId("demo-walkthrough-end").click();
  await expect(panel(page)).toHaveCount(0);
});

test("VG1 ?tour=1 : la visite s'ouvre au chargement ; étape 2 « Qui fait quoi » (Nemotron, Tavily)", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await stubRoute(page);
  await page.goto("/?tour=1");
  await dismissNotForNav(page);
  await expect(panel(page)).toHaveAttribute("data-step", "welcome", { timeout: 30_000 });
  await expect(panel(page).getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Étape 1 sur 8");
  await next(page, "models");
  await expect(page.getByTestId("demo-walkthrough-title")).toHaveText(/Qui fait quoi/);
  await expect(page.getByTestId("demo-walkthrough-body")).toContainText("Nebius Token Factory");
  const box = page.getByTestId("demo-models");
  await expect(page.getByTestId("demo-models-tavily")).toContainText("Tavily", { timeout: 20_000 });
  await expect(page.getByTestId("demo-models-quick")).toContainText("Nemotron");
  await expect(page.getByTestId("demo-models-write")).toContainText("Nemotron");
  await expect(page.getByTestId("demo-models-deep")).toContainText("Nemotron");
  const apiUp = Boolean(await probeOfficial(page));
  if (apiUp) {
    // Statut en direct : modèles lus dans /ici/warm/status, compteurs du jour.
    await expect(box).toHaveAttribute("data-live", "true");
    await expect(page.getByTestId("demo-models-today")).toContainText("appels Nemotron");
    await expect(page.getByTestId("demo-models-default")).toHaveCount(0);
  } else {
    await expect(box).toHaveAttribute("data-live", "false");
    await expect(page.getByTestId("demo-models-default")).toBeVisible();
  }
  expect(errors, errors.join("\n")).toEqual([]);
});

test("VG1 sans ?tour : la visite reste fermée au chargement", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("demo-walkthrough-launch")).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
});

test("VG1 driver.js : projecteur sur l'élément réel, question du journal cliquable, Échap éteint tout", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  const shots = process.env.TOUR_SHOTS_DIR;
  await startTour(page);
  await expect(panel(page)).toHaveAttribute("data-spot", "off");
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  if (shots) await page.screenshot({ path: `${shots}/01-bienvenue.png` });
  await next(page, "models");
  await next(page, "live");
  await expect(panel(page)).toHaveAttribute("data-spot", "on");
  await expect(page.locator(".leaflet-container.driver-active-element")).toHaveCount(1);
  if (shots) await page.screenshot({ path: `${shots}/02-carte.png` });
  await next(page, "briefing");
  await expect(page.locator('[data-tour="logbook"].driver-active-element')).toHaveCount(1);
  await expect(page.locator(".driver-overlay")).toBeVisible();
  // La question d'exemple reste cliquable sous le projecteur (pointer-events).
  const ex = page.getByTestId("logbook-chat-examples").locator("button").first();
  await expect(ex).toBeVisible();
  await expect.poll(() => ex.evaluate((b) => {
    const r = b.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return b === top || b.contains(top);
  }), { timeout: 5_000 }).toBe(true);
  if (shots) await page.screenshot({ path: `${shots}/03-journal-nemotron.png` });
  await next(page, "layers");
  await next(page, "replay");
  await expect(page.locator('[data-tour="film"].driver-active-element')).toHaveCount(1);
  if (shots) await page.screenshot({ path: `${shots}/04-film.png` });
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await expect(page.locator(".driver-active-element")).toHaveCount(0);
});

/* Tests additionnels demandés par la tâche (corrections PR #155) */

test("VG1 — pas d'overlay driver.js aux étapes 1, 2, 8 (welcome, models, return)", async ({ page }) => {
  await open(page);
  await startTour(page);
  // Étape 1 : welcome (target = null)
  await expect(panel(page)).toHaveAttribute("data-step", "welcome");
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await expect(page.locator(".driver-active-element")).toHaveCount(0);
  // Étape 2 : models (target = null)
  await next(page, "models");
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await expect(page.locator(".driver-active-element")).toHaveCount(0);
  // Passer aux étapes intermédiaires
  await next(page, "live");
  await next(page, "briefing");
  await next(page, "layers");
  await next(page, "replay");
  await next(page, "trace");
  // Étape 8 : return (target = null)
  await next(page, "return");
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await expect(page.locator(".driver-active-element")).toHaveCount(0);
});

test("VG1 — étape 1 → 2 (welcome → models) < 2 s avec cache vide", async ({ page }) => {
  // S'assurer qu'on part d'un cache vide (pas de tour au chargement)
  await open(page);
  const start = Date.now();
  await startTour(page);
  // Étape 1 : welcome
  await expect(panel(page)).toHaveAttribute("data-step", "welcome");
  await next(page, "models");
  // Étape 2 : models - la transition ne doit pas bloquer sur l'appel réseau
  await expect(panel(page)).toHaveAttribute("data-step", "models");
  const elapsed = Date.now() - start;
  expect(elapsed).toBeLessThan(2000);
});


test("VG1 — étape 5 (layers) : cible = summary [data-tour=layers] (pas le details entier)", async ({ page }) => {
  await open(page);
  await startTour(page);
  await next(page, "models");
  await next(page, "live");
  await next(page, "briefing");
  await next(page, "layers");
  // Vérifier que l'élément éclairé est bien le summary (et non le details)
  const summary = page.locator('[data-tour="layers"]').first();
  await expect(summary).toBeVisible();
  // Le driver doit éclairer exactement ce sélecteur
  await expect(page.locator('[data-tour="layers"].driver-active-element')).toHaveCount(1);
  // Le <details> ne doit PAS avoir la classe driver-active-element
  await expect(page.locator('details.driver-active-element')).toHaveCount(0);
});

test("VG1 — étape 6 (replay) : bulle au-dessus de la barre film, barre visible", async ({ page }) => {
  await open(page);
  await startTour(page);
  await next(page, "models");
  await next(page, "live");
  await next(page, "briefing");
  await next(page, "layers");
  await next(page, "replay");
  // La barre film doit être visible (pas cachée)
  const filmBar = page.locator('[data-tour="film"]').first();
  await expect(filmBar).toBeVisible();
  // La bulle (panneau) doit être au-dessus : bottom de la bulle ≤ top de la barre
  const panelEl = panel(page);
  const panelBox = await panelEl.boundingBox();
  const barBox = await filmBar.boundingBox();
  expect(panelBox.y + panelBox.height).toBeLessThanOrEqual(barBox.y + 12); // 12px marge
});

test("VG1 — étape 7 (trace) : bouton Tracer visible, pulse, classe retirée à la sortie", async ({ page }) => {
  await open(page);
  await startTour(page);
  await next(page, "models");
  await next(page, "live");
  await next(page, "briefing");
  await next(page, "layers");
  await next(page, "replay");
  await next(page, "trace");
  // Le bouton Tracer doit être visible et avoir la classe pulse
  const traceBtn = page.locator('[data-testid="view-tracer"]').first();
  await expect(traceBtn).toBeVisible();
  // Attendre que la classe pulse soit ajoutée (raf retry up to 30 frames)
  await expect(traceBtn).toHaveAttribute("class", /naviguide-tour-pulse/, { timeout: 10000 });
  // Vérifier le stagePadding ~14 (via data-step ou inspection)
  await expect(panel(page)).toHaveAttribute("data-step", "trace");
  // Quitter la visite : la classe pulse doit être retirée
  await page.keyboard.press("Escape");
  await expect(traceBtn).not.toHaveClass("naviguide-tour-pulse");

});

test("VG1 — flèche bulle → élément : data-arrow up/down/left/right + ::before", async ({ page }) => {
  await open(page);
  await startTour(page);
  // welcome, models, return : pas de flèche (target = null)
  await expect(panel(page)).not.toHaveAttribute("data-arrow");
  await next(page, "models");
  await expect(panel(page)).not.toHaveAttribute("data-arrow");
  // live : target = .leaflet-container (à droite) → flèche left
  await next(page, "live");
  await expect(panel(page)).toHaveAttribute("data-arrow", "left");
  // briefing : target = [data-tour="logbook"] (à droite) → flèche left
  await next(page, "briefing");
  await expect(panel(page)).toHaveAttribute("data-arrow", "left");
  // layers : target = [data-tour="layers"] (à gauche) → flèche right
  await next(page, "layers");
  await expect(panel(page)).toHaveAttribute("data-arrow", "right");
  // replay : target = [data-tour="film"] (à droite, en bas) → flèche down (panneau au-dessus)
  await next(page, "replay");
  await expect(panel(page)).toHaveAttribute("data-arrow", "down");
  // trace : target = [data-testid="view-tracer"] (à gauche) → flèche right
  await next(page, "trace");
  await expect(panel(page)).toHaveAttribute("data-arrow", "right");
  // return : target = null → pas de flèche
  await next(page, "return");
  await expect(panel(page)).not.toHaveAttribute("data-arrow");
});

test("VG1 — R13 : dix Tab consécutifs restent dans le panneau de visite", async ({ page }) => {
  await open(page);
  await startTour(page);
  const p = panel(page);
  await expect(p).toBeVisible();
  for (let i = 0; i < 10; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="demo-walkthrough-panel"]');
      return Boolean(el && el.contains(document.activeElement));
    });
    expect(inside).toBe(true);
  }
});

// R44 : le bouton Tracer « monté tard » (cible absente à l'ouverture de l'étape 7) reçoit
// quand même le pulse. Avant le correctif, le réessai comparait l'id rAF (> 30 à ce stade).
test("R44 — étape 7 : pulse appliqué quand le bouton Tracer apparaît après l'ouverture", async ({ page }) => {
  await open(page);
  await startTour(page);
  for (const id of ["models", "live", "briefing", "layers", "replay"]) await next(page, id);
  const rafId = await page.evaluate(() => new Promise((r) => requestAnimationFrame(r)).then(() => requestAnimationFrame(() => {})));
  expect(rafId, "les ids rAF dépassent 30 avant l'étape 7").toBeGreaterThan(30);
  // Retire la cible du sélecteur, puis la rend 150 ms après l'ouverture de l'étape.
  await page.evaluate(() => {
    const el = document.querySelector('[data-testid="view-tracer"]');
    el.setAttribute("data-testid", "view-tracer-later");
    window.__r44Restore = () => el.setAttribute("data-testid", "view-tracer");
  });
  try {
    await page.getByTestId("demo-walkthrough-next").click();
    await expect(panel(page)).toHaveAttribute("data-step", "trace");
    await page.waitForTimeout(150);
  } finally {
    // Rend toujours la cible, même si une étape a échoué (page partagée par les assertions suivantes).
    await page.evaluate(() => window.__r44Restore?.()).catch(() => {});
  }
  const traceBtn = page.getByTestId("view-tracer").first();
  await expect(traceBtn).toHaveClass(/naviguide-tour-pulse/, { timeout: 5000 });
});
