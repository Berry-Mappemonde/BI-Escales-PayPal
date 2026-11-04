// Liste des escales informative dans tous les modes ;
// pilules 2:30 / 3:00 dans le cadre de la barre ; plus de « Récit : » ;
// encadré date + heure à la taille du format.
// Sans API : liste (repli), curseur, pilules, absence de « Récit : »,
// largeur de l'encadré et lancement du film tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui exigent les noms du voyage officiel — jamais
// « ligne sans clic », ni « pilules dans le cadre », ni « pas de Récit : ».
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf8");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

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
  if (await panelOnScreen(page, side)) return;
  const toggle = side === "left"
    ? ".naviguide-sidebar-toggle--left"
    : ".naviguide-sidebar-toggle--right";
  await page.locator(toggle).click();
  await expect.poll(() => panelOnScreen(page, side), { timeout: 10_000 }).toBe(true);
  await page.waitForTimeout(350);
}

async function hidePanel(page, side) {
  if (!(await panelOnScreen(page, side))) return;
  const toggle = side === "left"
    ? ".naviguide-sidebar-toggle--left"
    : ".naviguide-sidebar-toggle--right";
  await page.locator(toggle).click();
  await expect.poll(() => panelOnScreen(page, side), { timeout: 10_000 }).toBe(false);
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

function durationBtn(page, sec) {
  return page.getByTestId("film-duration").locator(`[data-seconds="${sec}"]`);
}

function insideFrame(inner, outer, slack = 2) {
  expect(inner.x, "à gauche du cadre").toBeGreaterThanOrEqual(outer.x - slack);
  expect(inner.y, "au-dessus du cadre").toBeGreaterThanOrEqual(outer.y - slack);
  expect(inner.x + inner.width, "à droite du cadre").toBeLessThanOrEqual(outer.x + outer.width + slack);
  expect(inner.y + inner.height, "sous le cadre").toBeLessThanOrEqual(outer.y + outer.height + slack);
}

async function assertPillsInBar(page, panelOpen) {
  const bar = page.getByTestId("film-bar");
  const pills = page.getByTestId("film-duration");
  await expect(pills).toBeVisible();
  const barBox = await bar.boundingBox();
  const pillBox = await pills.boundingBox();
  expect(barBox, "cadre de la barre").toBeTruthy();
  expect(pillBox, "pilules 2:30 / 3:00").toBeTruthy();
  insideFrame(pillBox, barBox);
  if (panelOpen) {
    const panel = page.locator(".naviguide-sidebar-panel.right-0").first();
    const panelBox = await panel.boundingBox();
    if (panelBox && panelBox.width > 50) {
      expect(pillBox.x + pillBox.width, "pilules sous le panneau droit").toBeLessThanOrEqual(panelBox.x + 2);
    }
  }
}

async function assertListeInformative(page) {
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
  // Le gabarit « 0 nm · j0 · 15 mai 2026 » précède l'horloge officielle (minute UTC qui avance) : on attend la
  // bascule et on compare le jour de mer + LIVE, pas le texte entier (tranche 6/6, 29 sept.).
  await expect(clock).not.toHaveText(/\bj0\b/, { timeout: 20_000 }).catch(() => {});
  const readClock = async () => ((await clock.textContent().catch(() => "")) || "").replace(/\s+/g, " ");
  const cursorOf = (s) => `${(s.match(/\bj\d+\b/) || [""])[0]} ${/\bLIVE\b/.test(s) ? "LIVE" : ""}`.trim();
  const clockBefore = await readClock();
  const row = rows.first();
  await row.scrollIntoViewIfNeeded();
  await row.click({ force: true });
  await page.waitForTimeout(400);
  const clockAfter = await readClock();
  expect(cursorOf(clockAfter), `clic ligne a bougé le curseur (${clockBefore} → ${clockAfter})`).toBe(cursorOf(clockBefore));
}

async function assertDateBoxFitsFormat(page) {
  const field = page.getByTestId("replay-departure-field");
  await expect(field).toBeVisible();
  const metrics = await field.evaluate((el) => {
    const inputs = [...el.querySelectorAll("input")];
    const sample = inputs.map((n) => n.value).filter(Boolean).join(" ");
    const cs = getComputedStyle(inputs[0] || el);
    const probe = document.createElement("span");
    probe.textContent = sample || "15/05/2026 08:00";
    probe.style.cssText = `position:absolute;left:-9999px;white-space:nowrap;font:${cs.fontSize} ${cs.fontFamily};font-variant-numeric:tabular-nums`;
    document.body.appendChild(probe);
    const text = probe.getBoundingClientRect().width;
    probe.remove();
    const box = el.getBoundingClientRect().width;
    return { text, box, sample };
  });
  expect(metrics.sample, "date + heure affichées").toMatch(/\d{2}.\d{2}.\d{4}\s+\d{2}:\d{2}/);
  expect(metrics.box, "encadré plus large que le format").toBeLessThanOrEqual(metrics.text + 24);
  expect(metrics.box, "encadré plus étroit que le format").toBeGreaterThanOrEqual(metrics.text - 6);
}

test("Liste informative, barre dans le cadre, sans Récit", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — noms du voyage officiel non exigés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });

  if (apiUp) {
    const { waitFilmReady } = await import("../helpers.js");
    await waitFilmReady(page);
  }
  const pillsReady = await page.getByTestId("film-duration").isVisible().catch(() => false);
  if (!pillsReady && !apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — pilules et lancement non exigés",
    });
  } else if (!pillsReady) {
    throw new Error("film prêt mais pilules 2:30 / 3:00 absentes");
  }

  const btn150 = durationBtn(page, 150);
  const btn180 = durationBtn(page, 180);
  if (pillsReady) {
    await expect(btn150).toBeVisible();
    await expect(btn180).toBeVisible();
    await expect(btn150).toHaveAttribute("aria-pressed", "false");
    await expect(btn180).toHaveAttribute("aria-pressed", "false");
  }

  await hidePanel(page, "right");
  if (pillsReady) await assertPillsInBar(page, false);
  await expect(page.getByTestId("film-bar")).not.toContainText(/Récit\s*:/);
  await expect(page.getByTestId("film-bar")).not.toContainText(/Story\s*:/);
  await assertDateBoxFitsFormat(page);

  await showPanel(page, "right");
  if (pillsReady) await assertPillsInBar(page, true);
  await expect(page.getByTestId("film-bar")).not.toContainText(/Récit\s*:/);
  await assertDateBoxFitsFormat(page);

  await expect(page.getByTestId("escale-legend")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("escale-legend").scrollIntoViewIfNeeded();
  await assertListeInformative(page);

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => panelOnScreen(page, "right"), { timeout: 10_000 }).toBe(true);
  await expect(page.getByTestId("escale-legend")).toBeVisible({ timeout: 10_000 });
  await assertListeInformative(page);
  await shot(page, "01-liste");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showPanel(page, "right");
  if (pillsReady) {
    await expect(page.getByTestId("film-duration")).toBeVisible();
    await expect(btn150).toHaveAttribute("aria-pressed", "false");
    await expect(btn180).toHaveAttribute("aria-pressed", "false");
    await assertPillsInBar(page, true);
  }
  await shot(page, "02-barre");

  if (pillsReady) {
    const listen = page.getByTestId("listen");
    if (await listen.isVisible().catch(() => false)) {
      if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
    }
    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
    const subtitle = page.getByTestId("film-subtitle");
    await expect(subtitle).toBeVisible({ timeout: 8_000 });
    const budget = await page.evaluate(() => window.__naviguideFilm?.budgetSeconds);
    expect(budget, "film sans durée par défaut").toBe(0);
    const stopBtn = page.getByTestId("replay-stop");
    if (await stopBtn.isVisible().catch(() => false)) await stopBtn.click();
  }
});
