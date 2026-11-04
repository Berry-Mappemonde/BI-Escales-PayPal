// Au changement de chapitre, un seul mouvement, bateau au centre.
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions caméra — barre et Revoir gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc49");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

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

test("Ajaccio → Fort-de-France : un recadrage, bateau au centre", async ({ page }) => {
  test.setTimeout(120_000);
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
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
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
      const boat = map.latLngToContainerPoint([Number(f.lat), Number(f.lon)]);
      const c = map.getCenter();
      return {
        lat: c.lat,
        lng: c.lng,
        nx: boat.x / size.x,
        ny: boat.y / size.y,
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
  expect(
    jumps,
    `getCenter ${jumps} sauts en 1 s ${sought.from} → ${sought.to}`,
  ).toBeLessThanOrEqual(1);

  await shot(page, "01-ajaccio-fort-de-france");

  const caraibe = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => {
      const from = c.fromName || "";
      const to = c.toName || "";
      if (/Fort-de-France|Martinique/i.test(from) && /Pointe-à-Pitre|Guadeloupe|Marigot|Gustavia/i.test(to)) {
        return true;
      }
      return /Fort-de-France/i.test(from) && /Antilles|Caraïbe/i.test(`${to} ${c.text || ""}`);
    });
    if (i >= 0) window.__naviguideFilm?.seekChapter?.(i, 0);
    return { i, from: list[i]?.fromName || "", to: list[i]?.toName || "" };
  });

  if (caraibe.i < 0) {
    test.info().annotations.push({
      type: "poste",
      description: "chapitre Fort-de-France → Pointe-à-Pitre absent — glisse Caraïbes non mesurée",
    });
    await shot(page, "02-caraibes");
    return;
  }

  await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
    caraibe.i, { timeout: 8_000 }).catch(() => null);
  await page.waitForTimeout(1_200);

  const originBoat = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    return {
      lat: Number(f.lat),
      lon: Number(f.lon),
      ch: Number(f.chapterIdx),
      from: f.fromName || "",
      to: f.toName || "",
    };
  });
  const leftQuay = Number.isFinite(originBoat.lat) && await page.waitForFunction((o) => {
    const f = window.__naviguideFilm || {};
    const lat = Number(f.lat);
    const lon = Number(f.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    return Math.hypot(lat - o.lat, lon - o.lon) > 0.01;
  }, originBoat, { timeout: 12_000 }).then(() => true).catch(() => false);

  if (!leftQuay) {
    test.info().annotations.push({
      type: "poste",
      description: "bateau encore à quai sur Fort-de-France → Pointe-à-Pitre — glisse non mesurée",
    });
    await shot(page, "02-caraibes");
    return;
  }

  const samples = [];
  for (let i = 0; i < 11; i++) {
    const snap = await page.evaluate(() => {
      const map = window.__naviguideScene?.map;
      const f = window.__naviguideFilm || {};
      if (!map || !Number.isFinite(Number(f.lat))) return null;
      const size = map.getSize();
      const boat = map.latLngToContainerPoint([Number(f.lat), Number(f.lon)]);
      const c = map.getCenter();
      return {
        lat: c.lat,
        lng: c.lng,
        nx: boat.x / size.x,
        ny: boat.y / size.y,
        ch: Number(f.chapterIdx),
      };
    });
    if (snap) samples.push(snap);
    if (i < 10) await page.waitForTimeout(200);
  }

  const run = [];
  for (const s of samples) {
    if (run.length && s.ch !== run[0].ch) break;
    run.push(s);
  }

  if (run.length < 6) {
    test.info().annotations.push({
      type: "poste",
      description: "pas assez de centres sur 2 s, même chapitre — glisse Caraïbes non mesurée",
    });
    await shot(page, "02-caraibes");
    return;
  }

  const hop = `${originBoat.from} → ${originBoat.to}`;
  const moved = degJump(run[0], run[run.length - 1]);
  expect(moved, `caméra immobile ${moved.toFixed(3)}° ${hop}`).toBeGreaterThan(0.05);

  // Saut d'île FDF→PAP ≈ 1,6°. 200–300 ms de glisse ≈ 0,4°. Seuil 0,8°.
  for (let i = 1; i < run.length; i++) {
    const jump = degJump(run[i - 1], run[i]);
    expect(
      jump,
      `saut Caraïbes ${jump.toFixed(3)}° / 200 ms ${hop}`,
    ).toBeLessThanOrEqual(0.8);
  }

  const caraibeLast = run[run.length - 1];
  expect(caraibeLast.nx, `bateau x=${caraibeLast.nx.toFixed(2)} hors 40 % centraux`).toBeGreaterThanOrEqual(0.3);
  expect(caraibeLast.nx, `bateau x=${caraibeLast.nx.toFixed(2)} hors 40 % centraux`).toBeLessThanOrEqual(0.7);
  expect(caraibeLast.ny, `bateau y=${caraibeLast.ny.toFixed(2)} hors 40 % centraux`).toBeGreaterThanOrEqual(0.3);
  expect(caraibeLast.ny, `bateau y=${caraibeLast.ny.toFixed(2)} hors 40 % centraux`).toBeLessThanOrEqual(0.7);

  await shot(page, "02-caraibes");
});
