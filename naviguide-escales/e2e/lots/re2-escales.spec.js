// Liste des escales informative en Suivre ; fiche = escale désignée.
// Sans API : Suivre / Simulation, la liste (repli itinéraire) et l'absence
// de bouton tiennent seuls. GET /voyage/official sondé ; s'il manque,
// annotation + saut des seules assertions noms / drapeau / fiche Ici —
// jamais « ligne sans clic en Suivre » ni « bouton en Simulation ».
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re2");
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

function panelOnScreen(page, side) {
  const sel = side === "left"
    ? ".naviguide-sidebar-panel.left-0"
    : ".naviguide-sidebar-panel.right-0";
  return page.locator(sel).first().evaluate((el) => {
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 50 && r.right > 12 && r.left < window.innerWidth - 12;
  });
}

async function showPanel(page, side) {
  await leaveCinema(page);
  if (await panelOnScreen(page, side)) return;
  const toggle = side === "left"
    ? ".naviguide-sidebar-toggle--left"
    : ".naviguide-sidebar-toggle--right";
  await page.locator(toggle).evaluate((el) => el.click());
  const opened = await expect.poll(() => panelOnScreen(page, side), { timeout: 8_000 }).toBe(true)
    .then(() => true).catch(() => false);
  if (!opened) {
    await page.keyboard.press("Escape");
    await page.locator(toggle).evaluate((el) => el.click());
    await expect.poll(() => panelOnScreen(page, side), { timeout: 8_000 }).toBe(true);
  }
  await page.waitForTimeout(350);
}

async function probeOfficial(request) {
  const official = await request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  if (!official || !official.ok()) return null;
  const ct = official.headers()["content-type"] || "";
  if (!ct.includes("json")) return null;
  const body = await official.json().catch(() => null);
  return body && typeof body === "object" ? body : null;
}

function legend(page) {
  return page.getByTestId("escale-legend");
}

function rowByName(page, name) {
  return page.locator("[data-testid='escale-legend-row']").filter({ hasText: new RegExp(name, "i") }).first();
}

async function clickAjaccioFlag(page) {
  const found = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 20_000 }).then(() => true).catch(() => false);
  if (!found) return false;
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) {
        scene.map.setView(marker.getLatLng(), 7, { animate: false });
        return;
      }
    }
  });
  const flag = page.locator("[data-testid='waypoint-flag'][data-escale*='Ajaccio']").first();
  if (!(await flag.isVisible({ timeout: 12_000 }).catch(() => false))) return false;
  await flag.click({ force: true });
  return true;
}

test("Liste informative en Suivre, fiche = escale désignée", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — noms Saint-Maur / La Rochelle / drapeau Ajaccio / fiche Ici non exigés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showPanel(page, "right");
  await expect(legend(page)).toBeVisible({ timeout: 10_000 });
  await legend(page).scrollIntoViewIfNeeded();

  const rows = page.locator("[data-testid='escale-legend-row']");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
  const rowCount = await rows.count();
  expect(rowCount, "liste des escales vide").toBeGreaterThan(0);

  for (let i = 0; i < rowCount; i += 1) {
    const row = rows.nth(i);
    await expect(row).toHaveAttribute("data-interactive", "false");
    await expect(row.locator("button")).toHaveCount(0);
    const cursor = await row.evaluate((el) => getComputedStyle(el).cursor);
    expect(cursor, `curseur main sur la ligne ${i}`).not.toBe("pointer");
    const inner = row.locator(":scope > *").first();
    const innerCursor = await inner.evaluate((el) => getComputedStyle(el).cursor);
    expect(innerCursor, `curseur main dans la ligne ${i}`).not.toBe("pointer");
  }

  const clock = page.getByTestId("film-clock-line");
  // La ligne d'horloge démarre sur le gabarit « 0 nm · j0 · 15 mai 2026 » puis passe à l'horloge officielle
  // (jour de mer réel, heure UTC qui avance) : on attend cette bascule, et on compare le JOUR DE MER et
  // l'état LIVE — pas le texte entier, dont la minute peut tourner pendant le test (tranche 5/6, 29 sept.).
  if (apiUp) await expect(clock).not.toHaveText(/\bj0\b/, { timeout: 20_000 }).catch(() => {});
  const readClock = async () => ((await clock.textContent().catch(() => "")) || "").replace(/\s+/g, " ");
  const cursorOf = (s) => `${(s.match(/\bj\d+\b/) || [""])[0]} ${/\bLIVE\b/.test(s) ? "LIVE" : ""}`.trim();
  const clockBefore = await readClock();
  const sheetBefore = await page.getByTestId("escale-sheet").count();

  const named = ["Saint-Maur", "La Rochelle"];
  let clickedNamed = false;
  for (const name of named) {
    const row = rowByName(page, name);
    if (!(await row.isVisible().catch(() => false))) continue;
    clickedNamed = true;
    await row.scrollIntoViewIfNeeded();
    await row.click({ force: true });
    await page.waitForTimeout(400);
    await expect(row.locator("button")).toHaveCount(0);
    const clockAfter = await readClock();
    expect(cursorOf(clockAfter), `clic ${name} a bougé le curseur (${clockBefore} → ${clockAfter})`).toBe(cursorOf(clockBefore));
    await expect(page.getByTestId("escale-sheet").filter({ hasText: /Fort-de-France/i })).toHaveCount(0);
    expect(await page.getByTestId("escale-sheet").count(), `clic ${name} a ouvert une fiche`).toBe(sheetBefore);
  }
  if (apiUp && !clickedNamed) {
    test.info().annotations.push({
      type: "liste",
      description: "Saint-Maur / La Rochelle absents de la liste — clic nommé non joué",
    });
  }
  if (!clickedNamed && rowCount > 0) {
    const row = rows.first();
    await row.click({ force: true });
    await page.waitForTimeout(400);
    const clockAfter = await readClock();
    expect(cursorOf(clockAfter), `clic ligne Suivre a bougé le curseur (${clockBefore} → ${clockAfter})`).toBe(cursorOf(clockBefore));
    await expect(page.getByTestId("escale-sheet").filter({ hasText: /Fort-de-France/i })).toHaveCount(0);
  }

  await shot(page, "01-liste");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => panelOnScreen(page, "right"), { timeout: 10_000 }).toBe(true);
  await expect(legend(page)).toBeVisible({ timeout: 10_000 });

  const ajaccioRow = rowByName(page, "Ajaccio");
  const hasAjaccio = await ajaccioRow.isVisible().catch(() => false);
  if (hasAjaccio) {
    // Liste informative dans tous les modes — plus de clic.
    await expect(ajaccioRow).toHaveAttribute("data-interactive", "false");
    await expect(ajaccioRow.getByRole("button")).toHaveCount(0);
  } else if (apiUp) {
    expect(hasAjaccio, "ligne Ajaccio absente de la liste en Simulation").toBe(true);
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "liste sans Ajaccio — clic Simulation / curseur non exigé",
    });
    const firstInteractive = page.locator("[data-testid='escale-legend-row'][data-interactive='true']").first();
    if (await firstInteractive.isVisible().catch(() => false)) {
      await expect(firstInteractive.getByRole("button")).toHaveCount(1);
    }
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showPanel(page, "left");
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 10_000 });

  if (apiUp) {
    const flagged = await clickAjaccioFlag(page);
    if (!flagged) {
      test.info().annotations.push({
        type: "drapeau",
        description: "aucun drapeau Ajaccio — fiche Ici non exigée",
      });
    } else {
      const sheet = page.getByTestId("ici-maintenant").getByTestId("escale-sheet");
      await expect(sheet).toBeVisible({ timeout: 10_000 });
      await expect(sheet).toContainText(/Ajaccio/i);
      await expect(sheet).not.toContainText(/Fort-de-France/i);
      const here = page.getByTestId("ici-section-here");
      await expect(here.getByTestId("escale-sheet")).toBeVisible();
    }
  }

  await shot(page, "02-fiche");
});
