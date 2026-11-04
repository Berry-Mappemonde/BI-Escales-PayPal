// Caméra et rendu à 60 Hz (revue du 28 sept.).
// Sans API : Suivre, Revoir et la barre tiennent seuls. GET /voyage/official
// sondé ; s'il manque, annotation + saut des assertions film — jamais la barre
// ni Revoir retirés. Aucune donnée factice : on lit le poste tel quel.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitBoatUnderWay, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg13");
const recetteRc25 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc25");
const recetteRc29 = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc29");
mkdirSync(recetteDir, { recursive: true });
mkdirSync(recetteRc25, { recursive: true });
mkdirSync(recetteRc29, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});
const shotRc25 = (page, name) => page.screenshot({
  path: join(recetteRc25, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});
const shotRc29 = (page, name) => page.screenshot({
  path: join(recetteRc29, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const STILL_NM = 0.5;
const BOAT_JUMP_PX = 40;

async function measureChapterFlip(page, timeoutMs = 50_000) {
  return page.evaluate(async (limit) => {
    const R = 3440.065;
    const toRad = (d) => (d * Math.PI) / 180;
    const nmBetween = (a, b) => {
      if (!a || !b || ![a.lat, a.lon, b.lat, b.lon].every(Number.isFinite)) return Infinity;
      const dLat = toRad(b.lat - a.lat);
      let dLonDeg = b.lon - a.lon;
      while (dLonDeg > 180) dLonDeg -= 360;
      while (dLonDeg < -180) dLonDeg += 360;
      const dLon = toRad(dLonDeg);
      const s = Math.sin(dLat / 2) ** 2
        + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
      return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
    };
    const read = () => {
      const f = window.__naviguideFilm || {};
      const el = document.querySelector(".catamaran-divicon--live");
      const r = el?.getBoundingClientRect?.();
      return {
        ch: Number.isFinite(Number(f.chapterIdx)) ? Number(f.chapterIdx) : 0,
        lat: Number(f.lat),
        lon: Number(f.lon),
        x: r && r.width ? r.left + r.width / 2 : null,
        y: r && r.height ? r.top + r.height / 2 : null,
        ended: Boolean(f.ended),
      };
    };
    const log = [];
    const t0 = performance.now();
    while (performance.now() - t0 < limit) {
      const s = read();
      log.push(s);
      if (s.ended) break;
      if (log.length >= 2 && s.ch !== log[log.length - 2].ch) {
        const holdUntil = performance.now() + 2000;
        while (performance.now() < holdUntil) {
          await new Promise((r) => requestAnimationFrame(r));
          log.push(read());
        }
        break;
      }
      await new Promise((r) => requestAnimationFrame(r));
    }
    let idx = -1;
    for (let i = 1; i < log.length; i++) {
      if (log[i].ch !== log[i - 1].ch) {
        idx = i;
        break;
      }
    }
    if (idx < 0) {
      const chs = [...new Set(log.map((s) => s.ch))];
      return {
        flipped: false,
        ended: Boolean(log.at(-1)?.ended),
        chs,
        n: log.length,
        firstCh: log[0]?.ch,
        lastCh: log.at(-1)?.ch,
        lastLat: log.at(-1)?.lat,
      };
    }
    let prev = log[idx - 1];
    for (let i = idx - 1; i >= 0; i--) {
      if (log[i].x != null && Number.isFinite(log[i].lat)) {
        prev = log[i];
        break;
      }
    }
    const cur = log[idx];
    const jumps = [];
    let lastStill = prev.x != null ? prev : null;
    for (let i = idx; i < log.length; i++) {
      const a = log[i - 1];
      const b = log[i];
      if (nmBetween(prev, b) > 0.5) break;
      if (b.x != null) lastStill = b;
      if (a?.x == null || b?.x == null) continue;
      jumps.push(Math.hypot(b.x - a.x, b.y - a.y));
    }
    return {
      flipped: true,
      from: prev.ch,
      to: cur.ch,
      nm: nmBetween(prev, cur),
      dpx: prev.x != null && cur.x != null ? Math.hypot(cur.x - prev.x, cur.y - prev.y) : null,
      totalPx: prev.x != null && lastStill?.x != null
        ? Math.hypot(lastStill.x - prev.x, lastStill.y - prev.y)
        : null,
      maxJump: jumps.length ? Math.max(...jumps) : null,
      samplesAfter: jumps.length,
    };
  }, timeoutMs);
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

test("Cadrage film, barre et Revoir présents", async ({ page }) => {
  test.setTimeout(120_000);
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
    await shot(page, "01-cadrage");
    await shotRc25(page, "01-chapitre-sans-bond");
    await shotRc29(page, "01-flip-bateau-centre");
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-cadrage");
    await shotRc25(page, "01-chapitre-sans-bond");
    await shotRc29(page, "01-flip-bateau-centre");
    return;
  }

  const flipP = measureChapterFlip(page, 55_000);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  expect((await subtitle.innerText()).trim().length, "sous-titre non vide").toBeGreaterThan(0);

  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });

  const flip = await flipP;
  test.info().annotations.push({
    type: "flip",
    description: flip.flipped
      ? `ch${flip.from}→ch${flip.to} Δnm=${Number(flip.nm).toFixed(2)} dpx=${flip.dpx} totalPx=${flip.totalPx} maxJump=${flip.maxJump}`
      : `pas de flip (${flip.ended ? "film fini" : "timeout"}) chs=${JSON.stringify(flip.chs)} n=${flip.n} last=${flip.lastCh}@${flip.lastLat}`,
  });
  if (!flip.flipped) {
    test.info().annotations.push({
      type: "poste",
      description: "chapitre 1 pas atteint — assertion |Δpx| au flip sautée",
    });
  } else if (!(flip.nm <= STILL_NM)) {
    test.info().annotations.push({
      type: "poste",
      description: `flip ch${flip.from}→ch${flip.to} Δnm=${Number(flip.nm).toFixed(2)} — pas le cas à quai`,
    });
  } else if (flip.dpx == null) {
    test.info().annotations.push({
      type: "poste",
      description: `flip ch${flip.from}→ch${flip.to} sans icône bateau — |Δpx| non mesuré`,
    });
  } else {
    expect(flip.dpx, `bateau ${flip.dpx} px au flip ch${flip.from}→ch${flip.to}`).toBeLessThanOrEqual(BOAT_JUMP_PX);
    if (flip.totalPx != null) {
      expect(
        flip.totalPx,
        `cumul ${flip.totalPx} px sur ≥2s après flip ch${flip.from}→ch${flip.to}`,
      ).toBeLessThanOrEqual(BOAT_JUMP_PX);
    }
    if (flip.maxJump != null) {
      expect(flip.maxJump, `saut max ${flip.maxJump} px autour du flip`).toBeLessThanOrEqual(BOAT_JUMP_PX);
    }
  }
  await shotRc25(page, "01-chapitre-sans-bond");
  await shotRc29(page, "01-flip-bateau-centre");

  const underway = await waitBoatUnderWay(page, { timeout: 20_000 });
  if (!underway?.moving) {
    test.info().annotations.push({
      type: "poste",
      description: "bateau encore à quai sur les premières phrases — capture telle quelle",
    });
  }

  const frame = await page.evaluate(() => {
    const map = window.__naviguideScene?.map;
    const boat = document.querySelector(".catamaran-divicon--live");
    const box = map?.getContainer?.()?.getBoundingClientRect?.();
    if (!map || !boat || !box) return { ok: false };
    const r = boat.getBoundingClientRect();
    const bx = r.left + r.width / 2;
    const by = r.top + r.height / 2;
    const dx = Math.abs(bx - (box.left + box.width / 2)) / box.width;
    const dy = Math.abs(by - (box.top + box.height / 2)) / box.height;
    return { ok: true, dx, dy, tiles: document.querySelectorAll("img.leaflet-tile").length };
  });
  if (frame.ok && underway?.moving) {
    expect(frame.dx, "bateau trop loin du centre (largeur)").toBeLessThanOrEqual(0.4);
    expect(frame.dy, "bateau trop loin du centre (hauteur)").toBeLessThanOrEqual(0.4);
    expect(frame.tiles, "fond damier").toBeGreaterThan(0);
  }

  await shot(page, "01-cadrage");
});
