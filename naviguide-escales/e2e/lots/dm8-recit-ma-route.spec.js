// Suivre me rejoue MA route et me la raconte.
// Tracer → deux points nommés → Terminer → Suivre : Revoir joue
// GET /voyage/{id}/film (jamais le brut local) ; Journal = moments DM8A ;
// Revue du plan = ma jambe ; Maintenant masqué. Pilule Berry = film officiel.
// Sans API : sonde GET /voyage/official et saute Revoir actif / sous-titre /
// journal non vide ; onglets, bouton grisé « en préparation » et pilules restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  dismissNotForNav,
  openJournalTab,
  openReviewTab,
  probeOfficial,
  showLeftPanel,
  waitFilmCanStart,
} from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm8");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const PILL_ON = /bg-blue-600\/30/;

// Corde courte nommée (La Rochelle → Pertuis, ~20 nm) : les moments et le
// film perso deviennent ready dans le timeout. La recette porteur reste la
// transat La Rochelle → Antilles (données réelles du poste).
const START = { lat: 46.15, lon: -1.16, name: "La Rochelle" };
const END = { lat: 45.90, lon: -1.55, name: "Pertuis" };

async function stubRoute(page) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
        properties: {},
      }),
    });
  });
}

async function drawTwoPoints(page, a, b) {
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("route-switch-draw").click();
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon, name }) => window.__naviguideAddDrawnPoint(lat, lon, { name }), a);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await page.evaluate(({ lat, lon, name }) => window.__naviguideAddDrawnPoint(lat, lon, { name }), b);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

const JOURNAL_MORNING = [
  {
    t: "2026-10-18T08:00:00Z",
    signature: "dep",
    seq: 0,
    pos: { lat: 46.15, lon: -1.16 },
    changes: [{ kind: "regime", score: 1, title: "vents d'ouest", fact: "" }],
  },
  {
    t: "2026-10-18T11:00:00Z",
    signature: "h11",
    seq: 1,
    pos: { lat: 46.1, lon: -1.3 },
    changes: [{ kind: "regime", score: 1, title: "allure stable", fact: "" }],
  },
];

const JOURNAL_CROSSING = [
  ...JOURNAL_MORNING,
  {
    t: "2026-12-02T08:00:00Z",
    signature: "eaux",
    seq: 2,
    pos: { lat: 36.0, lon: -20.0 },
    changes: [{ kind: "zee-enter", score: 2, title: "eaux espagnoles", fact: "" }],
  },
  {
    t: "2027-01-15T08:00:00Z",
    signature: "arrivee",
    seq: 3,
    pos: { lat: 45.9, lon: -1.55 },
    changes: [{ kind: "escale", score: 3, title: "Arrivée à Pertuis", fact: "" }],
  },
];

async function stubCustomMoments(page) {
  let gets = 0;
  await page.route(/\/voyage\/[^/]+\/moments(?:\?|$)/, async (route) => {
    const url = route.request().url();
    if (/\/voyage\/official\/moments/.test(url)) {
      await route.continue();
      return;
    }
    gets += 1;
    const preparing = gets === 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(preparing
        ? { status: "preparing", moments: JOURNAL_MORNING, coverageNm: 30, totalNm: 3200 }
        : { status: "ready", moments: JOURNAL_CROSSING, coverageNm: 3200, totalNm: 3200 }),
    });
  });
}

async function expectJournalCrossing(page) {
  await openJournalTab(page);
  const entries = page.getByTestId("ici-journal-entry");
  await expect(entries.first()).toBeVisible({ timeout: 20_000 });
  expect(await entries.count()).toBeGreaterThan(0);
  await expect.poll(async () => {
    const text = (await entries.allInnerTexts()).join("\n");
    return /arriv|eaux|mer\b|zee|\beez\b|exclusive|côte|coast/i.test(text);
  }, { timeout: 20_000 }).toBe(true);
}

test("Suivre × ma route : Revoir, Journal, Revue ; Berry intact", async ({ page }) => {
  test.setTimeout(180_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  const customFilms = [];
  const officialFilms = [];
  const voyageCreates = [];
  page.on("request", (req) => {
    const url = req.url();
    if (req.method() === "POST" && /\/voyage(\?|$)/.test(url)) voyageCreates.push(url);
    if (url.includes("/voyage/official/film")) officialFilms.push(url);
    if (/\/voyage\/(?!official)[^/?]+\/film/.test(url)) customFilms.push(url);
  });

  await stubRoute(page);
  await stubCustomMoments(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — Revoir actif, sous-titre et journal non vides non exigés",
    });
  }

  await drawTwoPoints(page, START, END);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await showLeftPanel(page);
  const customPill = page.getByTestId("route-switch-custom");
  await expect(customPill).toBeVisible({ timeout: 10_000 });
  expect((await customPill.getAttribute("class")) || "").toMatch(PILL_ON);

  const tabs = page.getByTestId("ici-tabs").getByRole("tab", { includeHidden: false });
  await expect(tabs).toHaveCount(3);
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();

  await openReviewTab(page);
  await expect(page.getByTestId("plan-review")).toBeVisible();

  const replayStart = page.getByTestId("replay-start");
  await expect(replayStart).toBeVisible();
  if (!(await replayStart.isEnabled())) {
    await expect(replayStart).toHaveAttribute("title", /en préparation|preparing/);
  }

  if (!apiUp) {
    await shot(page, "01-revoir-ma-route");
    await openJournalTab(page);
    await shot(page, "02-journal");
    await page.getByTestId("route-switch-berry").click();
    await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
      timeout: 8_000,
    }).toMatch(PILL_ON);
    await expect(page.getByTestId("ici-tab-now")).toBeVisible();
    expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
    return;
  }

  await expect.poll(() => voyageCreates.length, { timeout: 30_000 }).toBeGreaterThan(0);
  await expect.poll(() => customFilms.length, { timeout: 30_000 }).toBeGreaterThan(0);

  const ready = await waitFilmCanStart(page, 120_000);
  if (!ready) {
    test.info().annotations.push({
      type: "film perso",
      description: "GET /voyage/{id}/film encore preparing après 2 min — Revoir actif non exigé",
    });
    await shot(page, "01-revoir-ma-route");
    await expectJournalCrossing(page);
    await shot(page, "02-journal");
    expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
    return;
  }

  await muteVoice(page);
  await replayStart.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("film-subtitle")).toContainText(/La Rochelle/, { timeout: 15_000 });
  await shot(page, "01-revoir-ma-route");

  await expectJournalCrossing(page);
  await shot(page, "02-journal");

  const officialBefore = officialFilms.length;
  await page.getByTestId("replay-stop").click().catch(() => {});
  await page.getByTestId("route-switch-berry").click();
  await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect.poll(() => officialFilms.length, { timeout: 20_000 }).toBeGreaterThan(officialBefore);

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
