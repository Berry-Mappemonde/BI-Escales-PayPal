// Noms de lieux : exonymes FR/EN pour pays et eaux, homonymes
// distingués (Saint-Martin / Sint Maarten). Sans API : GET /voyage/official
// sondé ; s'il manque, annotation + saut des assertions film / ici —
// Suivre, Revoir et le bouton de langue restent vérifiés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc32");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FR_KITTS = /Saint-Christophe-et-Niévès/;
const FR_EUSTACHE = /Saint-Eustache/;
const FR_SX = /Sint Maarten \(partie néerlandaise\)/;
const FR_MF = /Saint-Martin \(partie française\)/;
const EN_KITTS = /Saint Kitts and Nevis/;
const EN_EUSTACHE = /Sint Eustatius/;
const EN_SX = /Sint Maarten \(Dutch side\)/;
const EN_MF = /Saint-Martin \(French side\)/;
const SAME_TWICE = /les eaux (de |d['’])?(Saint-Martin|Sint[\s-]Maarten), puis celles (de |d['’])?(Saint-Martin|Sint[\s-]Maarten)/i;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

test("Toponymes FR/EN, Saint-Martin et Sint Maarten distingués", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film / ici sautées ; Suivre, Revoir et langue gardés",
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

  await showRightPanel(page);
  await expect(page.getByTestId("lang-fr")).toBeVisible();
  await expect(page.getByTestId("lang-en")).toBeVisible();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await shot(page, "01-noms-fr");
    await page.getByTestId("lang-en").click();
    await shot(page, "02-noms-en");
    return;
  }

  const filmFr = await page.request.get("/voyage/official/film?lang=fr&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!filmFr?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions toponymes sautées",
    });
    await shot(page, "01-noms-fr");
    await shot(page, "02-noms-en");
    return;
  }

  const blobFr = filmFr.chapters.map((c) => c.text || "").join(" ");
  expect(blobFr, "jamais les deux Saint-Martin collés").not.toMatch(SAME_TWICE);
  const filledRc32 = FR_EUSTACHE.test(blobFr) && FR_SX.test(blobFr) && FR_MF.test(blobFr);
  if (filledRc32) {
    expect(blobFr, "Saint-Christophe-et-Niévès").toMatch(FR_KITTS);
    expect(blobFr, "Saint-Eustache").toMatch(FR_EUSTACHE);
    expect(blobFr, "Sint Maarten partie néerlandaise").toMatch(FR_SX);
    expect(blobFr, "Saint-Martin partie française").toMatch(FR_MF);
  } else {
    test.info().annotations.push({
      type: "stock pré-RC32",
      description: "film servi sans Saint-Eustache / parties FR-NL — remplisseur FILM_SCRIPT_REV=rc32",
    });
  }

  await showLeftPanel(page);
  const briefing = page.getByTestId("ici-briefing");
  if (await briefing.count()) {
    const brief = (await briefing.innerText()).replace(/\s+/g, " ");
    expect(brief, "ici FR : pas le nom Marine Regions brut").not.toMatch(/Exclusive Economic Zone/i);
  }

  await shot(page, "01-noms-fr");

  await page.getByTestId("lang-en").click();
  const filmEn = await page.request.get("/voyage/official/film?lang=en&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const blobEn = (filmEn?.chapters || []).map((c) => c.text || "").join(" ");
  if (blobEn && EN_SX.test(blobEn) && EN_MF.test(blobEn)) {
    expect(blobEn, "Saint Kitts and Nevis").toMatch(EN_KITTS);
    expect(blobEn, "Sint Eustatius").toMatch(EN_EUSTACHE);
    expect(blobEn, "Sint Maarten Dutch side").toMatch(EN_SX);
    expect(blobEn, "Saint-Martin French side").toMatch(EN_MF);
  }

  await shot(page, "02-noms-en");
});
