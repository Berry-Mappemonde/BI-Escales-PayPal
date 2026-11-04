// Parcours « Try it in 60 seconds » du README, sur le build local.
// L'URL de production n'est jamais ouverte (passage manuel seulement).
// GET /voyage/official est sondé. S'il ne répond pas, les assertions qui
// en dépendent sont annotées puis sautées. Celles qui n'en dépendent pas restent.
import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  bringOffscreenFlagsIntoView,
  dismissNotForNav,
  enterTracer,
  openJournalTab,
  openReviewTab,
  openStoryTab,
  panelClosed,
  showLeftPanel,
  showRightPanel,
} from "../helpers.js";

test.use({ storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "parallel" });

mkdirSync("../docs/recette/jg1", { recursive: true });

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/jg1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AI_NOTICE = "You are interacting with artificial intelligence. Replies are generated automatically and may contain errors.";
const TECHNICAL = /HTTPStatusError|Traceback|no_sample_at_point|[A-Za-z]+_unavailable|Exception:/;
const LA_ROCHELLE = { lat: 46.157, lon: -1.151, name: "La Rochelle" };
const GIJON = { lat: 43.545, lon: -5.662, name: "Gijon" };
const LISBON = { lat: 38.722, lon: -9.139, name: "Lisbonne" };
const PARIS = { lat: 48.8566, lon: 2.3522 };

function clockSeconds(text) {
  const m = String(text || "").match(/(\d+):(\d{2})/);
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

function samePlace(shown, full) {
  const a = String(shown || "").trim().toLowerCase();
  const b = String(full || "").trim().toLowerCase();
  if (!a || !b) return false;
  const head = b.split("(")[0].trim();
  return b.includes(a) || a.includes(head);
}

function legAt(clock, now = Date.now()) {
  const marks = clock?.clock?.marks || clock?.marks;
  const list = (Array.isArray(marks) ? marks : [])
    .filter((m) => m && m.name && m.iso)
    .map((m) => ({ name: m.name, t: Date.parse(m.iso), hold: Number(m.holdHours) || 0 }))
    .filter((m) => Number.isFinite(m.t))
    .sort((a, b) => a.t - b.t);
  if (list.length < 2) return null;
  let i = 0;
  for (let k = 0; k < list.length; k += 1) if (list[k].t <= now) i = k;
  const here = list[Math.min(i, list.length - 1)];
  const next = list[Math.min(i + 1, list.length - 1)];
  const atStop = now >= here.t && now < here.t + here.hold * 3600000;
  return { from: here.name, to: next.name, atStop };
}

async function probeApi(page) {
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(
    official && official.ok() && String(official.headers()["content-type"] || "").includes("json"),
  );
  return apiUp;
}

async function readWarm(page) {
  return page.request.get("/ici/warm/status", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
}

function assertWarmShape(warm) {
  expect(warm && typeof warm === "object").toBeTruthy();
  expect(warm.llm && typeof warm.llm === "object").toBeTruthy();
  expect(Number.isFinite(Number(warm.llm.tavily?.calls))).toBeTruthy();
  const fallback = warm.llm.fallback;
  if (fallback && typeof fallback === "object") {
    const n = Object.values(fallback).reduce((sum, v) => sum + (Number(v) || 0), 0);
    expect(n, "replis du jour").toBe(0);
  }
  const byTier = warm.llm.lastSourceByTier;
  if (byTier && typeof byTier === "object") {
    for (const value of Object.values(byTier)) {
      expect(String(value)).toMatch(/nemotron/i);
    }
  }
}

async function assertLocal(page) {
  expect(page.url(), "build local").toMatch(/^http:\/\/127\.0\.0\.1:/);
  expect(page.url()).not.toContain("naviguide.fr");
}

async function assertAiMarks(page) {
  const marks = await page.locator("[data-ai-generated]").evaluateAll((els) => els.map((el) => ({
    value: el.getAttribute("data-ai-generated"),
    source: el.getAttribute("data-llm-source"),
    text: (el.textContent || "").replace(/\s+/g, " ").trim(),
  })));
  for (const mark of marks) {
    expect(mark.value).toMatch(/^(true|false)$/);
    expect(mark.source).not.toBeNull();
    if (mark.value === "true") expect(mark.text).toMatch(/AI-generated content \(model:/);
  }
  return marks;
}

async function expectOfficialExports(page, geoBtn, kmlBtn) {
  await expect(kmlBtn).toHaveAttribute("title", "KML of the followed route");
  const fs = await import("node:fs");
  const [geoDl] = await Promise.all([
    page.waitForEvent("download"),
    geoBtn.click(),
  ]);
  const geo = JSON.parse(fs.readFileSync(await geoDl.path(), "utf8"));
  expect(geo.type).toBe("FeatureCollection");
  expect(Array.isArray(geo.features) && geo.features.length > 0).toBeTruthy();
  const [kmlDl] = await Promise.all([
    page.waitForEvent("download"),
    kmlBtn.click(),
  ]);
  const kml = fs.readFileSync(await kmlDl.path(), "utf8");
  expect(kml).toMatch(/<kml/i);
  expect(kml).toMatch(/<LineString>|<Point>/);
}

async function routeGet(page, from, to) {
  const q = new URLSearchParams({
    start_lat: String(from.lat),
    start_lon: String(from.lon),
    end_lat: String(to.lat),
    end_lon: String(to.lon),
  });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const res = await page.request.get(`/route?${q}`, { timeout: 20_000 }).catch(() => null);
    if (res && res.status() === 503 && attempt === 0) {
      await page.waitForTimeout(5000);
      continue;
    }
    return res;
  }
  return null;
}

test("parcours 60 secondes : suivre, revoir, journal, tracer, mention IA", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  const apiUp = await probeApi(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — /ici/warm/status, étape du jour et fiche d'escale non exigés",
    });
  }
  const warmBefore = apiUp ? await readWarm(page) : null;

  await page.goto("/");
  await assertLocal(page);
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const follow = page.getByTestId("view-suivre");
  if ((await follow.innerText()).trim() !== "Follow expedition") {
    await showRightPanel(page);
    await page.getByTestId("lang-en").click();
  }
  await expect(follow).toHaveText("Follow expedition");
  await follow.click();
  await expect(follow).toHaveAttribute("aria-checked", "true");
  await shot(page, "01-suivre");

  const start = page.getByTestId("replay-start");
  await expect(start).toContainText("Replay the expedition", { timeout: 20_000 });
  if (await start.isDisabled()) await expect(start).toHaveAttribute("title", "preparing");
  await expect(page.getByTestId("film-style-raw")).toHaveText("Raw");
  const edited = page.getByTestId("film-style-written");
  await expect(edited).toHaveText("Edited");
  if (await edited.isDisabled()) {
    await expect(edited).toHaveAttribute("title", "not yet written for this duration");
  }
  await shot(page, "03-revoir");

  await showLeftPanel(page);
  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 15_000 });
  await expect(chat).toContainText("Logbook — ask a question");
  const input = page.getByTestId("logbook-chat-input");
  await expect(input).toHaveAttribute("placeholder", "Wind at the boat? Next stop?");
  await expect(page.getByTestId("logbook-chat-send")).toHaveAttribute("title", "Send");
  await input.focus();
  const notice = page.getByTestId("logbook-chat-ai-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(AI_NOTICE);
  const size = await notice.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size).toBeGreaterThanOrEqual(12);
  await dismissNotForNav(page);
  await expect(notice).toBeVisible();
  // Seule la question d'exemple « web » nomme Tavily (elle l'annonce, le serveur l'appelle).
  // Les boutons du tiroir gauche restent visibility: hidden pendant son glissement
  // (index.css, .naviguide-drawer-settled) : on attend la liste exacte, sans l'affaiblir.
  const tavilyButtons = page.getByRole("button", { name: /tavily/i });
  await expect.poll(
    () => tavilyButtons.evaluateAll((els) => els.map((el) => el.getAttribute("data-testid"))),
    { timeout: 10_000 },
  ).toEqual(["logbook-chat-example-web"]);
  await shot(page, "02-journal");

  const sheet = page.getByTestId("escale-sheet");
  if (await sheet.isVisible().catch(() => false)) {
    await expect(sheet).toContainText("Port of call sheet");
    const watch = sheet.getByText(/watch of/i);
    if (await watch.count()) await expect(watch.first()).toContainText(/\d/);
  }

  const draw = page.getByRole("button", { name: /Draw your own route/ }).first();
  await expect(draw).toBeVisible();
  await enterTracer(page);
  await expect(page.getByTestId("draw-point-limit")).toContainText("60 points maximum");
  await shot(page, "04-tracer");

  const marks = await assertAiMarks(page);
  if (!marks.some((m) => m.value === "true")) {
    test.info().annotations.push({
      type: "sans texte LLM",
      description: "aucun data-ai-generated=true à l'écran — pas de bloc rédigé servi",
    });
  }

  if (apiUp) {
    if (warmBefore) assertWarmShape(warmBefore);
    else {
      test.info().annotations.push({
        type: "sans API",
        description: "GET /ici/warm/status avant le parcours sans JSON",
      });
    }
    const warmAfter = await readWarm(page);
    if (warmAfter) assertWarmShape(warmAfter);
    else {
      test.info().annotations.push({
        type: "sans API",
        description: "GET /ici/warm/status après le parcours sans JSON",
      });
    }
  }

  expect(errors, errors.join("\n")).toEqual([]);
});

test("non-régression suivre, film, revue, polaire, exports, fiche", async ({ page }) => {
  test.setTimeout(150_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  const apiUp = await probeApi(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — C-01, C-04 à C-06, C-12 à C-17, H-02, H-09, I-06, I-09, I-10, I-13, I-15, I-16 sautés",
    });
  }

  await page.goto("/");
  await assertLocal(page);
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await showRightPanel(page);
  await expect(page.getByTestId("polar-box")).toBeVisible();
  const geoBtn = page.getByTestId("export-geojson");
  const kmlBtn = page.getByTestId("export-kml");
  await expect(geoBtn).toBeVisible();
  await expect(kmlBtn).toBeVisible();

  if (!apiUp) {
    if (await geoBtn.isEnabled()) await expectOfficialExports(page, geoBtn, kmlBtn);
    else await expect(kmlBtn).toHaveAttribute("title", "No route to export");
    expect(errors, errors.join("\n")).toEqual([]);
    return;
  }

  await test.step("NAV-C-01 étape du jour, aucun message technique", async () => {
    const clock = await page.request.get("/voyage/official/clock", { timeout: 20_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    const leg = page.getByTestId("film-leg");
    await expect.poll(async () => (await leg.getAttribute("data-from")) || "", { timeout: 25_000 }).not.toEqual("");
    const from = await leg.getAttribute("data-from");
    const to = await leg.getAttribute("data-to");
    const bracket = legAt(clock);
    if (!bracket) {
      test.info().annotations.push({
        type: "horloge",
        description: "horloge sans deux marques — l'étape affichée reste exigée, le nom du jour non comparé",
      });
    } else {
      expect(samePlace(from, bracket.from), `${from} / ${bracket.from}`).toBeTruthy();
      expect(samePlace(to, bracket.to), `${to} / ${bracket.to}`).toBeTruthy();
    }
    const panel = await page.getByTestId("ici-maintenant").innerText();
    expect(panel).not.toMatch(TECHNICAL);
    expect(await page.getByTestId("film-bar").innerText()).not.toMatch(TECHNICAL);
  });

  let legBefore = "";
  await test.step("NAV-C-04 C-05 journal et clic sans remettre l'étape", async () => {
    const journal = await page.request.get("/voyage/official/journal?limit=80", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    await openJournalTab(page);
    if (!journal || journal.status === "preparing") {
      test.info().annotations.push({
        type: "en préparation",
        description: "journal officiel pas ready — plus d'une entrée non exigée",
      });
    } else {
      const days = Array.isArray(journal.days) ? journal.days : [];
      expect(days.length).toBeGreaterThan(1);
      await expect.poll(() => page.getByTestId("journal-day").count(), { timeout: 12_000 }).toBeGreaterThan(1);
    }
    legBefore = `${await page.getByTestId("film-leg").getAttribute("data-from")}|${await page.getByTestId("film-leg").getAttribute("data-to")}`;
    const day = page.getByTestId("journal-day").first();
    if (await day.count()) {
      await day.evaluate((el) => el.click());
      await expect.poll(async () => {
        const fromNow = await page.getByTestId("film-leg").getAttribute("data-from");
        const toNow = await page.getByTestId("film-leg").getAttribute("data-to");
        return `${fromNow}|${toNow}`;
      }, { timeout: 3000 }).toBe(legBefore);
    }
  });

  await test.step("NAV-C-06 récit sans mélange", async () => {
    await openStoryTab(page);
    const story = page.getByTestId("expedition-story");
    await expect(story).toBeVisible();
    const text = await story.innerText();
    expect(text).not.toMatch(TECHNICAL);
    const legAfter = `${await page.getByTestId("film-leg").getAttribute("data-from")}|${await page.getByTestId("film-leg").getAttribute("data-to")}`;
    expect(legAfter).toBe(legBefore);
  });

  await test.step("NAV-C-12 à C-17 cartes moment", async () => {
    const body = await page.request.get("/voyage/official/moments", { timeout: 15_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    await page.getByTestId("ici-tab-now").evaluate((el) => el.click());
    const panel = page.getByTestId("ici-maintenant");
    const card = panel.locator("[data-testid='moment-now'], [data-testid='moment-free']");
    const cardShown = await card.first().waitFor({ state: "visible", timeout: 12_000 }).then(() => true).catch(() => false);
    if (!cardShown) {
      const n = Array.isArray(body?.moments) ? body.moments.length : 0;
      test.info().annotations.push({
        type: "en préparation",
        description: `aucune carte moment à la position du jour (${n} moments) — C-12 à C-17 non joués`,
      });
      return;
    }
    await openStoryTab(page);
    await expect(page.getByTestId("expedition-story")).toBeVisible();
    await expect(page.locator("[data-testid='moment-now'], [data-testid='moment-free']").first()).toBeVisible();
    await page.getByTestId("ici-tab-now").evaluate((el) => el.click());
    const free = panel.getByTestId("moment-free");
    if (await free.count()) {
      const next = free.getByTestId("moment-next");
      await expect(next).toBeVisible();
      await next.evaluate((el) => el.click());
      await expect(free).toBeVisible();
    }
    const focus = panel.getByTestId("moment-focus");
    if (await focus.count()) await focus.first().evaluate((el) => el.click());
    else {
      test.info().annotations.push({
        type: "carte",
        description: "aucune carte moment n'a de lieu à montrer — Voir sur la carte absent",
      });
    }
    const link = panel.locator("[data-testid^='moment-link-']");
    if (await link.count()) {
      await expect(link.first()).toHaveAttribute("href", /^https?:\/\//);
    } else {
      test.info().annotations.push({
        type: "carte",
        description: "la carte moment du jour n'a pas de lien http",
      });
    }
    const now = panel.getByTestId("moment-now");
    if (await now.count()) {
      const before = await now.count();
      await now.getByTestId("moment-dismiss").first().evaluate((el) => el.click());
      await expect.poll(() => now.count()).toBeLessThan(before);
    }
  });

  await test.step("NAV-H-02 H-09 pilules 2:30 / 3:00 et Stop", async () => {
    const duration = page.getByTestId("film-duration");
    if (!(await duration.isVisible().catch(() => false))) {
      test.info().annotations.push({
        type: "en préparation",
        description: "Revoir pas prêt — 2:30 / 3:00 non affichés",
      });
      return;
    }
    const pill150 = duration.locator("[data-seconds='150']");
    const pill180 = duration.locator("[data-seconds='180']");
    await expect(pill150).toBeVisible();
    await expect(pill180).toBeVisible();
    const film = await page.request.get("/voyage/official/film?lang=en&seconds=0", { timeout: 12_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    const estimates = film?.estimates && typeof film.estimates === "object" ? film.estimates : null;
    const readClock = async () => clockSeconds(await page.getByTestId("film-duration-estimate").textContent().catch(() => ""));
    for (const sec of [150, 180]) {
      const pill = sec === 150 ? pill150 : pill180;
      if (await pill.getAttribute("data-variant-absent") === "1") {
        expect(await pill.getAttribute("title")).toBeTruthy();
        continue;
      }
      if (await pill.getAttribute("aria-pressed") !== "true") await pill.click();
      await expect(pill).toHaveAttribute("aria-pressed", "true");
      const expected = Number(estimates?.[String(sec)]?.estimatedSeconds);
      if (Number.isFinite(expected) && expected >= sec * 0.9 && expected <= sec * 1.1) {
        const shown = await readClock();
        expect(shown).not.toBeNull();
        expect(shown).toBeGreaterThanOrEqual(sec * 0.9);
        expect(shown).toBeLessThanOrEqual(sec * 1.1);
      }
    }
    const replay = page.getByTestId("replay-start");
    if (await pill150.getAttribute("data-variant-absent") !== "1") await pill150.click();
    if (await replay.isEnabled()) {
      // La pilule 150 s quitte le DOM pendant le rejeu : lire son état avant de lancer.
      const pressed150 = await pill150.getAttribute("aria-pressed");
      await replay.click();
      const stop = page.getByTestId("replay-stop");
      await expect(stop).toBeVisible({ timeout: 8_000 });
      const budget = await page.evaluate(() => window.__naviguideFilm?.targetSeconds ?? null);
      if (budget != null && pressed150 === "true") {
        expect(budget).toBeGreaterThanOrEqual(150 * 0.9);
        expect(budget).toBeLessThanOrEqual(150 * 1.1);
      }
      await stop.evaluate((el) => el.click());
      await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
      expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();
    }
  });

  await test.step("NAV-I-06 polaire TWA 90 TWS 12", async () => {
    const speed = await page.request.get("/api/v1/polar/berry-mappemonde-2026/speed?twa=90&tws=12", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    if (!speed || !Number.isFinite(Number(speed.speed))) {
      test.info().annotations.push({
        type: "en préparation",
        description: "GET polaire /speed sans vitesse — cellule non comparée",
      });
      return;
    }
    await showRightPanel(page);
    await expect(page.getByTestId("polar-status")).toContainText("Polars loaded", { timeout: 15_000 });
    const show = page.getByTestId("polar-show").first();
    if (await show.isVisible().catch(() => false) && (await show.getAttribute("aria-expanded")) !== "true") {
      await show.click();
    }
    const cell = page.getByTestId("polar-speed-90-12").first();
    await expect(cell).toBeVisible({ timeout: 8_000 });
    const shown = Number(await cell.getAttribute("data-kn"));
    expect(Math.abs(shown - Number(speed.speed))).toBeLessThanOrEqual(0.05);
  });

  await test.step("NAV-I-09 I-10 jours de mer et conseil", async () => {
    const review = await page.request.get("/voyage/official/plan-review", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    if (!review || review.status !== "ready" || !Array.isArray(review.legs) || !review.legs.length) {
      test.info().annotations.push({
        type: "en préparation",
        description: "GET /plan-review pas ready — jours de mer non exigés",
      });
      return;
    }
    await openReviewTab(page);
    const rows = page.getByTestId("plan-review-leg");
    await expect(rows).toHaveCount(review.legs.length);
    for (let i = 0; i < review.legs.length; i += 1) {
      const attr = await rows.nth(i).getAttribute("data-days-at-sea");
      const expected = review.legs[i].daysAtSea;
      if (expected == null || expected === "") expect(attr || "").toBe("");
      else {
        const ui = Number(attr);
        const exp = Number(expected);
        expect(Number.isFinite(ui)).toBeTruthy();
        const scale = Math.max(Math.abs(exp), 1);
        expect(Math.abs(ui - exp) / scale).toBeLessThanOrEqual(0.1);
      }
    }
    const source = page.getByTestId("plan-review-source");
    if (await source.count()) {
      expect(await source.getAttribute("data-ai-generated")).toMatch(/^(true|false)$/);
    }
    const apply = page.getByTestId("plan-advice-apply");
    if (await apply.count()) {
      const advice = await page.request.get("/voyage/official/advice?leg=0&lang=en", { timeout: 8000 })
        .then((r) => (r.ok() ? r.json() : null))
        .catch(() => null);
      const rawWhen = advice?.best?.departIso || advice?.best?.departNow || advice?.best?.depart || "";
      const when = Date.parse(String(rawWhen).length === 10 ? `${rawWhen}T00:00:00Z` : rawWhen);
      if (Number.isFinite(when) && when <= Date.now()) await expect(apply).toBeDisabled();
    }
  });

  await test.step("NAV-I-13 I-15 I-16 fiche et exports", async () => {
    if (!(await panelClosed(page, "right"))) {
      await page.locator(".naviguide-sidebar-toggle--right").evaluate((el) => el.click());
      await expect.poll(() => panelClosed(page, "right")).toBe(true);
    }
    const findFreeFlag = () => page.evaluate(() => [...document.querySelectorAll("[data-testid='waypoint-flag']")]
      .findIndex((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return false;
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return Boolean(top && (el === top || el.contains(top)));
      }));
    const flags = page.locator("[data-testid='waypoint-flag']");
    const flagCount = await flags.count();
    // Après l'arrêt du film, la carte peut encore glisser vers le bateau et
    // repousser les drapeaux hors cadre : recadrer jusqu'à ce qu'un drapeau soit dégagé.
    let freeIdx = -1;
    if (flagCount > 0) {
      await expect.poll(async () => {
        await bringOffscreenFlagsIntoView(page);
        freeIdx = await findFreeFlag();
        return freeIdx;
      }, { message: "aucun drapeau dégagé", timeout: 10_000 }).toBeGreaterThanOrEqual(0);
    }
    if (freeIdx >= 0) {
      const flag = flags.nth(freeIdx);
      await flag.click({ force: true });
      await showLeftPanel(page);
      const opened = page.getByTestId("escale-sheet");
      await expect(opened).toBeVisible({ timeout: 25_000 });
      await expect(opened).toContainText("Port of call sheet");
      await page.getByTestId("escale-close").evaluate((el) => el.click());
      await expect(opened).toBeHidden();
      const started = Date.now();
      await flag.click({ force: true });
      await expect(opened).toBeVisible({ timeout: 3000 });
      expect(Date.now() - started).toBeLessThan(3000);
      const watch = opened.getByText(/watch of/i);
      if (await watch.count()) await expect(watch.first()).toContainText(/\d/);
    } else {
      test.info().annotations.push({
        type: "fiche",
        description: "aucun drapeau dégagé — seconde ouverture de fiche non jouée",
      });
    }

    await showRightPanel(page);
    const geoBtn = page.getByTestId("export-geojson");
    const kmlBtn = page.getByTestId("export-kml");
    await expect(geoBtn).toBeEnabled({ timeout: 20_000 });
    await expectOfficialExports(page, geoBtn, kmlBtn);
  });

  expect(errors, errors.join("\n")).toEqual([]);
});

test("non-régression tracé : jambes, terre, distance, suite, 60 points, GeoJSON", async ({ page }) => {
  test.setTimeout(150_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  const apiUp = await probeApi(page);
  const routeUp = apiUp ? await routeGet(page, LA_ROCHELLE, GIJON) : null;
  const routing = Boolean(routeUp && routeUp.ok());
  if (!routing) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /route absent — G-03, G-05, G-06, G-07, G-10, G-14 sautés ; la limite de 60 points reste exigée",
    });
  }

  await page.goto("/");
  await assertLocal(page);
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await expect(page.getByTestId("draw-point-limit")).toContainText("60 points maximum");

  if (routing) {
    await test.step("NAV-G-10 La Rochelle → Gijón trois fois", async () => {
      for (let i = 0; i < 3; i += 1) {
        const res = i === 0 ? routeUp : await routeGet(page, LA_ROCHELLE, GIJON);
        expect(res, `essai ${i + 1}`).toBeTruthy();
        expect(res.ok(), `essai ${i + 1}`).toBeTruthy();
        const body = await res.json();
        expect(Number(body?.properties?.length)).toBeGreaterThan(0);
      }
    });

    const lengths = [];
    const isPair = (url, a, b) => {
      const n = (key) => Number(url.searchParams.get(key));
      const near = (x, y) => Math.abs(x - y) < 1e-3;
      return near(n("start_lat"), a.lat) && near(n("start_lon"), a.lon)
        && near(n("end_lat"), b.lat) && near(n("end_lon"), b.lon);
    };
    page.on("response", async (res) => {
      if (!res.url().includes("/route?") || !res.ok()) return;
      const url = new URL(res.url());
      if (!isPair(url, LA_ROCHELLE, GIJON) && !isPair(url, GIJON, LISBON)) return;
      const body = await res.json().catch(() => null);
      const km = Number(body?.properties?.length);
      if (Number.isFinite(km) && km > 0) lengths.push(km);
    });

    await test.step("NAV-G-03 G-06 trois points, deux jambes, distance", async () => {
      await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
      for (const point of [LA_ROCHELLE, GIJON, LISBON]) {
        await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon, { name: p.name }), point);
      }
      await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) === 2, null, { timeout: 40_000 });
      const drawn = await page.evaluate(() => window.__naviguideDrawn);
      expect(drawn.points).toHaveLength(3);
      expect(drawn.segments).toHaveLength(2);
      expect(drawn.segments.every((seg) => seg.failed !== true)).toBe(true);
      const legNm = lengths.reduce((sum, km) => sum + km / 1.852, 0);
      expect(legNm).toBeGreaterThan(0);
      const shown = await page.getByTestId("drawing-points").innerText();
      const match = shown.match(/([\d\s\u00a0\u202f]+)\s*nm/i);
      expect(match, shown).toBeTruthy();
      const displayed = Number(String(match[1]).replace(/[^\d]/g, ""));
      expect(Math.abs(displayed - legNm) / legNm).toBeLessThan(0.01);
    });

    await test.step("NAV-G-05 point à terre refusé", async () => {
      const before = await page.evaluate(() => window.__naviguideDrawn?.points?.length || 0);
      await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), PARIS);
      await expect(page.getByTestId("route-import-error")).toContainText(/land/i, { timeout: 8_000 });
      await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(before);
    });

    await test.step("NAV-G-14 aller-retour GeoJSON", async () => {
      await showRightPanel(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByTestId("export-geojson").click(),
      ]);
      const raw = (await import("node:fs")).readFileSync(await download.path(), "utf8");
      const geo = JSON.parse(raw);
      const exported = geo.features
        .filter((f) => f.geometry?.type === "Point")
        .map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
      const live = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
      expect(exported.length).toBe(live.length);
      page.on("dialog", (dialog) => dialog.accept());
      await showLeftPanel(page);
      await page.locator(".naviguide-sidebar-panel.left-0").getByRole("button", { name: /^cancel$/i }).click();
      await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 0);
      await page.getByTestId("route-import-file").setInputFiles({
        name: "roundtrip.geojson",
        mimeType: "application/geo+json",
        buffer: Buffer.from(raw),
      });
      await page.waitForFunction((n) => (window.__naviguideDrawn?.points?.length || 0) === n, live.length, { timeout: 20_000 });
      const again = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
      expect(again.map((p) => [Number(p[0].toFixed(5)), Number(p[1].toFixed(5))])).toEqual(
        live.map((p) => [Number(p[0].toFixed(5)), Number(p[1].toFixed(5))]),
      );
    });

    await test.step("NAV-G-07 continuer le tracé", async () => {
      await showLeftPanel(page);
      const finish = page.getByRole("button", { name: /^finish$/i });
      await expect(finish).toBeEnabled({ timeout: 15_000 });
      await finish.click();
      const cont = page.getByRole("button", { name: "Continue drawing" });
      await expect(cont).toBeVisible({ timeout: 10_000 });
      await cont.click();
      await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 10_000 });
    });
  }

  await test.step("NAV-G-13 soixante points au plus", async () => {
    await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
    const initialCount = await page.evaluate(() => window.__naviguideDrawn?.points?.length || 0);
    for (let i = 0; i < 61; i += 1) {
      await page.evaluate(() => window.__naviguideAddDrawnPoint(46.157, -1.151));
      await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), {
        timeout: 60_000,
      }).toBe(Math.min(initialCount + i + 1, 60));
    }
    await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(60);
    await expect(page.getByTestId("draw-point-limit")).toContainText("60 points maximum");
  });

  expect(errors, errors.join("\n")).toEqual([]);
});
