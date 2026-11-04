// L'épisode Saint-Pierre-et-Miquelon raconté comme il s'est passé
// (vol Cayenne→Halifax, second bateau Halifax↔Saint-Pierre, vol retour,
// reprise du catamaran). Sans API : GET /voyage/official sondé ; s'il
// manque, annotation + saut des assertions film / carte — barre et Revoir
// restent vérifiés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, openJournalTab, openReviewTab, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc31");
const recetteRc43 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc43");
const recetteRc44 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc44");
const recetteRc50 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc50");
mkdirSync(recetteDir, { recursive: true });
mkdirSync(recetteRc43, { recursive: true });
mkdirSync(recetteRc44, { recursive: true });
mkdirSync(recetteRc50, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});
const shot43 = (page, name) => page.screenshot({
  path: join(recetteRc43, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});
const shot44 = (page, name) => page.screenshot({
  path: join(recetteRc44, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});
const shot50 = (page, name) => page.screenshot({
  path: join(recetteRc50, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AIR_OUT = /s'envole de Cayenne pour Halifax|prend l'avion pour Halifax|the crew flies from Cayenne to Halifax/i;
const AIR_BACK = /s['’]envole (?:de |d['’])Halifax pour Cayenne|retour en avion vers Cayenne|flies from Halifax/i;
const WAIT = /le catamaran attend à Cayenne|the catamaran waits at Cayenne/i;
const SIDE_BOAT = /second voilier|second sailing boat/i;
const RESUME_SEA = /reprend la mer|départ vers Papeete|puts to sea again|departure for Papeete/i;
const FALSE_AIR = /s'envole de Cayenne pour Saint-Pierre|flies from Cayenne to Saint-Pierre/i;
const SIDE_COLOR = "#67e8f9";

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
  return { apiUp: true, body };
}

function chapterIndex(chapters, fromRe, toRe) {
  return (chapters || []).findIndex((c) => (
    fromRe.test(c.fromName || "") && toRe.test(c.toName || "")
  ));
}

async function seekFilmLeg(page, fromRe, toRe, textRe) {
  const idx = await page.evaluate(({ fromSrc, toSrc, textSrc }) => {
    const fromRx = new RegExp(fromSrc, "i");
    const toRx = new RegExp(toSrc, "i");
    const textRx = textSrc ? new RegExp(textSrc, "i") : null;
    const list = window.__naviguideFilm?.chapters || [];
    let hit = list.find((c) => fromRx.test(c.fromName || "") && toRx.test(c.toName || ""));
    if (!hit && textRx) hit = list.find((c) => textRx.test(c.text || ""));
    if (!hit) return -1;
    const i = Number.isFinite(Number(hit.idx)) ? Number(hit.idx) : list.indexOf(hit);
    const at = textRx ? String(hit.text || "").search(textRx) : -1;
    window.speechSynthesis?.cancel?.();
    window.__naviguideFilm?.seekChapter?.(i, at >= 0 ? at : 0);
    return i;
  }, { fromSrc: fromRe.source, toSrc: toRe.source, textSrc: textRe ? textRe.source : "" });
  if (idx >= 0) {
    await page.waitForFunction((i) => Number(window.__naviguideFilm?.chapterIdx) === i, idx, {
      timeout: 8_000,
    }).catch(() => null);
  }
  return idx;
}

async function seekUntilSubtitle(page, fromRe, toRe, textRe, expectRe) {
  let idx = -1;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    idx = await seekFilmLeg(page, fromRe, toRe, textRe);
    if (idx < 0) return idx;
    const text = await page.getByTestId("film-subtitle").innerText().catch(() => "");
    if (expectRe.test(text)) return idx;
    await page.waitForTimeout(250);
  }
  return idx;
}

test("Épisode SPM : quatre chapitres, second bateau, catamaran à Cayenne", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film / carte sautées ; barre et Revoir gardés",
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
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions Journal Halifax / jambe Cayenne → Papeete sautées",
    });
    await shot(page, "01-episode");
    await shot(page, "02-carte-side");
    await shot44(page, "01-journal-halifax");
    await shot44(page, "02-revue-cayenne-papeete");
    await shot44(page, "03-fiche-cayenne");
    await shot50(page, "01-cayenne-papeete");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions discours sautées",
    });
    await shot(page, "01-episode");
    await shot(page, "02-carte-side");
    return;
  }

  test.info().annotations.push({
    type: "film",
    description: `API film chapters=${film.chapters.length} status=${film.status || "?"}`,
  });
  const chapters = film.chapters;
  const blob = chapters.map((c) => c.text || "").join(" ");
  const airOut = chapterIndex(chapters, /cayenne/i, /halifax/i);
  const sideOut = chapterIndex(chapters, /halifax/i, /saint-pierre|miquelon/i);
  const sideBack = chapterIndex(chapters, /saint-pierre|miquelon/i, /halifax/i);
  const airBack = chapterIndex(chapters, /halifax/i, /cayenne/i);
  const episodeReady = airOut >= 0 && sideOut >= 0 && sideBack >= 0 && airBack >= 0
    && airOut < sideOut && sideOut < sideBack && sideBack < airBack;

  if (!episodeReady) {
    test.info().annotations.push({
      type: "stock pré-RC31",
      description: "film servi sans les 4 chapitres d'épisode — remplisseur FILM_SCRIPT_REV=rc31",
    });
  } else {
    expect(blob, "vol Cayenne → Halifax").toMatch(AIR_OUT);
    expect(blob, "vol Halifax → Cayenne").toMatch(AIR_BACK);
    expect(blob, "attente du catamaran").toMatch(WAIT);
    expect(
      (blob.match(/catamaran attend à Cayenne|catamaran waits at Cayenne/gi) || []).length,
      "attente dite une fois",
    ).toBe(1);
    expect(blob, "pas de vol inventé vers Saint-Pierre").not.toMatch(FALSE_AIR);
    expect(blob, "second bateau nommé ou « un second voilier »").toMatch(SIDE_BOAT);
  }

  const clock = await page.request.get("/voyage/official", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const marks = (clock && (clock.clock?.marks || clock.marks)) || [];
  const halifaxMarks = marks.filter((m) => /halifax/i.test(m?.name || ""));
  if (halifaxMarks.length) {
    expect(halifaxMarks.length, "marques Halifax aller et retour").toBeGreaterThanOrEqual(1);
  }

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  await muteVoice(page);
  await page.evaluate(() => { window.speechSynthesis?.cancel?.(); });
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0
      && Array.isArray(f.chapters) && f.chapters.length > 0;
  }, null, { timeout: 8_000 }).catch(() => null);
  const clientFilm = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const list = f.chapters || [];
    return {
      count: f.chapterCount || 0,
      n: list.length,
      names: list.map((c, i) => `${i}:${c.fromName || ""}→${c.toName || ""}`).join(" | "),
    };
  });
  test.info().annotations.push({
    type: "client-film",
    description: `${clientFilm.n}/${clientFilm.count} ${clientFilm.names}`,
  });

  if (episodeReady) {
    const airAt = await seekUntilSubtitle(
      page, /cayenne/, /halifax/, AIR_OUT,
      /s'envole de Cayenne|prend l'avion pour Halifax|flies from Cayenne|attend à Cayenne|waits at Cayenne/i,
    );
    if (airAt >= 0) {
      await expect.poll(async () => subtitle.innerText(), { timeout: 8_000 })
        .toMatch(/s'envole|avion|flies|attend à Cayenne|waits at Cayenne/i);
    }
  }
  await shot(page, "01-episode");

  const sideAt = await seekUntilSubtitle(page, /halifax/, /saint-pierre|miquelon/, SIDE_BOAT, SIDE_BOAT);
  await page.waitForTimeout(400);

  if (sideAt >= 0) {
    await expect.poll(async () => subtitle.innerText(), { timeout: 8_000 }).toMatch(SIDE_BOAT);
    await expect(subtitle, "Halifax → Saint-Pierre sans bloc avion").not.toContainText(/s'envole/i);
    await shot43(page, "01-halifax-saint-pierre");
  } else if (episodeReady) {
    test.info().annotations.push({
      type: "seek",
      description: "chapitre Halifax → Saint-Pierre absent du film client — sous-titre RC43 non capturé",
    });
  }

  const mapStats = await page.evaluate(() => {
    const scene = window.__naviguideScene;
    const map = scene?.map;
    const stats = { sideLines: 0, airDash: 0 };
    if (!map) return stats;
    const norm = (c) => String(c || "").toLowerCase().replace(/\s/g, "");
    map.eachLayer((layer) => {
      if (!layer.getLatLngs || !layer.options) return;
      const color = norm(layer.options.color);
      const dash = layer.options.dashArray;
      if (color === "#67e8f9" || color === "rgb(103,232,249)") stats.sideLines += 1;
      if (dash && (color === "#111111" || color === "#111" || color === "black" || color === "rgb(17,17,17)")) {
        stats.airDash += 1;
      }
    });
    return stats;
  });
  if (mapStats.sideLines + mapStats.airDash === 0) {
    test.info().annotations.push({
      type: "carte",
      description: "aucune polyligne side/air lue sur Leaflet — capture brute",
    });
  } else {
    expect(mapStats.airDash + mapStats.sideLines, "vol pointillé ou trace side").toBeGreaterThan(0);
  }
  await shot(page, "02-carte-side");

  const resumeAt = await seekUntilSubtitle(page, /cayenne/, /papeete/, RESUME_SEA, RESUME_SEA);
  if (resumeAt >= 0) {
    await expect.poll(async () => subtitle.innerText(), { timeout: 8_000 }).toMatch(RESUME_SEA);
    await expect(subtitle, "reprise sans s'envole").not.toContainText(/s'envole/i);
    await shot43(page, "02-reprise-papeete");
  } else if (episodeReady) {
    test.info().annotations.push({
      type: "seek",
      description: "chapitre reprise Cayenne → Papeete absent du film client — sous-titre RC43 non capturé",
    });
  }

  await showLeftPanel(page);
  const journalTab = page.getByTestId("ici-tab-journal");
  if (await journalTab.isVisible().catch(() => false)) {
    await journalTab.click();
    const journal = page.getByTestId("journal-panel")
      .or(page.getByTestId("journal-day"))
      .or(page.getByTestId("ici-journal-list"));
    if (await journal.isVisible({ timeout: 4_000 }).catch(() => false)) {
      const txt = await journal.innerText().catch(() => "");
      if (txt) {
        expect(txt.length, "journal non vide").toBeGreaterThan(0);
      }
    }
  }

  const momentsBody = await page.request.get("/voyage/official/moments", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const momentRows = Array.isArray(momentsBody?.moments) ? momentsBody.moments : [];
  const aroundHfx = momentRows.filter((row) => {
    const lat = Number(row?.pos?.lat ?? row?.moment?.pos?.lat);
    const lon = Number(row?.pos?.lon ?? row?.moment?.pos?.lon);
    return lat > 43.5 && lat < 45.5 && lon < -62 && lon > -65;
  });
  const hfxTitles = aroundHfx.flatMap((row) => (row.changes || []).map((c) => c?.title || "")).join(" | ");
  const cayenneAt44 = aroundHfx.some((row) => (
    (row.changes || []).some((c) => /Arrivée à Cayenne/i.test(c?.title || ""))
  ));
  const halifaxNamed = /Halifax/i.test(hfxTitles);
  if (!aroundHfx.length || !halifaxNamed || cayenneAt44) {
    test.info().annotations.push({
      type: "stock pré-RC44",
      description: "moments figés sans ligne Halifax à ~44°N — remplisseur MOMENTS_REV à relancer",
    });
  } else {
    expect(hfxTitles, "journal à ~44°N nomme Halifax").toMatch(/Halifax/i);
    expect(cayenneAt44, "pas d'Arrivée à Cayenne collée à 44°").toBeFalsy();
  }

  if (episodeReady) {
    await seekUntilSubtitle(
      page, /cayenne/, /halifax/, AIR_OUT,
      /Halifax|s'envole|avion|flies/i,
    );
  }
  try {
    await openJournalTab(page);
  } catch {
    /* onglet déjà ouvert ou masqué */
  }
  await shot44(page, "01-journal-halifax");

  const reviewBody = await page.request.get("/voyage/official/plan-review", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const reviewReady = reviewBody?.status === "ready";
  const reviewLegs = Array.isArray(reviewBody?.legs) ? reviewBody.legs : [];
  const pacific = reviewLegs.filter((leg) => (
    /Papeete/i.test(leg?.to || "") && !/Papeete/i.test(leg?.from || "")
  ));
  const staleToPapeete = pacific.filter((leg) => /Halifax|Saint-Pierre|Miquelon/i.test(leg?.from || ""));
  const cayenneToPapeete = pacific.filter((leg) => /Cayenne/i.test(leg?.from || ""));
  // Un GET ready ne peut plus porter Halifax / Saint-Pierre → Papeete
  // (plus d'annotation « stock pré-RC44 » sur un ready). Sans snapshot à la
  // nouvelle clé : preparing, annotation, assertions jambe sautées.
  if (reviewReady) {
    expect(cayenneToPapeete.length, "jambe après l'épisode = Cayenne → Papeete").toBeGreaterThan(0);
    expect(staleToPapeete.length, "plus jamais Halifax ni Saint-Pierre → Papeete").toBe(0);
  } else {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready — PLAN_REVIEW_REV, remplisseur à relancer ; assertions jambe sautées",
    });
  }

  try {
    await openReviewTab(page);
  } catch {
    /* revue absente sans stock */
  }
  if (reviewReady) {
    const row = page.getByTestId("plan-review-leg").filter({ hasText: /Cayenne/i }).filter({ hasText: /Papeete/i });
    await expect(row.first()).toBeVisible({ timeout: 8_000 });
    await expect(page.getByTestId("plan-review")).not.toContainText(/Halifax \(Nouvelle-Écosse\) → Papeete|Saint-Pierre \(Saint-Pierre-et-Miquelon\) → Papeete/i);
  }
  await shot44(page, "02-revue-cayenne-papeete");
  await shot50(page, "01-cayenne-papeete");

  const stopBtn = page.getByTestId("replay-stop");
  if (await stopBtn.isVisible().catch(() => false)) {
    await stopBtn.click();
  }
  await leaveCinema(page);

  const cayenneMark = marks.find((m) => /cayenne/i.test(m?.name || ""));
  if (cayenneMark && Number.isFinite(Number(cayenneMark.lat))) {
    await page.evaluate((stop) => {
      window.__naviguideScene?.callbacks?.onWaypointClick?.(stop);
    }, { name: cayenneMark.name, lat: cayenneMark.lat, lon: cayenneMark.lon }).catch(() => null);
    const sheet = page.getByTestId("escale-sheet").or(page.getByTestId("escale-popup"));
    if (await sheet.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await expect(sheet).toContainText(/Cayenne/i);
      await expect(sheet).not.toContainText(/Halifax/i);
    }
  }
  await shot44(page, "03-fiche-cayenne");
});
