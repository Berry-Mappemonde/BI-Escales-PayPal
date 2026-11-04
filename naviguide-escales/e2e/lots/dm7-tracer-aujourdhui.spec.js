// Tracer simule depuis aujourd'hui (revue du 14 oct., C4 / C5) :
// Play part toujours du jour de connexion, 08:00 UTC ; « repartir au début »
// y revient ; Date de départ masquée en Tracer (reste en Suivre) ; encadré et
// fiche d'escale suivent le bateau DU TRACÉ (Saint-Maur → La Rochelle), jamais
// la position officielle (Papeete).
// Sans API : horloge locale, champ masqué, Play / prev, Suivre → date.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions vitrine Berry (Saint-Maur / étape) — jamais l'horloge du jour,
// ni l'absence du champ, ni l'absence de Papeete, ni le retour Suivre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm7");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const PILL_ON = /bg-blue-600\/30/;
const MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function todayCivilFr() {
  const d = new Date();
  return `${d.getUTCDate()} ${MONTHS_FR[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

test("Tracer : horloge aujourd'hui, pas de date, pas de Papeete", async ({ page }) => {
  test.setTimeout(120_000);
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — vitrine Berry (Saint-Maur / étape) sautée ; horloge du jour, champ masqué, Play / prev et Suivre conservés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  const berryPill = page.getByTestId("route-switch-berry");
  await expect(berryPill).toBeVisible({ timeout: 10_000 });
  if (!PILL_ON.test((await berryPill.getAttribute("class")) || "")) {
    await berryPill.click();
  }
  await expect.poll(async () => (await berryPill.getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);

  const today = todayCivilFr();
  const clock = page.getByTestId("clock-line");
  await expect(clock).toBeVisible({ timeout: 15_000 });
  await expect(clock).toContainText(today, { timeout: 15_000 });
  await expect(clock).toContainText(/08:00 UTC/);

  await showRightPanel(page);
  await expect(page.getByTestId("departure-field")).toHaveCount(0);

  await showLeftPanel(page);
  const sheet = page.getByTestId("escale-sheet");
  const popup = page.getByTestId("escale-popup");
  if (await sheet.isVisible().catch(() => false)) {
    await expect(sheet).not.toContainText(/Papeete/i);
  }
  if (await popup.isVisible().catch(() => false)) {
    await expect(popup).not.toContainText(/Papeete/i);
  }
  await expect(page.getByTestId("escale-sheet").filter({ hasText: /Papeete/i })).toHaveCount(0);

  if (apiUp) {
    await expect(page.getByText(/Saint-Maur/i).first()).toBeVisible({ timeout: 20_000 });
    const leg = page.getByTestId("ici-section-leg");
    await expect(leg).toBeVisible({ timeout: 10_000 });
    await expect(leg).toContainText(/Saint-Maur/i);
    await expect(leg).toContainText(/La Rochelle/i);
    await expect(leg).not.toContainText(/Papeete/i);
  }

  await shot(page, "01-tracer-aujourdhui");

  const play = page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/);
  await expect(play).toBeVisible();
  const before = (await clock.innerText()).trim();
  await play.click();
  await expect.poll(async () => (await clock.innerText()).trim(), { timeout: 12_000 })
    .not.toBe(before);
  const pause = page.getByTestId("film-bar").getByTitle(/^(Pause)$/);
  if (await pause.isVisible().catch(() => false)) await pause.click();

  const prev = page.getByTestId("prev-stop");
  for (let i = 0; i < 8; i += 1) {
    if (await prev.isDisabled().catch(() => true)) break;
    await prev.click();
  }
  await expect(clock).toContainText(today, { timeout: 10_000 });
  await expect(clock).toContainText(/08:00 UTC/);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-departure")).toBeVisible({ timeout: 15_000 });
});
