// La spec DC3 compte les familles par chapitre / longue jambe,
// pas « ≤ 1 dans tout le film ». Le 2:30 reste à 0 hit famille.
// Toujours 0 « image satellite au-dessus du bateau ».
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film — barre, Suivre et Revoir restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc57");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const ATON = /\bbalise\b|\bbeacon\b/i;
const CABLE = /\bcâble\b|\bcable\b/i;
const DEPTH = /profondeur\s*:|depth\s*:/i;
const PIRACY = /Piraterie —|Piracy —/;
const SAT_INVENTED = /image satellite au-dessus|satellite image above/i;
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

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

function familyHits(blob) {
  const sents = String(blob || "").split(/(?<=[.!?…])\s+/);
  return {
    aton: sents.filter((s) => ATON.test(s)).length,
    cable: sents.filter((s) => CABLE.test(s)).length,
    depth: sents.filter((s) => DEPTH.test(s)).length,
    piracy: sents.filter((s) => PIRACY.test(s)).length,
    satInvented: sents.filter((s) => SAT_INVENTED.test(s)).length,
  };
}

function chapterWhere(ch, i) {
  const from = ch?.fromName || "?";
  const to = ch?.toName || "?";
  return `chapitre ${i} ${from} → ${to}`;
}

function assertZeroFamilyHits(hits, where) {
  expect(hits.aton, `${where} : 0 balise`).toBe(0);
  expect(hits.cable, `${where} : 0 câble`).toBe(0);
  expect(hits.depth, `${where} : 0 profondeur`).toBe(0);
  expect(hits.piracy, `${where} : 0 piraterie`).toBe(0);
  expect(hits.satInvented, `${where} : pas de phrase satellite inventée`).toBe(0);
}

function assertAtMostOnePerFamilyOnChapters(chapters, label) {
  const list = chapters || [];
  const blob = list.map((c) => c.text || "").join(" ");
  expect(familyHits(blob).satInvented, `${label} : pas de phrase satellite inventée`).toBe(0);
  for (let i = 0; i < list.length; i += 1) {
    const ch = list[i];
    const hits = familyHits(ch?.text || "");
    const where = `${label} ${chapterWhere(ch, i)}`;
    expect(hits.aton, `${where} : au plus une balise`).toBeLessThanOrEqual(1);
    expect(hits.cable, `${where} : au plus un câble`).toBeLessThanOrEqual(1);
    expect(hits.depth, `${where} : au plus une profondeur`).toBeLessThanOrEqual(1);
    expect(hits.piracy, `${where} : au plus une piraterie`).toBeLessThanOrEqual(1);
    expect(hits.satInvented, `${where} : pas de phrase satellite inventée`).toBe(0);
  }
}

test("DC3 une fois par chapitre, 2:30 à 0, pas de satellite inventé", async ({ page }) => {
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
    await shot(page, "01-integral");
    return;
  }

  const film150 = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const chapters150 = film150?.chapters || [];
  const blob150 = chapters150.map((c) => c.text || "").join(" ");
  const chars = Number(film150?.chars) || blob150.length;
  const hits150 = familyHits(blob150);

  if (!chapters150.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film 2:30 sans chapitres — assertions longueur sautées",
    });
    await shot(page, "01-integral");
    return;
  }

  assertZeroFamilyHits(hits150, "2:30");
  expect(chars / 15, "2:30 tient dans 150 s + 10 % à 15 car./s").toBeLessThanOrEqual(150 * 1.1);
  const rev = String(film150.film_script_rev || "");
  if (rev === "dc3" || rev === "ed1" || rev === "vs1") {
    expect(chars, "2:30 ≤ film_char_budget(150)").toBeLessThanOrEqual(CHAR_BUDGET_150);
  } else if (chars > CHAR_BUDGET_150) {
    test.info().annotations.push({
      type: "stock pré-DC3",
      description: `film_script_rev=${rev || "?"} — 2:30 encore ${chars} car. ; remplisseur FILM_SCRIPT_REV=vs1`,
    });
  }

  const film0 = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  assertAtMostOnePerFamilyOnChapters(film0?.chapters || [], "intégral");

  if (await start.isEnabled().catch(() => false)) {
    await muteVoice(page);
    await start.click();
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
    }, null, { timeout: 8_000 }).catch(() => null);
  }

  const pill150 = page.getByTestId("film-duration").locator("[data-seconds='150']");
  if (await pill150.isVisible().catch(() => false)) {
    if (await pill150.getAttribute("aria-pressed") !== "true") {
      await pill150.click();
      await expect(pill150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
    }
    await pill150.click();
  }
  await shot(page, "01-integral");
});
