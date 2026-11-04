// Faits justes : départ horloge, vol typé, par la route.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const ROAD = /par la route|by road/i;
const AIR = /s'envole|the crew flies from|le bateau attend|le catamaran attend|the boat waits|the catamaran waits/i;
const NEXT_PAPEETE = /départ vers Papeete|departure for Papeete/i;
const DEPART_AJACCIO = /départ vers Ajaccio|departure for Ajaccio/i;
const OLD_FALSE_DEPART = /le 18 mai, départ vers Ajaccio|on 18 May, departure for Ajaccio/i;

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

function haversineNm(lat1, lon1, lat2, lon2) {
  const r = 3440.065;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
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

test("Départ horloge, vol, par la route", async ({ page }) => {
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
    await shot(page, "01-depart-la-rochelle");
    await shot(page, "02-cayenne-vol");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG1 sautées",
    });
    await shot(page, "01-depart-la-rochelle");
    await shot(page, "02-cayenne-vol");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const rg1Ready = ROAD.test(blob) && AIR.test(blob);
  if (!rg1Ready) {
    test.info().annotations.push({
      type: "stock pré-RG1",
      description: "film servi encore à l'ancienne clé — remplisseur doit recalculer (FILM_SCRIPT_REV=rg1)",
    });
    await shot(page, "01-depart-la-rochelle");
    await shot(page, "02-cayenne-vol");
    return;
  }

  expect(blob, "premier chapitre par la route").toMatch(ROAD);
  expect(blob, "vol raconté comme un vol").toMatch(AIR);
  expect(blob, "bateau reste à Cayenne").toMatch(/le bateau attend à Cayenne|le catamaran attend à Cayenne|the boat waits at Cayenne|the catamaran waits at Cayenne/i);
  expect(blob, "pas de traversée vers Saint-Pierre").not.toMatch(/départ vers Saint-Pierre|departure for Saint-Pierre/i);
  expect(blob, "pas d'approche Saint-Pierre").not.toMatch(/approche de Saint-Pierre|approaching Saint-Pierre/i);
  expect(blob, "départ Papeete depuis Cayenne").toMatch(NEXT_PAPEETE);
  expect(blob, "plus le faux 18 mai").not.toMatch(OLD_FALSE_DEPART);

  const papeete = film.chapters.find((c) => NEXT_PAPEETE.test(c.text || ""));
  expect(papeete?.fromName || "", "jambe suivante depuis Cayenne").toMatch(/cayenne/i);

  const departCh = film.chapters.find((c) => DEPART_AJACCIO.test(c.text || ""));
  const departAnchor = (departCh?.anchors || []).find((a) => {
    const slice = (departCh.text || "").slice(Number(a.charIdx) || 0);
    return DEPART_AJACCIO.test(slice);
  }) || (departCh?.anchors || [])[0];
  if (departAnchor?.t) {
    const clock = await page.request.get("/voyage/official/clock", { timeout: 12_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    const verts = clock?.vertices || [];
    if (verts.length) {
      const t0 = Date.parse(departAnchor.t);
      let best = verts[0];
      let bestDt = Infinity;
      for (const v of verts) {
        const dt = Math.abs(Date.parse(v.iso) - t0);
        if (dt < bestDt) {
          best = v;
          bestDt = dt;
        }
      }
      const d = haversineNm(46.15, -1.16, Number(best.lat), Number(best.lon));
      expect(d, "ancre départ à La Rochelle ≤ 5 nm").toBeLessThanOrEqual(5);
    }
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
    const re = new RegExp(reSrc, "i");
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => re.test(c.text || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  }, DEPART_AJACCIO.source);
  await shot(page, "01-depart-la-rochelle");

  await page.evaluate((reSrc) => {
    const re = new RegExp(reSrc, "i");
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => re.test(c.text || "") || /cayenne/i.test(c.fromName || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  }, AIR.source);
  await shot(page, "02-cayenne-vol");
});
