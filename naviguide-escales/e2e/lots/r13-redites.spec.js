// Redites : un libellé une fois par écran.
// Sans API : le décompte innerText tient seul (repli route interne).
// GET /voyage/official : sondé ; nom du bateau / polaire chargée seulement si l'API répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-r13");

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r13/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function isChromeLabel(line) {
  const n = line.toLowerCase().replace(/\s+/g, " ").trim();
  if (/^à bord, maintenant/.test(n) || /^on board, now/.test(n)) return true;
  if (/^encore \d+$/.test(n) || /^still \d+$/.test(n)) return true;
  if (/^voir sur la carte/.test(n) || /^see on the map/.test(n)) return true;
  if (/fiche google maps|google maps sheet/.test(n)) return true;
  if (/^polaires?( chargées)?$/.test(n) || /^polars?( loaded)?$/.test(n)) return true;
  if (/^voir les polaires$/.test(n) || /^show polars$/.test(n)) return true;
  if (/^glissez un fichier( polaire)?$/.test(n) || /^drop a (polar )?file here$/.test(n)) return true;
  if (/^climatologie$/.test(n) || /^climatology$/.test(n)) return true;
  if (/^ne convient pas à la navigation/.test(n) || /^not (for|to be used for) navigation/.test(n)) return true;
  if (/^masquer le panneau$/.test(n) || /^hide (sidebar|panel)$/.test(n)) return true;
  if (/^distance totale$/.test(n) || /^total distance$/.test(n)) return true;
  if (/^prochaine escale$/.test(n) || /^next stop$/.test(n)) return true;
  if (/^escale précédente$/.test(n) || /^previous stop$/.test(n)) return true;
  if (/^masquer la barre$/.test(n) || /^hide the bar$/.test(n)) return true;
  return false;
}

function formatReport(labels, data) {
  const block = (title, rows) => {
    const body = rows.length
      ? rows.map(([n, line]) => `${n}\t${line}`).join("\n")
      : "";
    return `# ${title}\n${body}`;
  };
  return [
    block("même texte deux fois (libellés)", labels),
    "",
    block("données (information différente, conservées)", data),
    "",
  ].join("\n");
}

async function showToolsPanel(page) {
  const theme = page.getByRole("button", { name: /^(sombre|clair|dark|light)$/i });
  if (await theme.isVisible({ timeout: 1500 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect(theme).toBeVisible({ timeout: 10_000 });
}

async function showBothPanels(page) {
  await openLeftDrawer(page);
  await showToolsPanel(page);
}

async function settle(page) {
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  const box = page.getByTestId("expedition-box");
  if (await box.isVisible({ timeout: 4000 }).catch(() => false)) {
    await expect(box).toBeVisible();
  }
}

async function collectScreen(page) {
  await settle(page);
  return page.evaluate(() => {
    // Panneaux fermés (cinéma / translate) : leur innerText reste dans le
    // body. On les exclut le temps du décompte — la recette ne voit que l'écran.
    const panels = [...document.querySelectorAll(".naviguide-sidebar-panel")];
    const closed = panels.filter((el) => {
      const r = el.getBoundingClientRect();
      return r.right < 8 || r.left > window.innerWidth - 8;
    });
    const prev = closed.map((el) => el.style.display);
    closed.forEach((el) => { el.style.display = "none"; });
    const raw = document.body.innerText || "";
    // La ligne « Sources » de l'encadré Ici liste des producteurs (« zee · GEBCO · climatology · … ») : le mot
    // « climatology » y est un identifiant de source, pas un libellé d'écran — il ne compte pas comme redite.
    // (29 sept. : vert ou rouge selon que le sac /ici était arrivé au moment du décompte.)
    const sourcesText = [...document.querySelectorAll("[data-testid='ici-section-sources']")]
      .map((el) => el.innerText || "").join("\n");
    closed.forEach((el, i) => { el.style.display = prev[i]; });
    const lines = raw.split(/\n/).map((s) => s.trim()).filter((s) => s.length >= 8);
    const counts = new Map();
    for (const line of lines) counts.set(line, (counts.get(line) || 0) + 1);
    const duplicates = [...counts.entries()]
      .filter(([, n]) => n >= 2)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "fr"))
      .map(([line, n]) => [n, line]);
    const word = (re, text = raw) => {
      const m = text.match(re);
      return m ? m.length : 0;
    };
    const sourceLines = new Set(sourcesText.split(/\n/).map((s) => s.trim()).filter(Boolean));
    const rawSansSources = raw.split(/\n/).filter((l) => !sourceLines.has(l.trim())).join("\n");
    return {
      duplicates,
      climatologie: word(/climatolog(?:ie|y)/gi, rawSansSources),
      polaire: word(/polaires?|polars?/gi),
      boat: word(/l[eé]opard\s*46/gi),
    };
  });
}

function splitDuplicates(rows) {
  const labels = [];
  const data = [];
  for (const row of rows) {
    (isChromeLabel(row[1]) ? labels : data).push(row);
  }
  return { labels, data };
}

function writeReport(screen, rows) {
  mkdirSync(recetteDir, { recursive: true });
  const { labels, data } = splitDuplicates(rows);
  writeFileSync(join(recetteDir, `redites-${screen}.txt`), formatReport(labels, data), "utf8");
  return { labels, data };
}

async function enterDraw(page) {
  const drawBtn = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Draw your own route/i });
  await openLeftDrawer(page);
  await expect(drawBtn).toBeVisible({ timeout: 15_000 });
  await drawBtn.click();
  await expect(page.getByTestId("drawing-box")).toBeVisible({ timeout: 15_000 });
}

test("Aucune redite de libellé ; bateau / climatologie / Polaire une fois", async ({ page }) => {
  test.setTimeout(60_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — décompte innerText inchangé ; nom du bateau sauté s'il n'apparaît pas",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 12_000 });
  await showBothPanels(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showBothPanels(page);
  const suivre = await collectScreen(page);
  const suivreSplit = writeReport("suivre", suivre.duplicates);
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showBothPanels(page);
  const simulation = await collectScreen(page);
  const simulationSplit = writeReport("simulation", simulation.duplicates);
  await shot(page, "02-simulation");

  await enterDraw(page);
  const tracer = await collectScreen(page);
  const tracerSplit = writeReport("tracer", tracer.duplicates);
  await shot(page, "03-tracer");

  const { showRightPanel } = await import("../helpers.js");
  await showRightPanel(page);
  const droit = await collectScreen(page);
  const droitSplit = writeReport("panneau-droit", droit.duplicates);
  await shot(page, "04-panneau-droit");

  const screens = {
    suivre: { ...suivre, ...suivreSplit },
    simulation: { ...simulation, ...simulationSplit },
    tracer: { ...tracer, ...tracerSplit },
    droit: { ...droit, ...droitSplit },
  };
  for (const [name, data] of Object.entries(screens)) {
    expect(data.labels, `${name} : libellé deux fois\n${formatReport(data.labels, [])}`).toEqual([]);
    expect(data.climatologie, `${name} : climatologie ×${data.climatologie}`).toBeLessThanOrEqual(1);
    expect(data.polaire, `${name} : Polaire ×${data.polaire}`).toBeLessThanOrEqual(1);
  }

  if (droit.boat > 0 || apiUp) {
    const orders = page.getByTestId("skipper-orders");
    if (await orders.isVisible().catch(() => false)) {
      if (!(await orders.evaluate((el) => el.open))) {
        await orders.locator("summary").first().click();
      }
      const boatRow = page.getByTestId("skipper-boat");
      await expect(boatRow).toBeVisible();
      const outside = await page.evaluate(() => {
        const body = document.body.innerText || "";
        const keepEl = document.querySelector("[data-testid='skipper-boat'], [data-testid='polar-box']");
        const keepBoxes = [...document.querySelectorAll("[data-testid='skipper-boat'], [data-testid='polar-box']")];
        const inside = keepBoxes.map((el) => el.innerText || "").join("\n");
        const re = /l[eé]opard\s*46/gi;
        const all = body.match(re) || [];
        const keep = inside.match(re) || [];
        return { all: all.length, keep: keep.length };
      });
      if (outside.all === 0 && !apiUp) {
        test.info().annotations.push({
          type: "sans API",
          description: "nom du bateau absent — polar non chargée",
        });
      } else {
        expect(outside.all, "Léopard 46 hors Paramètres avancés").toBe(outside.keep);
        expect(outside.keep, "Léopard 46 une fois dans Paramètres avancés").toBeLessThanOrEqual(1);
      }
    } else if (apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "Paramètres avancés absents — nom du bateau non vérifié",
      });
    }
  }
});
