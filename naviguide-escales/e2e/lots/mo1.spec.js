// MO1 — sous 600 px le panneau gauche est un tiroir et la barre du film
// tient sur deux lignes. Le bureau (600 px et plus) ne change pas.
// Sans API : la mise en page se vérifie seule. Le poids de l'horloge
// (NAV-M-05) ne s'affirme que si GET /voyage/official répond.
import { devices, expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-mo1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, name),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function officialUp(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  return Boolean(res && res.ok());
}

function boxesOverlap(a, b) {
  if (!a || !b) return false;
  const x = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const y = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return x > 1 && y > 1;
}

async function commandBands(page) {
  return page.evaluate(() => {
    const bar = document.querySelector("[data-testid='film-bar']");
    const root = document.querySelector("[data-testid='film-commands']");
    if (!bar || !root) return { rows: 0, overflow: true, labels: [] };
    const nodes = [
      ...root.querySelectorAll("button, input"),
      document.querySelector("[data-testid='hide-film-bar']"),
    ].filter(Boolean);
    const visible = nodes.filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 1 && r.height > 1 && getComputedStyle(el).visibility !== "hidden";
    });
    const centers = visible
      .map((el) => {
        const r = el.getBoundingClientRect();
        return Math.round(r.top + r.height / 2);
      })
      .sort((a, b) => a - b);
    const bands = [];
    for (const center of centers) {
      if (!bands.length || center - bands[bands.length - 1] > 18) bands.push(center);
    }
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const overflow = visible.some((el) => {
      const r = el.getBoundingClientRect();
      return r.left < -1 || r.right > vw + 1 || r.top < -1 || r.bottom > vh + 1;
    });
    const barBox = bar.getBoundingClientRect();
    return {
      rows: bands.length,
      overflow,
      labels: visible.map((el) => (el.innerText || el.getAttribute("aria-label") || el.getAttribute("data-testid") || "").replace(/\s+/g, " ").trim()).filter(Boolean),
      bar: { x: barBox.x, y: barBox.y, w: barBox.width, h: barBox.height },
      vw,
      vh,
    };
  });
}

function panelLocator(page, side) {
  return page.locator(side === "left"
    ? ".naviguide-sidebar-drawer"
    : ".naviguide-sidebar-panel.right-0").first();
}

async function panelOpen(page, side) {
  const cls = await panelLocator(page, side).getAttribute("class");
  if (!cls) return false;
  return side === "left"
    ? !cls.includes("-translate-x-full")
    : !cls.includes("translate-x-full");
}

// Quitter le cinéma rouvre les deux panneaux (état enregistré au départ).
// On amène le panneau à l'état voulu au lieu de supposer qu'il est fermé.
async function setPanel(page, side, open) {
  const toggle = page.locator(side === "left"
    ? ".naviguide-sidebar-toggle--left"
    : ".naviguide-sidebar-toggle--right");
  if (await panelOpen(page, side) !== open) {
    await toggle.click();
    await expect.poll(() => panelOpen(page, side), { timeout: 5_000 }).toBe(open);
  }
  if (side === "left") {
    await expect(toggle).toHaveAttribute("aria-expanded", open ? "true" : "false");
  }
}

async function leftDrawerBox(page) {
  const drawer = panelLocator(page, "left");
  await expect.poll(async () => {
    const box = await drawer.boundingBox();
    return box ? box.x : -999;
  }).toBeGreaterThanOrEqual(-1);
  return drawer.boundingBox();
}

const iphone13 = devices["iPhone 13"];

test.describe("iPhone 13 — tiroir et barre sur deux lignes", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    userAgent: iphone13.userAgent,
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
  });

  test("NAV-M-01 M-02 : tiroir, commandes sur deux lignes, rien hors écran", async ({ page }) => {
    test.setTimeout(90_000);
    const apiUp = await officialUp(page);
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "GET /voyage/official absent — la mise en page mobile se vérifie sans elle",
      });
    }

    await page.goto("/");
    await dismissNotForNav(page);
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
    await leaveCinema(page);

    const toggle = page.locator(".naviguide-sidebar-toggle--left");
    await expect(toggle).toBeVisible();
    await setPanel(page, "left", true);
    await setPanel(page, "right", true);
    await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 10_000 });

    const openBands = await commandBands(page);
    expect(openBands.overflow, `commande hors écran tiroir ouvert : ${JSON.stringify(openBands)}`).toBe(false);
    expect(openBands.rows, `la barre doit tenir sur deux lignes : ${JSON.stringify(openBands)}`).toBe(2);
    expect(openBands.bar.x).toBeLessThanOrEqual(12);
    expect(openBands.bar.x + openBands.bar.w).toBeGreaterThanOrEqual(openBands.vw - 12);
    expect(openBands.bar.y + openBands.bar.h).toBeLessThanOrEqual(openBands.vh + 1);
    expect(openBands.bar.w).toBeGreaterThan(300);

    const panel = await leftDrawerBox(page);
    const bar = await page.getByTestId("film-bar").boundingBox();
    expect(panel.width).toBeGreaterThan(200);
    expect(panel.x + panel.width).toBeLessThanOrEqual(390);
    expect(panel.y + panel.height, "le tiroir recouvre la barre").toBeLessThanOrEqual(bar.y + 1);
    expect(boxesOverlap(panel, bar), "tiroir et barre se chevauchent").toBe(false);
    await expect.poll(async () => {
      const openToggle = await toggle.boundingBox();
      const drawer = await panelLocator(page, "left").boundingBox();
      if (!openToggle || !drawer) return false;
      return openToggle.x + openToggle.width <= 390
        && openToggle.x >= drawer.x + drawer.width - 2;
    }).toBe(true);
    await shot(page, "02-iphone-tiroir.webp");

    const right = panelLocator(page, "right");
    await expect.poll(async () => {
      const box = await right.boundingBox();
      return Boolean(box && box.x < 200 && box.x + box.width <= 391);
    }).toBe(true);
    const layers = page.getByTestId("layers-drawer");
    await expect(layers.locator("summary")).toBeVisible({ timeout: 10_000 });
    await layers.locator("summary").scrollIntoViewIfNeeded();
    if (!(await layers.evaluate((el) => el.open))) await layers.locator("summary").click();
    const zee = layers.getByRole("button", { name: "ZEE", exact: true });
    await expect(zee).toBeVisible({ timeout: 10_000 });
    await zee.scrollIntoViewIfNeeded();
    const rightBox = await right.boundingBox();
    const bar2 = await page.getByTestId("film-bar").boundingBox();
    expect(boxesOverlap(rightBox, bar2), "panneau des calques et barre se chevauchent").toBe(false);
    const zeeBox = await zee.boundingBox();
    expect(zeeBox.x).toBeGreaterThanOrEqual(0);
    expect(zeeBox.x + zeeBox.width).toBeLessThanOrEqual(390);
    expect(zeeBox.y).toBeGreaterThanOrEqual(0);
    expect(zeeBox.y + zeeBox.height).toBeLessThanOrEqual(844);
    expect(boxesOverlap(zeeBox, bar2), "ZEE recouvre la barre").toBe(false);
    await shot(page, "03-iphone-calques.webp");

    await setPanel(page, "left", false);
    const closedToggle = await toggle.boundingBox();
    expect(closedToggle.x).toBeGreaterThanOrEqual(0);
    expect(closedToggle.x + closedToggle.width).toBeLessThanOrEqual(390);
    const closed = await commandBands(page);
    expect(closed.overflow, `commande hors écran : ${JSON.stringify(closed)}`).toBe(false);
    expect(closed.rows, `la barre doit tenir sur deux lignes : ${JSON.stringify(closed)}`).toBe(2);
    expect(closed.bar.x).toBeLessThanOrEqual(12);
    expect(closed.bar.x + closed.bar.w).toBeGreaterThanOrEqual(closed.vw - 12);
    expect(closed.bar.y + closed.bar.h).toBeLessThanOrEqual(closed.vh + 1);
    await shot(page, "01-iphone-barre.webp");
  });

  test("NAV-M-03 : Tab montre le focus, Échap quitte le plein écran", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/");
    await dismissNotForNav(page);
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
    await leaveCinema(page);

    // La carte a beaucoup de liens avant le tiroir. On part du bouton du
    // panneau, puis Tab doit poser un anneau sur un contrôle du tiroir ou de la barre.
    await page.locator(".naviguide-sidebar-toggle--left").focus();
    await page.keyboard.press("Tab");
    let seen = null;
    for (let i = 0; i < 8 && !seen; i += 1) {
      seen = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const bar = el.closest?.(
          "[data-testid='film-bar'], .naviguide-sidebar-toggle, .naviguide-sidebar-drawer, .naviguide-sidebar-panel",
        );
        if (!bar) return null;
        const s = getComputedStyle(el);
        const width = parseFloat(s.outlineWidth) || 0;
        if (s.outlineStyle === "none" || width < 2) return null;
        const r = el.getBoundingClientRect();
        return { outline: s.outlineStyle, width, w: r.width, h: r.height };
      });
      if (!seen) await page.keyboard.press("Tab");
    }
    expect(seen, "aucun bouton de la barre ou du tiroir n'a pris le focus").toBeTruthy();
    expect(seen.outline).not.toBe("none");
    expect(seen.width).toBeGreaterThanOrEqual(2);
    expect(seen.w).toBeGreaterThan(0);
    expect(seen.h).toBeGreaterThan(0);

    const full = page.getByTestId("film-fullscreen");
    await full.click();
    await expect(full).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("sim-root")).toHaveClass(/film-fullscreen/);
    await page.keyboard.press("Escape");
    await expect(full).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("sim-root")).not.toHaveClass(/film-fullscreen/);
    await expect(page.locator(".naviguide-sidebar-toggle--left")).toBeVisible();
  });

  test("NAV-M-05 : poids de l'horloge si l'API répond", async ({ page }) => {
    test.setTimeout(90_000);
    const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
    if (!official || !official.ok()) {
      test.info().annotations.push({
        type: "sans API",
        description: "GET /voyage/official absent : poids de /voyage/official/clock non mesuré",
      });
      return;
    }
    const client = await page.context().newCDPSession(page);
    await client.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 150,
      downloadThroughput: (1.6 * 1024 * 1024) / 8,
      uploadThroughput: (750 * 1024) / 8,
    });
    const started = Date.now();
    const clock = await page.request.get("/voyage/official/clock", { timeout: 60_000 }).catch(() => null);
    const ms = Date.now() - started;
    if (!clock || !clock.ok()) {
      test.info().annotations.push({
        type: "horloge",
        description: `GET /voyage/official/clock sans corps exploitable (${ms} ms, 4G simulée)`,
      });
      return;
    }
    const body = await clock.body();
    test.info().annotations.push({
      type: "horloge",
      description: `${body.length} octets en ${ms} ms (4G simulée, 390×844)`,
    });
    expect(body.length).toBeGreaterThan(0);
  });
});

test.describe("bureau inchangé", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("à 1280 px la barre reste entre les panneaux, une seule rangée", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/");
    await dismissNotForNav(page);
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
    await leaveCinema(page);

    await setPanel(page, "left", false);
    await setPanel(page, "right", false);
    const commands = page.getByTestId("film-commands");
    await expect(commands).toBeVisible();
    const display = await commands.evaluate((el) => getComputedStyle(el).display);
    expect(display).not.toBe("contents");
    const resting = await commandBands(page);
    expect(resting.rows, `le bureau au repos tient sur une rangée : ${JSON.stringify(resting)}`).toBe(1);
    expect(resting.overflow).toBe(false);

    await setPanel(page, "left", true);
    await setPanel(page, "right", true);
    // La classe change tout de suite ; la translation dure encore.
    // On mesure quand le glissement est fini et le bord gauche du tiroir est à 0.
    await page.locator(".naviguide-sidebar-drawer, .naviguide-sidebar-panel.right-0").evaluateAll(async (els) => {
      await Promise.all(els.flatMap((el) => el.getAnimations().map((anim) => anim.finished)));
    });
    await expect.poll(async () => {
      const barBox = await page.getByTestId("film-bar").boundingBox();
      const panelBox = await panelLocator(page, "left").boundingBox();
      const rightBox = await panelLocator(page, "right").boundingBox();
      if (!barBox || !panelBox || !rightBox) return false;
      if (panelBox.x < -1) return false;
      const leftClear = barBox.x + 1 >= panelBox.x + panelBox.width && !boxesOverlap(panelBox, barBox);
      const rightClear = barBox.x + barBox.width <= rightBox.x + 1 && !boxesOverlap(rightBox, barBox);
      return leftClear && rightClear;
    }).toBe(true);
    const panel = await leftDrawerBox(page);
    const bar = await page.getByTestId("film-bar").boundingBox();
    expect(bar.x).toBeGreaterThanOrEqual(300);
    expect(bar.x + bar.width).toBeLessThanOrEqual(1280 - 300);
    expect(panel.height).toBeGreaterThan(700);
    expect(panel.x).toBeGreaterThanOrEqual(-1);
    expect(boxesOverlap(panel, bar)).toBe(false);
    await shot(page, "04-bureau.webp");
  });
});
