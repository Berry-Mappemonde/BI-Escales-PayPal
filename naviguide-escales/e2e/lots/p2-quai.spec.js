// Vitesse réelle, zéro à quai.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-p2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function knotsIn(text) {
  const m = String(text || "").match(/(\d+[.,]\d+)\s*kt/);
  return m ? Number(m[1].replace(",", ".")) : null;
}

async function seekFilm(page, ratio) {
  const bar = page.locator("[data-testid='film-bar'] .relative.w-full.h-2").first();
  await expect(bar).toBeVisible({ timeout: 15_000 });
  const box = await bar.boundingBox();
  if (!box) throw new Error("barre film introuvable");
  await bar.click({ position: { x: Math.max(4, box.width * ratio), y: box.height / 2 } });
}

async function enterSimulation(page) {
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("button", { name: /prochaine escale/i })).toBeVisible({ timeout: 15_000 });
  // L’effet de prime Simulation fait un seek(0) une fois : on attend qu’il soit passé
  // avant de viser une escale (sinon le seek(0) écrase le clic).
  await page.waitForTimeout(800);
}

test("À quai 0 kn ; en mer la vitesse varie", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const clock = page.getByTestId("clock-line");
  await expect(clock).toBeVisible({ timeout: 15_000 });
  // CI sans API : l’horloge live n’est pas forcément à quai. On pose le
  // playhead sur Ajaccio (3 j de hold) après le seek(0) de prime Simulation.
  await enterSimulation(page);
  const next = page.getByTestId("next-stop");
  await expect(next).toBeVisible({ timeout: 15_000 });
  for (let i = 0; i < 12; i += 1) {
    const txt = await clock.innerText();
    if (/à quai|in port/i.test(txt)) break;
    await next.click();
    await page.waitForTimeout(400);
  }
  await expect(clock).toContainText(/à quai|in port/i, { timeout: 15_000 });
  await expect(clock).not.toContainText(/\d+[.,]\d+\s*kt/);
  await shot(page, "01-quai");
  const seen = new Set();
  for (const ratio of [0.22, 0.38, 0.55, 0.72]) {
    await seekFilm(page, ratio);
    await page.waitForTimeout(600);
    const kn = knotsIn(await clock.innerText());
    if (kn != null) seen.add(kn);
  }
  await shot(page, "02-mer");
  // La variation de la vitesse vient du vent (GRIB / climatologie servis par
  // l'API). En CI il n'y a pas d'API : on vérifie alors seulement qu'une
  // vitesse est affichée en mer, et on note que la variation n'a pas pu être
  // contrôlée (un spec de lot tient sans API).
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({ type: "sans API", description: `vitesses relevées : ${[...seen].join(", ") || "aucune"} — variation non contrôlable sans API` });
    expect(seen.size, "au moins une vitesse affichée en mer").toBeGreaterThanOrEqual(1);
    return;
  }
  expect(seen.size, `vitesses relevées : ${[...seen].join(", ") || "aucune"}`).toBeGreaterThanOrEqual(2);
});
