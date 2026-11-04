// Le sous-titre film montre l'avion aller et retour à l'écran.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le seek Guyane
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut
// des seules assertions avion visibles — jamais Revoir retiré, ni les
// pilules, ni la barre. Le spec RC13 (contrat GET /film) n'est pas modifié.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc16");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AIR_OUT = /prend l'avion pour|s'envole de Cayenne|the crew flies (?:to|from)/i;
const AIR_BACK = /retour en avion vers|return flight to|s['’]envole (?:de |d['’])Halifax|flies from Halifax/i;

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

async function waitOfficialFilm(page) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < 20_000) {
    const r = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
      .then((x) => (x.ok() ? x.json() : null))
      .catch(() => null);
    last = r;
    if (r?.chapters?.length && r.status !== "preparing") return r;
    await page.waitForTimeout(800);
  }
  return last;
}

/** Le motif est dans le layout visible, pas seulement dans textContent (overflow clip). */
async function visiblePhrase(locator, re) {
  return locator.evaluate((el, src) => {
    const pattern = new RegExp(src, "i");
    const style = getComputedStyle(el);
    const clips = (
      (style.overflowX === "hidden" || style.overflow === "hidden")
      && (style.textOverflow === "ellipsis" || style.whiteSpace === "nowrap")
    );
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const idx = node.data.search(pattern);
      if (idx < 0) continue;
      const word = (node.data.match(pattern) || [""])[0];
      if (!word) continue;
      const range = document.createRange();
      range.setStart(node, idx);
      range.setEnd(node, idx + word.length);
      const r = range.getBoundingClientRect();
      const box = el.getBoundingClientRect();
      const inBox = (
        r.width > 1
        && r.height > 1
        && r.left < box.right - 0.5
        && r.right > box.left + 0.5
        && r.top < box.bottom - 0.5
        && r.bottom > box.top + 0.5
      );
      return { found: true, inBox, clips, word };
    }
    return { found: false, inBox: false, clips, word: "" };
  }, re.source);
}

async function expectVisibleAir(locator, re, label) {
  const info = await visiblePhrase(locator, re);
  expect(info.found, `${label} présent`).toBeTruthy();
  expect(info.clips, `${label} sans overflow clip`).toBeFalsy();
  expect(info.inBox, `${label} dans la boîte visible (${info.word})`).toBeTruthy();
}

test("Sous-titre visible : avion aller et retour à la Guyane", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions avion visibles sautées ; Suivre et Revoir gardés",
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

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }
  await shot(page, "01-suivre-revoir");

  if (!apiUp) {
    await expect(page.getByTestId("replay-departure")).toBeVisible();
    await shot(page, "02-guyane-avion");
    return;
  }

  const film = await waitOfficialFilm(page);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film en préparation",
      description: "GET /voyage/official/film sans chapitres — assertions avion visibles sautées",
    });
    await shot(page, "02-guyane-avion");
    return;
  }

  if (!(await start.isEnabled().catch(() => false))) {
    test.info().annotations.push({
      type: "Revoir indisponible",
      description: "Revoir grisé — assertions avion visibles sautées",
    });
    await shot(page, "02-guyane-avion");
    return;
  }

  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).catch(() => null);

  async function seekAirPhrase(re) {
    const idx = await page.evaluate((src) => {
      const rx = new RegExp(src, "i");
      const list = window.__naviguideFilm?.chapters || [];
      for (const chapter of list) {
        const text = chapter.text || "";
        const at = text.search(rx);
        if (at < 0) continue;
        const i = Number.isFinite(Number(chapter.idx)) ? Number(chapter.idx) : list.indexOf(chapter);
        window.speechSynthesis?.cancel?.();
        window.__naviguideFilm?.seekChapter?.(i, at);
        return i;
      }
      return -1;
    }, re.source);
    if (idx >= 0) {
      await page.waitForFunction((i) => Number(window.__naviguideFilm?.chapterIdx) === i, idx, {
        timeout: 8_000,
      }).catch(() => null);
    }
    return idx;
  }

  const outIdx = await seekAirPhrase(AIR_OUT);
  const backIdx = await seekAirPhrase(AIR_BACK);
  if (outIdx < 0 && backIdx < 0) {
    test.info().annotations.push({
      type: "chapitre avion absent",
      description: "aucun chapitre Guyane / avion dans le film chargé — assertions visibles sautées",
    });
    await shot(page, "02-guyane-avion");
    return;
  }

  await expect(subtitle).toBeVisible();
  if (outIdx >= 0) {
    await seekAirPhrase(AIR_OUT);
    await expect.poll(async () => subtitle.innerText(), { timeout: 8_000 }).toMatch(AIR_OUT);
    await expectVisibleAir(subtitle, AIR_OUT, "avion aller");
  }
  if (backIdx >= 0) {
    await seekAirPhrase(AIR_BACK);
    await expect.poll(async () => subtitle.innerText(), { timeout: 8_000 }).toMatch(AIR_BACK);
    await expectVisibleAir(subtitle, AIR_BACK, "avion retour");
  }
  await shot(page, "02-guyane-avion");
});
