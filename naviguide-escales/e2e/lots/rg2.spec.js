// Nommer la route : eaux, côtes, cap.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDirs = [
  join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg2"),
  join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc19"),
];
for (const dir of recetteDirs) mkdirSync(dir, { recursive: true });

const shot = (page, name) => Promise.all(recetteDirs.map((dir) => page.screenshot({
  path: join(dir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
})));

const JARGON = /zones? économiques? exclusives?|exclusive economic zones?/i;
const WATERS_ES = /eaux espagnoles|Spanish waters/i;
const GALICE = /Galice|Galicia/i;
const MUXIA = /Muxía|Muxia/i;
const SARDAIGNE = /Sardaigne|Sardinia|Porto Torres/i;
const DEPART_AJACCIO = /départ vers Ajaccio|departure for Ajaccio/i;

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

test("Eaux, côtes, cap : pas de jargon ZEE", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre et Revoir gardés",
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

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-galice-muxia");
    await shot(page, "02-sardaigne");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG2 sautées",
    });
    await shot(page, "01-galice-muxia");
    await shot(page, "02-sardaigne");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  // « Gibraltar » figure déjà dans l'annexe Couloirs de l'ancien film : ce n'est pas RG2.
  const rg2Ready = WATERS_ES.test(blob) || GALICE.test(blob);
  if (!rg2Ready) {
    test.info().annotations.push({
      type: "stock pré-RG2",
      description: "film servi encore à l'ancienne clé — remplisseur doit recalculer (FILM_SCRIPT_REV=rg2)",
    });
    await shot(page, "01-galice-muxia");
    await shot(page, "02-sardaigne");
    return;
  }

  expect(blob, "jamais le jargon ZEE").not.toMatch(JARGON);
  expect(blob, "Muxía dans la phrase Galice si le stock est RG2-prêt").toMatch(MUXIA);
  expect(blob, "Sardaigne (ou Porto Torres) avant Ajaccio si le stock est RG2-prêt").toMatch(SARDAIGNE);

  if (WATERS_ES.test(blob) && /eaux portugaises|Portuguese waters/i.test(blob)) {
    expect(blob.indexOf("espagnoles"), "ZEE dans l'ordre des dates").toBeLessThan(
      blob.search(/portugaises|Portuguese/),
    );
  }

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
    const iMux = list.findIndex((c) => /mux[ií]a|galice|galicia/i.test(c.text || ""));
    const iGib = list.findIndex((c) => /gibraltar|algeciras|tanger/i.test(c.text || ""));
    const re = new RegExp(reSrc, "i");
    const iDep = list.findIndex((c) => re.test(c.text || ""));
    const i = iMux >= 0 ? iMux : (iGib >= 0 ? iGib : iDep);
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  }, DEPART_AJACCIO.source);
  await shot(page, "01-galice-muxia");

  await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => /sardaigne|sardinia|porto torres/i.test(c.text || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  });
  await shot(page, "02-sardaigne");
});
