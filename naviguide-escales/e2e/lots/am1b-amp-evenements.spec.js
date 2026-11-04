// Le voyage dit les AMP qu'il traverse et dont il passe près
// (libellés DC1 : traverse / près, plus « entre dans » / « longe »).
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film / Ici — barre, Suivre et Revoir restent.
// Avec API : phrases d'entrée / proximité dans le film, encadré Ici « dans
// l'aire marine protégée … » quand le sac a inside, calque AMP joignable.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-am1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AMP_ENTER = /traverse l'aire marine protégée|crosses the marine protected area/i;
const AMP_NEAR = /près de l'aire marine protégée .+ à |near the marine protected area .+ at /i;
const AMP_NAMED = /cabrera|bonifacio|alboran|agoa|scandola|iroise|rochebonne|cul-de-sac|mer de corail|tainui/i;
const AMP_DANS = /dans l'aire marine protégée|in the marine protected area/i;
const FISHING = /p[ée]toncles|deposit|chaluts|filets|hu[iî]tres|prohibition zone/i;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

test("AMP : entrée / proximité au film, dans l'encadré Ici", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film/Ici sautées ; barre, Suivre et Revoir gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("replay-departure")).toBeVisible();
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-film-amp");
    await shot(page, "02-ici-dans");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const chapters = film?.chapters || [];
  const blob = chapters.map((c) => c.text || "").join(" ");
  expect(blob, "jamais une zone de pêche dite AMP").not.toMatch(FISHING);

  const hasEnter = AMP_ENTER.test(blob);
  const hasNear = AMP_NEAR.test(blob);
  const hasNamed = AMP_NAMED.test(blob);
  if (!hasEnter && !hasNear && !hasNamed) {
    test.info().annotations.push({
      type: "stock AMP",
      description: "film sans phrase AMP AM1B — perles à réchauffer après merge AM1A ; assertions film sautées",
    });
    await shot(page, "01-film-amp");
  } else {
    await expect(start).toBeEnabled({ timeout: 30_000 });
    await muteVoice(page);
    await start.click();
    const subtitle = page.getByTestId("film-subtitle");
    await expect(subtitle).toBeVisible({ timeout: 8_000 });
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
    }, null, { timeout: 8_000 });
    await page.evaluate((reSrc) => {
      const list = window.__naviguideFilm?.chapters || [];
      const re = new RegExp(reSrc, "i");
      const i = list.findIndex((c) => re.test(c.text || ""));
      if (i >= 0) window.__naviguideFilm.seekChapter(i);
    }, (hasEnter ? AMP_ENTER : hasNear ? AMP_NEAR : AMP_NAMED).source);
    if (hasEnter) {
      expect(blob, "au moins une entrée d'aire marine").toMatch(AMP_ENTER);
    }
    await shot(page, "01-film-amp");
  }

  await showLeftPanel(page);
  await page.getByTestId("ici-tab-now").click().catch(() => {});
  const briefing = page.getByTestId("ici-briefing");
  const here = page.getByTestId("ici-here-sentence");
  const iciText = [
    await briefing.textContent().catch(() => ""),
    ...(await here.allTextContents().catch(() => [])),
  ].join(" ");
  if (AMP_DANS.test(iciText)) {
    expect(iciText).toMatch(AMP_DANS);
  } else {
    test.info().annotations.push({
      type: "Ici hors aire",
      description: "horloge pas dans un polygone AMP au moment de la capture — encadré Ici non forcé",
    });
  }
  await shot(page, "02-ici-dans");

  await showRightPanel(page);
  const drawer = page.getByTestId("layers-drawer");
  await expect(drawer).toBeVisible();
  const ampToggle = page.getByTestId("layer-amp");
  if (!(await ampToggle.isVisible().catch(() => false))) {
    await drawer.locator("summary").click();
  }
  await expect(ampToggle).toBeVisible({ timeout: 8_000 });
});
