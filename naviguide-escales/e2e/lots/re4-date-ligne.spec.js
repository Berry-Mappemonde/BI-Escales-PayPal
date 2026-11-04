// Changer la date de la barre (Suivre) recalcule la ligne d'état
// (année, jour de voyage) ; remettre le défaut restaure la ligne LIVE ;
// le départ de Tracer (aujourd'hui, plus de champ — DM7) ne bouge pas.
// Sans API : champ date et ligne d'état (horloge locale) tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent — jamais le champ, ni le décalage d'année,
// ni l'absence du champ Date de départ en Tracer.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re4");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

function dateInput(page, testId) {
  return page.getByTestId(testId).locator("input").first();
}

async function probeOfficial(request) {
  const official = await request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  if (!official || !official.ok()) return null;
  const ct = official.headers()["content-type"] || "";
  if (!ct.includes("json")) return null;
  const body = await official.json().catch(() => null);
  return body && typeof body === "object" ? body : null;
}

test("Date de la barre pilote la ligne d'état, Simulation inchangée", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions LIVE serveur sautées",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  await expect(page.getByTestId("replay-departure")).toBeVisible({ timeout: 15_000 });
  const replayDate = dateInput(page, "replay-departure-field");
  await expect(replayDate).toHaveValue("15/05/2026");

  const clock = page.getByTestId("clock-line");
  await expect(clock).toBeVisible({ timeout: 15_000 });
  // La ligne démarre sur le gabarit « 0 nm · j0 · 15 mai 2026 » puis passe à l'horloge officielle (jour de mer
  // réel, minute UTC qui avance, milles qui tickent) : on attend cette bascule quand l'API est là, et le retour
  // au défaut se compare sur le jour de mer, l'année et LIVE — pas sur le texte entier (tranche 5/6, 29 sept.).
  if (apiUp) await expect(clock).not.toHaveText(/\bj0\b/, { timeout: 20_000 }).catch(() => {});
  const clockKey = (s) => `${(s.match(/\bj\d+\b|\bd\d+\b/) || [""])[0]} ${(s.match(/\b\d{4}\b/) || [""])[0]} ${/\bLIVE\b/.test(s) ? "LIVE" : ""}`.trim();
  const lineBefore = (await clock.innerText()).trim();
  expect(lineBefore, "ligne d'état initiale").toMatch(/j\d+|d\d+/);
  if (/\d{4}/.test(lineBefore)) {
    expect(lineBefore).toMatch(/2026/);
  }

  await replayDate.fill("15/05/2025");
  await expect(replayDate).toHaveValue("15/05/2025");

  await expect.poll(async () => (await clock.innerText()).trim(), { timeout: 8_000 })
    .toMatch(/2025/);
  const line2025 = (await clock.innerText()).trim();
  expect(line2025, "année 2025 après changement de date").toMatch(/2025/);
  expect(line2025, "jour de voyage toujours dérivé").toMatch(/j\d+|d\d+/);
  expect(line2025, "la ligne a changé, pas seulement le champ").not.toBe(lineBefore);
  if (apiUp && /LIVE/.test(lineBefore)) {
    expect(line2025, "LIVE reste sur la ligne décalée").toMatch(/LIVE/);
  }
  await shot(page, "01-ligne-2025");

  await replayDate.fill("15/05/2026");
  await expect(replayDate).toHaveValue("15/05/2026");
  await expect.poll(async () => clockKey((await clock.innerText()).trim()), { timeout: 8_000 })
    .toBe(clockKey(lineBefore));
  const lineRestored = (await clock.innerText()).trim();
  expect(clockKey(lineRestored), `retour au défaut = ligne d'origine (${lineBefore} → ${lineRestored})`).toBe(clockKey(lineBefore));
  if (/\d{4}/.test(lineRestored)) {
    expect(lineRestored).toMatch(/2026/);
  }
  await shot(page, "02-retour");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showToolsPanel(page);
  await expect(page.getByTestId("departure-field")).toHaveCount(0);
  if (await clock.isVisible().catch(() => false)) {
    const tracerLine = (await clock.innerText()).trim();
    expect(tracerLine, "horloge Tracer distincte du replay 2025").not.toMatch(/2025/);
  }
});
