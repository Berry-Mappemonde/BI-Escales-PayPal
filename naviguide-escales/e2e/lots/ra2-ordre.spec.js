// L'ordre du récit suit exactement le voyage.
// Sans API : le récit sidebar se construit depuis l'horloge locale.
// Le film serveur (GET /voyage/official/film) n'est vérifié que si l'API répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const ROUTE = ["Saint-Maur", "La Rochelle", "Ajaccio", "Fort-de-France"];

function firstIndex(text, needle) {
  return String(text).search(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
}

function assertRouteOrder(text, label) {
  const hits = ROUTE.map((n) => ({ n, i: firstIndex(text, n) })).filter((h) => h.i >= 0);
  expect(hits.length, `${label} : escales manquantes`).toBeGreaterThanOrEqual(3);
  for (let i = 1; i < hits.length; i++) {
    expect(hits[i - 1].i, `${label} : ${hits[i].n} avant ${hits[i - 1].n}`).toBeLessThan(hits[i].i);
  }
  const aj = firstIndex(text, "Ajaccio");
  const fdf = firstIndex(text, "Fort-de-France");
  if (aj >= 0 && fdf >= 0) expect(aj, "Ajaccio/Corse avant Fort-de-France").toBeLessThan(fdf);
}

function assertNoShiftedLeg(text) {
  expect(text).not.toMatch(/départ vers Fort-de-France[\s\S]{0,240}(?:Escale à|Arrivée à) Ajaccio/i);
  expect(text).not.toMatch(/departure for Fort-de-France[\s\S]{0,240}(?:Stopover in|Arrival at) Ajaccio/i);
}

function assertPairs(text, lang) {
  const depRe = lang === "en" ? /departure for (.+?)(?:\s*:|\.|$)/gi : /départ vers (.+?)(?:\s*:|\.|$)/gi;
  const arrRe = lang === "en" ? /Arrival at (.+?) on /gi : /Arrivée à (.+?) le /gi;
  const deps = [...String(text).matchAll(depRe)];
  const arrs = [...String(text).matchAll(arrRe)];
  if (!deps.length || !arrs.length) return false;
  const seen = [];
  for (const m of arrs) {
    const key = m[1].replace(/\s*\([^)]*\)\s*/g, " ").trim().toLowerCase();
    expect(seen, `escale répétée : ${m[1]}`).not.toContain(key);
    seen.push(key);
  }
  for (const d of deps) {
    const next = arrs.find((a) => a.index > d.index);
    if (!next) continue;
    const a = (next[1] || "").replace(/\s*\([^)]*\)\s*/g, " ").trim().toLowerCase();
    const b = (d[1] || "").replace(/\s*\([^)]*\)\s*/g, " ").trim().toLowerCase();
    expect(a, `départ vers ${d[1]} suivi de arrivée à ${next[1]}`).toBe(b);
  }
  return true;
}

function assertChapterPairs(chapters, lang) {
  const legs = (chapters || [])
    .map((c) => ({ from: String(c.fromName || "").trim(), to: String(c.toName || "").trim() }))
    .filter((l) => l.from && l.to);
  expect(legs.length, `film ${lang} : paires from/to`).toBeGreaterThanOrEqual(8);
  // Dernière jambe « départ vers Papeete » avec toName vide — le nom est
  // dans le texte, pas dans la paire. RC27 le met aussi dans from/to.
  const blob = (chapters || [])
    .map((c) => `${c.fromName || ""}→${c.toName || ""} ${c.text || ""}`)
    .join(" | ");
  expect(blob, `Papeete dans les paires ${lang}`).toMatch(/Papeete/i);
  for (let i = 1; i < legs.length; i++) {
    const prevTo = legs[i - 1].to.replace(/\s*\([^)]*\)\s*/g, " ").trim().toLowerCase();
    const curFrom = legs[i].from.replace(/\s*\([^)]*\)\s*/g, " ").trim().toLowerCase();
    expect(curFrom, `enchaînement ${legs[i - 1].to} → ${legs[i].from}`).toBe(prevTo);
  }
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  const isOn = async () => /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (!(await cinema.isVisible().catch(() => false))) return;
  if (!(await isOn())) return;
  await page.keyboard.press("Escape");
  if (!(await isOn())) return;
  await cinema.click();
}

async function showLeftPanel(page) {
  const { openStoryTab } = await import("../helpers.js");
  await openStoryTab(page);
  await expect(page.getByTestId("expedition-story")).toBeVisible({ timeout: 15_000 });
}

async function switchLang(page, code) {
  const btn = page.getByTestId(`lang-${code}`);
  if (!(await btn.isVisible().catch(() => false))) {
    const right = page.locator(".naviguide-sidebar-toggle--right");
    if (await right.isVisible().catch(() => false)) await right.click();
  }
  await expect(btn).toBeVisible({ timeout: 15_000 });
  await btn.click();
}

async function storyBlob(page) {
  const paras = page.getByTestId("story-paragraph");
  const texts = (await paras.allInnerTexts()).map((s) => s.trim());
  return { n: texts.length, text: texts.join(" ") };
}

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

test("Récit FR puis EN : Ajaccio avant Fort-de-France, sans répétition", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const apiUp = await probeOfficial(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);

  const story = page.getByTestId("expedition-story");
  await expect(story).toBeVisible({ timeout: 15_000 });

  const fr = await storyBlob(page);
  if (fr.n < 2) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "récit trop court — ordre des escales non vérifié côté sidebar",
      });
    } else {
      throw new Error(`récit FR : ${fr.n} paragraphe(s), attendu ≥ 2`);
    }
  } else {
    assertRouteOrder(fr.text, "récit FR");
    assertNoShiftedLeg(fr.text);
    if (/départ vers/.test(fr.text) && /Arrivée à/.test(fr.text)) assertPairs(fr.text, "fr");
  }

  await story.scrollIntoViewIfNeeded();
  await page.evaluate(() => {
    const box = document.querySelector("[data-testid='expedition-story']");
    if (!box) return;
    const hit = [...box.querySelectorAll("[data-testid='story-paragraph']")]
      .find((n) => /Ajaccio/i.test(n.textContent || ""));
    (hit || box).scrollIntoView({ block: "center" });
  });
  await shot(page, "01-ordre");

  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — chapitres film serveur non vérifiés",
    });
    await switchLang(page, "en");
    await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);
    return;
  }
  const { waitFilmReady } = await import("../helpers.js");
  await waitFilmReady(page);
  await page.getByTestId("replay-start").click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });

  if (apiUp) {
    const film = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(film?.chapters?.length, "GET /film?seconds=150 a des chapitres").toBeGreaterThan(0);
    const blob = film.chapters.map((c) => c.text || "").join(" ");
    assertRouteOrder(blob, "film FR");
    assertNoShiftedLeg(blob);
    assertChapterPairs(film.chapters, "fr");
    if (/départ vers .+?\.\s*Arrivée à/i.test(blob)) {
      assertPairs(blob, "fr");
    }
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — chapitres film serveur non vérifiés",
    });
  }

  await switchLang(page, "en");
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);
  await showLeftPanel(page);
  const { waitStoryLang } = await import("../helpers.js");
  await waitStoryLang(page, "en");
  const en = await storyBlob(page);
  if (en.n < 2) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "récit EN trop court — ordre non vérifié",
      });
    }
  } else {
    assertRouteOrder(en.text, "récit EN");
    assertNoShiftedLeg(en.text);
    if (/departure for/.test(en.text) && /Arrival at/.test(en.text)) assertPairs(en.text, "en");
  }

  if (apiUp) {
    const filmEn = await page.request.get("/voyage/official/film?lang=en&seconds=150", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(filmEn?.chapters?.length, "film EN : des chapitres").toBeGreaterThan(0);
    const blob = (filmEn.chapters || []).map((c) => c.text || "").join(" ");
    assertRouteOrder(blob, "film EN");
    assertNoShiftedLeg(blob);
    assertChapterPairs(filmEn.chapters, "en");
    if (/departure for .+?\.\s*Arrival at/i.test(blob)) {
      assertPairs(blob, "en");
    }
  }
});
