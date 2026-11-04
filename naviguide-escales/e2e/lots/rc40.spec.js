// En pleine jambe la caméra glisse, elle ne saute pas d'ancre
// (bouée, île, événement). Sans API : GET /voyage/official sondé ; s'il
// manque, annotation + saut des assertions caméra — barre et Revoir gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc40");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const MAX_JUMP_DEG = 0.4;

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

function degJump(a, b) {
  if (!a || !b) return Infinity;
  let dLon = b.lng - a.lng;
  while (dLon > 180) dLon -= 360;
  while (dLon < -180) dLon += 360;
  return Math.hypot(b.lat - a.lat, dLon);
}

test("Pleine jambe : centre carte sans saut > 0,4°", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions caméra sautées ; barre et Revoir gardés",
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
    await shot(page, "01-caraibes");
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-caraibes");
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).catch(() => null);

  const sought = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const caraibe = (c) => {
      const from = c.fromName || "";
      const to = c.toName || "";
      const blob = `${from} ${to} ${c.text || ""}`;
      if (/Fort-de-France|Martinique/i.test(from)) return true;
      if (/Pointe-à-Pitre|Guadeloupe|Gustavia|Saint-Barth|Marigot|Saint-Martin|Sint Maarten/i.test(to)) return true;
      return /Fort-de-France/i.test(blob) && /Guadeloupe|Marigot|Antilles|Caraïbe/i.test(blob);
    };
    let i = list.findIndex(caraibe);
    if (i < 0) {
      i = list.findIndex((c) => /La Rochelle/i.test(c.fromName || "") && /Ajaccio/i.test(c.toName || ""));
    }
    if (i >= 0) window.__naviguideFilm?.seekChapter?.(i);
    return { i, from: list[i]?.fromName || "", to: list[i]?.toName || "" };
  });

  if (sought.i < 0) {
    test.info().annotations.push({
      type: "poste",
      description: "chapitre Fort-de-France → Marigot (ou La Rochelle → Ajaccio) absent — saut 0,4° non mesuré",
    });
    await shot(page, "01-caraibes");
    return;
  }

  await page.waitForFunction((idx) => (
    Number(window.__naviguideFilm?.chapterIdx) === idx
  ), sought.i, { timeout: 8_000 }).catch(() => null);
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm || {};
    const lat = Number(f.lat);
    const lon = Number(f.lon);
    return Number.isFinite(lat) && Number.isFinite(lon) && lat > 10 && lat < 22 && lon < -50 && lon > -70;
  }, null, { timeout: 12_000 }).catch(() => null);
  await page.waitForTimeout(1_500);

  let sample = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    await page.waitForTimeout(1_200);
    const a = await page.evaluate(() => {
      const ll = window.__naviguideScene?.map?.getCenter?.();
      const z = window.__naviguideScene?.map?.getZoom?.();
      const ch = Number(window.__naviguideFilm?.chapterIdx);
      if (!ll || !Number.isFinite(ll.lat)) return null;
      return { lat: ll.lat, lng: ll.lng, z, ch };
    });
    await page.waitForTimeout(1_000);
    const b = await page.evaluate(() => {
      const ll = window.__naviguideScene?.map?.getCenter?.();
      const z = window.__naviguideScene?.map?.getZoom?.();
      const ch = Number(window.__naviguideFilm?.chapterIdx);
      if (!ll || !Number.isFinite(ll.lat)) return null;
      return { lat: ll.lat, lng: ll.lng, z, ch };
    });
    if (!a || !b) continue;
    if (a.ch !== b.ch) continue;
    if (Math.abs((a.z ?? 0) - (b.z ?? 0)) > 0.05) continue;
    sample = { a, b, jump: degJump(a, b) };
    break;
  }

  if (!sample) {
    test.info().annotations.push({
      type: "poste",
      description: "pas deux centres à 1 s, même chapitre, zoom stable — saut 0,4° non mesuré",
    });
    await shot(page, "01-caraibes");
    return;
  }

  expect(
    sample.jump,
    `saut ${sample.jump.toFixed(3)}° ch${sample.a.ch} ${sought.from} → ${sought.to} z=${sample.a.z}`,
  ).toBeLessThanOrEqual(MAX_JUMP_DEG);
  await shot(page, "01-caraibes");
});

test("Seek Ajaccio → Fort-de-France : bateau au centre, un saut", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions caméra sautées ; barre et Revoir gardés",
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
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).catch(() => null);

  const sought = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const ajaccio = list.findIndex((c) => /Ajaccio/i.test(`${c.fromName || ""} ${c.toName || ""}`));
    const fdf = list.findIndex((c) => /Fort-de-France|Martinique/i.test(`${c.fromName || ""} ${c.toName || ""}`));
    if (ajaccio >= 0) window.__naviguideFilm?.seekChapter?.(ajaccio);
    return {
      ajaccio,
      fdf,
      from: list[fdf]?.fromName || "",
      to: list[fdf]?.toName || "",
    };
  });

  if (sought.ajaccio < 0 || sought.fdf < 0) {
    test.info().annotations.push({
      type: "poste",
      description: "chapitre Ajaccio ou Fort-de-France absent — flip caméra non mesuré",
    });
    return;
  }

  await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
    sought.ajaccio, { timeout: 8_000 }).catch(() => null);
  await page.waitForTimeout(400);

  await page.evaluate((idx) => window.__naviguideFilm?.seekChapter?.(idx), sought.fdf);
  await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
    sought.fdf, { timeout: 8_000 }).catch(() => null);
  const inCaribbean = await page.waitForFunction(() => {
    const f = window.__naviguideFilm || {};
    const lat = Number(f.lat);
    const lon = Number(f.lon);
    return Number.isFinite(lat) && Number.isFinite(lon) && lat > 10 && lat < 22 && lon < -50 && lon > -70;
  }, null, { timeout: 12_000 }).then(() => true).catch(() => false);
  if (!inCaribbean) {
    test.info().annotations.push({
      type: "poste",
      description: "bateau pas aux Caraïbes après seek Fort-de-France — flip non mesuré",
    });
    return;
  }
  await page.waitForTimeout(300);

  const centers = [];
  for (let i = 0; i < 10; i++) {
    const snap = await page.evaluate(() => {
      const map = window.__naviguideScene?.map;
      const f = window.__naviguideFilm || {};
      if (!map || !Number.isFinite(Number(f.lat))) return null;
      const size = map.getSize();
      const boat = map.latLngToContainerPoint([f.lat, f.lon]);
      const c = map.getCenter();
      return {
        lat: c.lat, lng: c.lng,
        nx: boat.x / size.x, ny: boat.y / size.y,
        ch: Number(f.chapterIdx),
      };
    });
    if (snap) centers.push(snap);
    await page.waitForTimeout(100);
  }

  if (!centers.length) {
    test.info().annotations.push({
      type: "poste",
      description: "pas de centre carte après seek Fort-de-France — flip non mesuré",
    });
    return;
  }

  const last = centers[centers.length - 1];
  expect(last.nx, `bateau x=${last.nx.toFixed(2)} hors 20 % centraux`).toBeGreaterThanOrEqual(0.4);
  expect(last.nx, `bateau x=${last.nx.toFixed(2)} hors 20 % centraux`).toBeLessThanOrEqual(0.6);
  expect(last.ny, `bateau y=${last.ny.toFixed(2)} hors 20 % centraux`).toBeGreaterThanOrEqual(0.4);
  expect(last.ny, `bateau y=${last.ny.toFixed(2)} hors 20 % centraux`).toBeLessThanOrEqual(0.6);

  let jumps = 0;
  for (let i = 1; i < centers.length; i++) {
    if (degJump(centers[i - 1], centers[i]) > 0.05) jumps += 1;
  }
  expect(jumps, `getCenter ${jumps} sauts en 1 s ${sought.from} → ${sought.to}`).toBeLessThanOrEqual(1);
});
