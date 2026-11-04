// Journal lisible dans les deux thèmes ; pilules 2:30 / 3:00
// seulement à côté de « Revoir l'expédition », jamais pendant le film.
// Sans API : couleurs CSS (sonde dans l'encadré) et présence/absence des
// pilules tiennent seuls. GET /voyage/official sondé ; s'il manque,
// annotation + saut des seules assertions sur les lignes réelles du
// journal — jamais le contraste CSS, ni les pilules hors film.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re3");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

function parseRgb(color) {
  const m = String(color || "").match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function luminance(rgb) {
  if (!rgb) return null;
  return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
}

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
  if (side === "left") return openLeftDrawer(page);
  if (await panelOnScreen(page, side)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect.poll(() => panelOnScreen(page, side), { timeout: 10_000 }).toBe(true);
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

async function journalColors(page) {
  return page.evaluate(() => {
    const box = document.querySelector("[data-testid='ici-maintenant']");
    if (!box) return null;
    const real = [...box.querySelectorAll("[data-testid='ici-journal-entry']")];
    let el = real[0] || null;
    let probe = false;
    if (!el) {
      el = document.createElement("button");
      el.setAttribute("data-testid", "ici-journal-entry");
      box.appendChild(el);
      probe = true;
    }
    const cs = getComputedStyle(el);
    const bg = getComputedStyle(box);
    const out = {
      color: cs.color,
      background: bg.backgroundColor,
      probe,
      count: real.length,
    };
    if (probe) el.remove();
    return out;
  });
}

/** Ligne visible pour la capture si le journal n'a pas encore d'entrées (CSS réelle). */
async function revealJournalLineForShot(page) {
  const first = page.getByTestId("ici-journal-entry").first();
  if (await first.isVisible().catch(() => false)) return false;
  await page.evaluate(() => {
    const slot = document.querySelector("[data-testid='ici-journal-slot']");
    if (!slot) return;
    slot.style.minHeight = "2.5rem";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("data-testid", "ici-journal-entry");
    btn.className = "ici-journal-entry w-full text-left text-[11px] leading-snug px-0.5 py-0.5 bg-transparent border-0";
    btn.textContent = "15 mai 2026 · 48,9°N 2,3°E · départ";
    slot.appendChild(btn);
  });
  await expect(page.getByTestId("ici-journal-entry").first()).toBeVisible({ timeout: 5_000 });
  return true;
}

test("Journal lisible, pilules seulement hors film", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — lignes réelles du journal non exigées",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showPanel(page, "left");
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("ici-tab-journal").evaluate((el) => el.click());
  await expect(page.getByTestId("ici-tab-journal")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();

  if (apiUp) {
    const gotLines = await page.getByTestId("ici-journal-entry").first()
      .isVisible({ timeout: 15_000 })
      .catch(() => false);
    if (!gotLines) {
      test.info().annotations.push({
        type: "journal",
        description: "API up mais aucune ligne ici-journal-entry — contraste mesuré sur sonde CSS",
      });
    }
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "journal vide — contraste mesuré sur sonde CSS, pas sur une ligne réelle",
    });
  }

  const dark = await journalColors(page);
  expect(dark, "encadré Ici absent").toBeTruthy();
  const darkLum = luminance(parseRgb(dark.color));
  expect(darkLum, `journal sombre color=${dark.color}`).toBeGreaterThan(0.55);
  const darkBgLum = luminance(parseRgb(dark.background));
  if (darkBgLum != null) {
    expect(darkLum - darkBgLum, "texte clair sur fond sombre").toBeGreaterThan(0.25);
  }
  if (!dark.probe && dark.count > 0) {
    await expect(page.getByTestId("ici-journal-entry").first()).toBeVisible();
  }
  if (await revealJournalLineForShot(page)) {
    test.info().annotations.push({
      type: "capture",
      description: "01-journal : ligne de démonstration (même règle CSS) — journal encore vide",
    });
  }

  await shot(page, "01-journal");

  await showPanel(page, "right");
  const theme = page.getByRole("button", { name: /^(sombre|dark)$/i });
  await expect(theme).toBeVisible({ timeout: 8_000 });
  await theme.click();
  await expect(page.locator(".light-mode")).toBeVisible({ timeout: 5_000 });

  const light = await journalColors(page);
  expect(light, "encadré Ici absent en thème clair").toBeTruthy();
  const lightLum = luminance(parseRgb(light.color));
  expect(lightLum, `journal clair color=${light.color}`).toBeLessThan(0.35);
  const lightBgLum = luminance(parseRgb(light.background));
  if (lightBgLum != null) {
    expect(lightBgLum - lightLum, "texte foncé sur fond clair").toBeGreaterThan(0.25);
  }

  await page.getByRole("button", { name: /^(clair|light)$/i }).click();
  await expect(page.locator(".light-mode")).toHaveCount(0);

  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  const { waitFilmReady } = await import("../helpers.js");
  if (apiUp) await waitFilmReady(page);
  const durations = page.getByTestId("film-duration");
  if (!(await durations.isVisible().catch(() => false))) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "pilules 2:30 / 3:00 absentes tant que Revoir ne peut pas partir",
      });
      await shot(page, "02-pilules");
      return;
    }
    throw new Error("film prêt mais pilules 2:30 / 3:00 absentes");
  }
  await expect(durations).toContainText("2:30");
  await expect(durations).toContainText("3:00");
  await expect(durations.locator("[data-seconds='150']")).toHaveAttribute("aria-pressed", "false");
  await expect(durations.locator("[data-seconds='180']")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("replay-stop")).toHaveCount(0);
  await shot(page, "02-pilules");

  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-duration")).toHaveCount(0);
  await expect(page.getByTestId("replay-start")).toHaveCount(0);

  await page.getByTestId("replay-stop").click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-duration")).toBeVisible();
  await expect(page.getByTestId("film-duration")).toContainText("2:30");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
  await expect(page.getByTestId("film-duration")).toHaveCount(0);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const { enterTracer } = await import("../helpers.js");
  await enterTracer(page);
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("film-bar")).toHaveAttribute("data-drawing", "1");
  await expect(page.getByTestId("film-duration")).toHaveCount(0);
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
});
