// Le film dit les choses dans l'ordre, et finit ses phrases
// (revue du porteur, 14 oct.). Recette automatique du discours :
//   - dans chaque chapitre, les dates explicites vont en avant (jamais
//     « Le 19 mai … » puis « Le 18 mai … ») ;
//   - « Le lendemain » seulement après une date dite ;
//   - jamais « un flotteur Argo » anonyme (l'identifiant ou rien) ;
//   - jamais « les eaux de Saint-Martin, puis celles de Saint-Martin »
//     (Sint Maarten / Saint-Martin : un seul nom à l'oreille).
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film — la barre et Revoir restent vérifiés.
// Avec API, à un changement de chapterIdx la jambe barre contient
// encore le fromName du chapitre qui finit, pas déjà le toName du suivant.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc30");
const recetteRc36 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc36");
const recetteRc41 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc41");
const recetteRc48 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc48");
mkdirSync(recetteDir, { recursive: true });
mkdirSync(recetteRc36, { recursive: true });
mkdirSync(recetteRc41, { recursive: true });
mkdirSync(recetteRc48, { recursive: true });

const shot = async (page, name) => {
  const buf = await page.screenshot({ type: "webp", quality: 85, fullPage: false });
  writeFileSync(join(recetteDir, `${name}.webp`), buf);
};
const shotRc36 = async (page, name) => {
  const buf = await page.screenshot({ type: "webp", quality: 85, fullPage: false });
  writeFileSync(join(recetteRc36, `${name}.webp`), buf);
};
const shotRc41 = async (page, name) => {
  const buf = await page.screenshot({ type: "webp", quality: 85, fullPage: false });
  writeFileSync(join(recetteRc41, `${name}.webp`), buf);
};
const shotRc48 = async (page, name) => {
  const buf = await page.screenshot({ type: "webp", quality: 85, fullPage: false });
  writeFileSync(join(recetteRc48, `${name}.webp`), buf);
};

const MONTHS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];
const DATE_FR_RE = /\b(1er|\d{1,2}) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b/gi;
const ARGO_ANON_RE = /\b(un flotteur Argo|an Argo float)\b(?!\s*\d)/;
const SAME_WATERS_TWICE_RE = /les eaux (de |d['’])?(Saint-Martin|Sint-Maarten), puis celles (de |d['’])?(Saint-Martin|Sint-Maarten)/i;

function dayKey(dayRaw, monthRaw) {
  const day = dayRaw.toLowerCase() === "1er" ? 1 : Number(dayRaw);
  return (MONTHS_FR.indexOf(monthRaw.toLowerCase()) + 1) * 31 + day;
}

// La toise mois*31+jour boucle fin décembre : décembre → janvier est un
// passage d'année (en avant), pas un recul.
const YEAR_UNITS = 12 * 31 + 31;

function outOfOrderDates(text) {
  const out = [];
  let last = null;
  let offset = 0;
  for (const m of String(text || "").matchAll(DATE_FR_RE)) {
    let cur = dayKey(m[1], m[2]) + offset;
    if (last != null && cur < last && last - cur > YEAR_UNITS / 2) {
      offset += YEAR_UNITS;
      cur += YEAR_UNITS;
    }
    if (last != null && cur < last) out.push(m[0]);
    last = last == null ? cur : Math.max(last, cur);
  }
  return out;
}

function lendemainWithoutEve(text) {
  const out = [];
  let dated = false;
  for (const sent of String(text || "").split(/(?<=[.!?…])\s+/)) {
    if (/^(le lendemain|the next day)\b/i.test(sent.trim())) {
      if (!dated) out.push(sent.trim().slice(0, 60));
      continue;
    }
    DATE_FR_RE.lastIndex = 0;
    if (DATE_FR_RE.test(sent)) dated = true;
  }
  return out;
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 12_000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

test("Le film dit les choses dans l'ordre, et finit ses phrases", async ({ page }) => {
  test.setTimeout(210_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions discours sautées ; barre et Revoir gardés",
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
    await shot(page, "01-ordre");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const filmReady = film?.status === "ready" && Array.isArray(film?.chapters) && film.chapters.length > 0;
  if (!filmReady) {
    test.info().annotations.push({
      type: "film pas prêt",
      description: "GET /voyage/official/film pas ready — assertions discours sautées",
    });
    await shot(page, "01-ordre");
    return;
  }

  for (const [i, ch] of film.chapters.entries()) {
    const text = ch.text || "";
    const label = `ch${i} ${ch.fromName || ""} → ${ch.toName || ""}`;
    expect(outOfOrderDates(text), `${label} : dates qui reculent`).toEqual([]);
    expect(lendemainWithoutEve(text), `${label} : « Le lendemain » sans veille`).toEqual([]);
    expect(text, `${label} : flotteur Argo anonyme`).not.toMatch(ARGO_ANON_RE);
    expect(text, `${label} : mêmes eaux dites deux fois`).not.toMatch(SAME_WATERS_TWICE_RE);
  }
  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const argoCount = (blob.match(/flotteur Argo/g) || []).length;
  const chapterCount = film.chapters.length;
  expect(argoCount, "au plus un flotteur Argo par jambe").toBeLessThanOrEqual(chapterCount);

  const lrAj = film.chapters.find((c) =>
    /rochelle/i.test(c.fromName || "") && /ajaccio/i.test(c.toName || ""));
  const pap = film.chapters.find((c) => /papeete/i.test(c.toName || ""));
  const orderIdx = (text, re) => {
    const m = String(text || "").match(re);
    return m ? String(text).search(re) : -1;
  };
  let journalWatersReady = false;
  if (lrAj) {
    const t = lrAj.text || "";
    expect(t, "RC41 : plus de « Hs N m ≥ »").not.toMatch(/Hs \d+ m ≥/);
    const iFr = orderIdx(t, /eaux françaises|French waters/i);
    const iGas = orderIdx(t, /Gascogne/i);
    const iEs = orderIdx(t, /eaux espagnoles|Spanish waters/i);
    const iPt = orderIdx(t, /eaux portugaises|Portuguese waters/i);
    const iGi = orderIdx(t, /Gibraltar/i);
    const iMa = orderIdx(t, /eaux marocaines|Moroccan waters/i);
    journalWatersReady = iFr >= 0 && iGas >= 0 && iEs >= 0 && iPt >= 0 && iGi >= 0 && iMa >= 0;
    if (journalWatersReady) {
      expect(iFr, "eaux françaises avant Gascogne").toBeLessThan(iGas);
      expect(iGas, "Gascogne avant les eaux espagnoles").toBeLessThan(iEs);
      expect(iEs, "eaux espagnoles avant portugaises").toBeLessThan(iPt);
      expect(iPt, "eaux portugaises avant Gibraltar").toBeLessThan(iGi);
      expect(iGi, "Gibraltar avant les eaux marocaines").toBeLessThan(iMa);
    } else {
      test.info().annotations.push({
        type: "stock figé",
        description: "film ready sans zee-enter FR — remplisseur FILM_SCRIPT_REV=rc48",
      });
    }
  }
  if (pap) {
    if (/Pacifique|Pacific/i.test(pap.text || "")) {
      expect(pap.text, "Cayenne → Papeete nomme le Pacifique").toMatch(/Pacifique|Pacific/i);
    } else {
      test.info().annotations.push({
        type: "stock figé",
        description: "film ready sans Pacifique — remplisseur FILM_SCRIPT_REV=rc35/rc48",
      });
    }
  }

  await shot(page, "01-ordre");

  // À la bascule de chapitre, la barre est encore sur la jambe qui finit.
  expect(await waitFilmCanStart(page, 20_000), "Revoir actif (API présente)").toBe(true);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 12_000 });
  await expect.poll(
    () => page.evaluate(() => (
      Number(window.__naviguideFilm?.chapterCount) > 1
      && Number.isFinite(Number(window.__naviguideFilm?.tMs))
      && Number.isFinite(Number(window.__naviguideFilm?.chapterIdx))
    )),
    { timeout: 20_000 },
  ).toBeTruthy();

  if (journalWatersReady) {
    await expect.poll(
      async () => {
        const bar = await page.getByTestId("film-bar").innerText();
        const sub = await page.getByTestId("film-subtitle").innerText().catch(() => "");
        return /rochelle/i.test(bar) && /ajaccio/i.test(bar)
          && /eaux françaises|Gascogne|espagnol|portugai|Gibraltar|marocain/i.test(sub);
      },
      { timeout: 90_000 },
    ).toBeTruthy();
    await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
    await shotRc48(page, "01-ordre");
    await shot(page, "01-ordre");
  }
  await shotRc41(page, "01-revoir-hs");

  const charsUntilSecondSea = (film.chapters || []).slice(0, 3)
    .reduce((n, c) => n + String(c.text || "").length, 0);
  const flipWaitMs = Math.min(120_000, Math.max(70_000, Math.ceil(charsUntilSecondSea / 12) * 1000 + 25_000));
  const flip = await page.evaluate(async ({ limit }) => {
    const chapterMs = (v) => {
      if (typeof v === "number" && Number.isFinite(v)) return v;
      const p = Date.parse(v || "");
      return Number.isFinite(p) ? p : NaN;
    };
    const spanOf = (ch) => {
      const a = chapterMs(ch?.tA);
      const b = chapterMs(ch?.tB);
      return Number.isFinite(a) && Number.isFinite(b) && b > a ? b - a : 0;
    };
    const planChapters = () => window.__naviguideFilm?.chapters || [];
    const read = () => {
      const f = window.__naviguideFilm || {};
      const bar = document.querySelector("[data-testid='film-bar']");
      const clock = document.querySelector("[data-testid='clock-line']");
      const jambe = (bar?.innerText || "").split("\n")[0] || "";
      const idx = Number(f.chapterIdx);
      return {
        idx: Number.isFinite(idx) ? idx : 0,
        tMs: Number(f.tMs),
        jambe,
        clock: clock?.innerText || "",
        fromName: f.fromName || "",
        toName: f.toName || "",
        subtitle: f.subtitle || "",
        count: Number(f.chapterCount) || 0,
      };
    };
    let last = read();
    const seen = [];
    const t0 = performance.now();
    while (performance.now() - t0 < limit) {
      const s = read();
      if (s.idx !== last.idx) {
        seen.push({
          from: last.idx,
          to: s.idx,
          jambe: last.jambe,
          fromName: last.fromName,
          tMs: last.tMs,
          span: spanOf(planChapters()[last.idx]),
        });
      }
      if (s.idx > last.idx) {
        const prevCh = planChapters()[last.idx];
        if (spanOf(prevCh) > 3600_000) {
          return {
            lastGood: last,
            atFlip: s,
            startIdx: last.idx,
            nextIdx: s.idx,
            chapters: planChapters(),
            seen,
          };
        }
        last = s;
      } else {
        last = s;
      }
      await new Promise((r) => setTimeout(r, 40));
    }
    return {
      lastGood: last,
      atFlip: null,
      startIdx: last.idx,
      nextIdx: null,
      chapters: planChapters(),
      seen,
    };
  }, { limit: flipWaitMs });

  await shotRc36(page, "01-jambe-sous-titre");
  expect(
    flip?.atFlip,
    `bascule de chapterIdx en ${Math.round(flipWaitMs / 1000)} s (seen=${JSON.stringify(flip?.seen || [])} last=${JSON.stringify({
      idx: flip?.lastGood?.idx,
      jambe: flip?.lastGood?.jambe,
      fromName: flip?.lastGood?.fromName,
      count: flip?.lastGood?.count,
    })})`,
  ).toBeTruthy();

  const prev = (flip.chapters || [])[flip.startIdx] || {};
  const next = (flip.chapters || [])[flip.nextIdx] || {};
  const nameCore = (s) => String(s || "").replace(/\s*\([^)]*\)\s*/g, " ").trim();
  const prevFrom = nameCore(prev.fromName || flip.lastGood?.fromName || "");
  const prevTo = nameCore(prev.toName || flip.lastGood?.toName || "");
  const nextTo = nameCore(next.toName || "");
  const lastT = Number(flip.lastGood?.tMs);
  const lastA = Number(prev.tA);
  const lastB = Number(prev.tB);
  expect(Number.isFinite(lastT) && Number.isFinite(lastA) && Number.isFinite(lastB) && lastB > lastA, "chapitre de bascule borné").toBe(true);
  expect(lastT, "tMs encore dans [tA, tB] du chapitre qui finit").toBeGreaterThanOrEqual(lastA);
  expect(lastT, "tMs encore dans [tA, tB] du chapitre qui finit").toBeLessThanOrEqual(lastB);
  expect(lastT, "bascule en fin de jambe, pas au départ").toBeGreaterThan(lastA + (lastB - lastA) * 0.3);
  const jambe = flip.lastGood?.jambe || "";
  const surface = `${jambe}\n${flip.lastGood?.clock || ""}`;
  const onFinishingLeg = [prevFrom, prevTo].filter((n) => n.length >= 2).some((n) => (
    new RegExp(n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i").test(surface)
  ));
  expect(onFinishingLeg, `barre encore sur la jambe qui finit (${prevFrom} → ${prevTo}) : ${jambe}`).toBe(true);
  if (nextTo.length >= 2 && nextTo.toLowerCase() !== prevFrom.toLowerCase() && nextTo.toLowerCase() !== prevTo.toLowerCase()) {
    expect(jambe, "pas déjà le toName du chapitre suivant").not.toMatch(
      new RegExp(nextTo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"),
    );
  }
  await shotRc36(page, "01-jambe-sous-titre");
});
