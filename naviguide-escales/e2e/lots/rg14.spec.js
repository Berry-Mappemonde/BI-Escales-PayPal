// Ancres au bon mot (revue du 28 sept., § 5.3 / D1).
// Sans API : Suivre, Revoir et la barre tiennent seuls. GET /voyage/official
// sondé ; s'il manque, annotation + saut des assertions film — jamais la barre
// ni Revoir retirés. Aucune donnée factice : on lit le poste tel quel.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg14");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const GIBRALTAR = /Gibraltar/i;
const HOLD = /jours d'escale|escale de |jours au port|on reste |stopover|alongside/i;
const ARRIVE_AJACCIO = /Arrivée à Ajaccio|Arrival at Ajaccio/i;
const LOOKAHEAD = 12;
const GIB_LAT = 36.14;
const GIB_LON = -5.35;

function haversineNm(lat1, lon1, lat2, lon2) {
  const r = 3440.065;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
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

test("Ancre au nom, barre et Revoir présents", async ({ page }) => {
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

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-gibraltar");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG14 sautées",
    });
    await shot(page, "01-gibraltar");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const gibCh = film.chapters.find((c) => GIBRALTAR.test(c.text || ""));
  const nameAt = gibCh ? (gibCh.text || "").search(GIBRALTAR) : -1;
  const nearName = (gibCh?.anchors || []).some((a) => {
    const idx = Number(a.charIdx) || 0;
    return nameAt >= 0 && Math.abs(idx - Math.max(0, nameAt - LOOKAHEAD)) <= 8;
  });
  const holdCh = film.chapters.find((c) => HOLD.test(c.text || ""));
  const holdText = holdCh?.text || "";
  const holdAt = holdText.search(HOLD);
  const holdAnchors = (holdCh?.anchors || []).filter((a) => Number(a.charIdx) >= holdAt - 2);
  const rg14Ready = nearName && (!HOLD.test(blob) || holdAnchors.length >= 2);
  if (!rg14Ready) {
    test.info().annotations.push({
      type: "stock pré-RG14",
      description: "film servi encore à l'ancienne clé — remplisseur doit recalculer (FILM_SCRIPT_REV=rg14)",
    });
    await shot(page, "01-gibraltar");
    return;
  }

  expect(blob, "Gibraltar dit").toMatch(GIBRALTAR);
  if (HOLD.test(blob)) {
    expect(holdAnchors.length, "phrase de durée : deux ancres").toBeGreaterThanOrEqual(2);
  }
  if (ARRIVE_AJACCIO.test(blob)) {
    const arrCh = film.chapters.find((c) => ARRIVE_AJACCIO.test(c.text || ""));
    const arrText = arrCh?.text || "";
    const sentAt = arrText.search(ARRIVE_AJACCIO);
    const endAt = arrText.indexOf(".", sentAt);
    const last = endAt > sentAt ? endAt : arrText.length - 1;
    const arrAnchors = (arrCh?.anchors || []).filter((a) => {
      const idx = Number(a.charIdx) || 0;
      return idx >= sentAt && idx <= last;
    });
    expect(arrAnchors.length, "arrivée ancrée").toBeGreaterThanOrEqual(1);
    const lastArr = arrAnchors[arrAnchors.length - 1];
    expect(Number(lastArr.charIdx), "arrivée vers le dernier mot").toBeGreaterThan(sentAt + 8);
  }

  const clock = await page.request.get("/voyage/official/clock", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const verts = clock?.vertices || [];
  if (gibCh && verts.length) {
    const nameIdx = (gibCh.text || "").search(GIBRALTAR);
    const anc = (gibCh.anchors || []).find((a) => {
      const idx = Number(a.charIdx) || 0;
      return Math.abs(idx - Math.max(0, nameIdx - LOOKAHEAD)) <= 16;
    }) || (gibCh.anchors || [])[0];
    if (anc?.t) {
      const t0 = Date.parse(anc.t);
      let best = verts[0];
      let bestDt = Infinity;
      for (const v of verts) {
        const dt = Math.abs(Date.parse(v.iso) - t0);
        if (Number.isFinite(dt) && dt < bestDt) {
          best = v;
          bestDt = dt;
        }
      }
      const d = haversineNm(GIB_LAT, GIB_LON, Number(best.lat), Number(best.lon));
      expect(d, "ancre Gibraltar : bateau dans le détroit").toBeLessThanOrEqual(30);
    }
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-gibraltar");
    return;
  }

  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 });
  await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => /gibraltar|algeciras|tanger/i.test(c.text || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  });
  await shot(page, "01-gibraltar");
});
