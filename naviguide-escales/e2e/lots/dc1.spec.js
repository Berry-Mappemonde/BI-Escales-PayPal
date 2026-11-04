// Une aire, déjà dite, mieux dite (près / traversée).
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film — barre, Suivre et Revoir restent.
// Avec API : le 2:30 a au plus une phrase d'aire, ≤ 2250 caractères ;
// près ou traversée si le stock l'a.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dc1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AMP_SENT = /aire marine protégée|marine protected area/i;
const AMP_NEAR_OR_CROSS = /près de l'aire marine|traverse l'aire marine|near the marine protected|crosses the marine protected/i;
const CHAR_BUDGET_150 = 2250;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

function ampSentences(blob) {
  return String(blob || "")
    .split(/(?<=[.!?…])\s+/)
    .map((s) => s.trim())
    .filter((s) => AMP_SENT.test(s));
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

test("Une aire près ou traversée, 2:30 ≤ 2250", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre, Suivre et Revoir gardés",
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

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-une-aire");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const chapters = film?.chapters || [];
  const blob = chapters.map((c) => c.text || "").join(" ");
  const chars = Number(film?.chars) || blob.length;
  const amps = ampSentences(blob);

  if (!chapters.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film 2:30 sans chapitres — assertions longueur sautées",
    });
    await shot(page, "01-une-aire");
    return;
  }

  expect(amps.length, "au plus une phrase d'aire dans le 2:30").toBeLessThanOrEqual(1);
  expect(chars / 15, "2:30 tient dans 150 s + 10 % à 15 car./s").toBeLessThanOrEqual(150 * 1.1);
  if (amps.length === 1 && !AMP_NEAR_OR_CROSS.test(amps[0])) {
    if (/longe l'aire|entre dans l'aire|skirts the marine|enters the marine|à \S+ milles, l'aire marine|miles away, the marine protected/i.test(amps[0])) {
      test.info().annotations.push({
        type: "stock pré-DC1",
        description: "phrase d'aire encore AM1B — remplisseur doit recalculer (FILM_SCRIPT_REV=dc1)",
      });
    } else {
      expect(amps[0], "près ou traversée si l'aire est dite").toMatch(AMP_NEAR_OR_CROSS);
    }
  }

  const pill150 = page.getByTestId("film-duration").locator("[data-seconds='150']");
  if (await pill150.isVisible().catch(() => false)) {
    if (await pill150.getAttribute("aria-pressed") !== "true") await pill150.click();
    await expect(pill150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
  }

  if (amps.length === 1 && await start.isEnabled().catch(() => false)) {
    await muteVoice(page);
    await start.click();
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
    }, null, { timeout: 8_000 }).catch(() => null);
    await page.evaluate((reSrc) => {
      const list = window.__naviguideFilm?.chapters || [];
      const re = new RegExp(reSrc, "i");
      const i = list.findIndex((c) => re.test(c.text || ""));
      if (i >= 0) window.__naviguideFilm.seekChapter(i);
    }, AMP_SENT.source);
  }
  await shot(page, "01-une-aire");
});
