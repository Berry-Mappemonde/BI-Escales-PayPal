// Page carnet : récit puis journal daté, mêmes textes que le panneau.
// L'onglet Journal reste à sa place.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openJournalTab, probeOfficial, showLeftPanel } from "../helpers.js";

const CLOCK = {
  t0: "2026-05-15T08:00:00.000Z",
  marks: [
    { name: "Saint-Maur", nm: 0, filmNm: 0, iso: "2026-05-15T08:00:00.000Z", lat: 46.8, lon: 1.4 },
  ],
  vertices: [],
};

const MOMENTS = {
  moments: [
    {
      voyageId: "official",
      seq: 1,
      t: "2026-05-15T08:00:00.000Z",
      pos: { lat: 46.2, lon: -1.5 },
      signature: "cb1-iroise",
      changes: [{ kind: "amp", score: 1, title: "Iroise", fact: "Iroise" }],
    },
  ],
};

const FOLLOW_TABS = ["ici-tab-now", "ici-tab-story", "ici-tab-journal", "ici-tab-review"];

async function stubVoyage(page) {
  await page.route("**/voyage/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/moments")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(MOMENTS) });
      return;
    }
    if (path.endsWith("/clock")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(CLOCK) });
      return;
    }
    if (path.endsWith("/journal")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ latest: [], count: 0 }),
      });
      return;
    }
    if (path.endsWith("/official")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ clock: CLOCK, voyageId: "official" }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.route("**/logbook/**", (route) => route.fulfill({
    status: 404,
    contentType: "application/json",
    body: "{}",
  }));
}

async function visibleTabIds(page) {
  return page.getByTestId("ici-tabs").getByRole("tab", { includeHidden: false }).evaluateAll((els) => (
    els.map((el) => el.getAttribute("data-testid"))
  ));
}

test("le carnet s'ouvre, récit puis journal, onglet Journal inchangé", async ({ page }) => {
  test.setTimeout(90_000);
  await stubVoyage(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await showLeftPanel(page);
  await openJournalTab(page);

  await expect(page.getByTestId("ici-journal-entry").filter({ hasText: /Iroise/ }).first()).toBeVisible({ timeout: 20_000 });
  expect(await visibleTabIds(page)).toEqual(FOLLOW_TABS);
  await expect(page.getByTestId("carnet-open")).toHaveCount(1);
  await expect(page.getByTestId("carnet-open")).toBeVisible();
  await expect(page.getByTestId("carnet-open")).toHaveAttribute("href", /\?page=carnet/);

  await page.getByTestId("carnet-open").click();
  await expect(page).toHaveURL(/[?&]page=carnet(?:&|$)/);
  await expect(page.getByTestId("carnet-de-bord")).toBeVisible();
  await expect(page.getByTestId("carnet-title")).toHaveText("Carnet de bord");

  const chapter = page.getByTestId("carnet-chapter").first();
  await expect(chapter).toBeVisible({ timeout: 20_000 });
  await expect(chapter).toContainText(/Berry-Mappemonde|Saint-Maur/);
  const entry = page.getByTestId("carnet-entry").filter({ hasText: /Iroise/ }).first();
  await expect(entry).toBeVisible({ timeout: 20_000 });

  const storyBeforeJournal = await page.evaluate(() => {
    const chapterEl = document.querySelector("[data-testid='carnet-chapter']");
    const entryEl = document.querySelector("[data-testid='carnet-entry']");
    if (!chapterEl || !entryEl) return false;
    return Boolean(chapterEl.compareDocumentPosition(entryEl) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(storyBeforeJournal).toBe(true);

  await page.getByTestId("carnet-back").click();
  await expect(page).not.toHaveURL(/[?&]page=carnet(?:&|$)/);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await showLeftPanel(page);
  await openJournalTab(page);
  expect(await visibleTabIds(page)).toEqual(FOLLOW_TABS);
  await expect(page.getByTestId("ici-journal-list")).toBeVisible();
  await expect(page.getByTestId("ici-journal-entry").filter({ hasText: /Iroise/ }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("carnet-de-bord")).toHaveCount(0);
});

// Ma route : deux points nommés tracés, Suivre, puis le carnet depuis le Journal.
const MY_START = { lat: 46.15, lon: -1.16, name: "La Rochelle" };
const MY_END = { lat: 45.90, lon: -1.55, name: "Pertuis" };

async function stubSeaRoute(page) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const coords = [
      [Number(url.searchParams.get("start_lon")), Number(url.searchParams.get("start_lat"))],
      [Number(url.searchParams.get("end_lon")), Number(url.searchParams.get("end_lat"))],
    ];
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} }),
    });
  });
}

// Film et moments de ma route servis tels que le serveur les rend une fois prêts :
// sur le stock figé, le film perso peut rester « preparing » plus de 2 min (voir
// dm8-recit-ma-route), ce test vérifie le carnet, pas la préparation du film.
// POST /voyage et le voyage officiel restent ceux de l'API.
const MY_FILM_CHAPTERS = [
  "Départ de La Rochelle, cap au sud-ouest vers le Pertuis.",
  "Arrivée au Pertuis après une courte traversée.",
];

async function stubCustomVoyage(page) {
  await page.route(/\/voyage\/(?!official\b)[^/?]+\/(film|moments)(\?|$)/, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const url = new URL(route.request().url());
    const [, voyageId, kind] = url.pathname.match(/\/voyage\/([^/]+)\/(film|moments)$/) || [];
    if (kind === "film") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          voyageId,
          source: "rules",
          chapters: MY_FILM_CHAPTERS.map((text) => ({ text })),
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        voyageId,
        moments: [
          {
            voyageId,
            seq: 1,
            t: "2026-05-15T10:00:00.000Z",
            pos: { lat: 46.0, lon: -1.4 },
            signature: "cb1-pertuis",
            changes: [{ kind: "amp", score: 1, title: "Pertuis charentais", fact: "Pertuis charentais" }],
          },
        ],
      }),
    });
  });
}

test("ma route : le carnet reprend le récit et le journal de ma route", async ({ page }) => {
  test.setTimeout(180_000);
  await stubSeaRoute(page);
  await stubCustomVoyage(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  const apiUp = Boolean(await probeOfficial(page));
  test.skip(!apiUp, "sans API : film et journal de ma route indisponibles");

  await page.getByTestId("view-tracer").click();
  await page.getByTestId("route-switch-draw").click();
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  for (const [i, pt] of [MY_START, MY_END].entries()) {
    await page.evaluate(({ lat, lon, name }) => window.__naviguideAddDrawnPoint(lat, lon, { name }), pt);
    await page.waitForFunction((n) => (window.__naviguideDrawn?.points?.length || 0) >= n, i + 1, { timeout: 10_000 });
  }
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await showLeftPanel(page);
  await expect(page.getByTestId("route-switch-custom")).toBeVisible({ timeout: 10_000 });
  await openJournalTab(page);
  await expect(page.getByTestId("carnet-open")).toHaveCount(1);

  await page.getByTestId("carnet-open").click();
  await expect(page).toHaveURL(/[?&]page=carnet(?:&|$)/);
  await expect(page.getByTestId("carnet-de-bord")).toBeVisible();
  await expect(page.getByTestId("carnet-chapter").filter({ hasText: /La Rochelle|Pertuis/ }).first())
    .toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("carnet-entry").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("carnet-chapter").filter({ hasText: /Saint-Maur/ })).toHaveCount(0);
});
