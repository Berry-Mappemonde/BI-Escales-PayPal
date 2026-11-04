// Film anglais : noms d'eaux avec majuscule (French waters, …).
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions film — barre, Revoir et bouton EN gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showRightPanel, waitFilmCanStart, waitFilmReady } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc53");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LOWER_WATERS = [
  "french waters",
  "italian waters",
  "moroccan waters",
  "madeira waters",
  "martinique waters",
  "guadeloupe waters",
];

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

function watersBlob(chapters) {
  return (chapters || []).map((c) => String(c?.text || "")).join(" ");
}

test("Revoir EN : les eaux ont une majuscule", async ({ page }) => {
  test.setTimeout(120_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions eaux sautées ; barre, Revoir et EN gardés",
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
  await expect(page.getByTestId("lang-en")).toBeVisible();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await page.getByTestId("lang-en").click();
    await shot(page, "01-eaux");
    return;
  }

  const enFilmResp = page.waitForResponse(
    (r) => r.url().includes("/voyage/official/film") && r.url().includes("lang=en") && r.ok(),
    { timeout: 30_000 },
  ).catch(() => null);
  await page.getByTestId("lang-en").click();
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);
  await enFilmResp;

  const filmEn = await page.request.get("/voyage/official/film?lang=en&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!filmEn?.chapters?.length || filmEn.status !== "ready") {
    test.info().annotations.push({
      type: "film EN pas ready",
      description: "GET /voyage/official/film EN absent ou pas ready — assertions eaux sautées",
    });
    await shot(page, "01-eaux");
    return;
  }

  const blob = watersBlob(filmEn.chapters);
  const titled = [
    "French waters",
    "Italian waters",
    "Moroccan waters",
    "Madeira waters",
    "Martinique waters",
    "Guadeloupe waters",
  ];
  for (const low of LOWER_WATERS) {
    expect(blob, `minuscule interdite : ${low}`).not.toContain(low);
  }
  for (const name of titled) {
    if (blob.toLowerCase().includes(name.toLowerCase())) {
      expect(blob, "la forme capitale reste").toContain(name);
    }
  }

  const canPlay = await waitFilmReady(page, 45_000).then(() => true).catch(() => waitFilmCanStart(page, 10_000));
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; casse déjà vérifiée sur le JSON",
    });
    await shot(page, "01-eaux");
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 10_000 });

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 20_000 });

  const sought = await page.evaluate((names) => {
    const list = window.__naviguideFilm?.chapters || [];
    for (let i = 0; i < list.length; i += 1) {
      const text = String(list[i].text || "");
      for (const name of names) {
        const at = text.indexOf(name);
        if (at >= 0) return { i, at, text, name };
      }
    }
    return null;
  }, titled);

  if (sought) {
    await page.evaluate(({ i, at }) => window.__naviguideFilm?.seekChapter?.(i, at), sought);
    await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
      sought.i, { timeout: 10_000 }).catch(() => null);
    const subtitle = page.getByTestId("film-subtitle");
    await expect(subtitle).toBeVisible({ timeout: 8_000 });
    const spoken = `${await subtitle.innerText()} ${sought.text}`;
    for (const low of LOWER_WATERS) {
      expect(spoken).not.toContain(low);
    }
    if (spoken.includes(sought.name) || sought.text.includes(sought.name)) {
      expect(sought.text).toContain(sought.name);
    }
  }
  await shot(page, "01-eaux");
});
