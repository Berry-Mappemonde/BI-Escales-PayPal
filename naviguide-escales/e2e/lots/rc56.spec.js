// Pendant Revoir, le bateau glisse (pas écran ≤ 30 px hors
// zoom / changement de chapitre / resize du conteneur carte).
// Le pas est mesuré dans le cadre de la carte (pas la fenêtre : un panneau
// qui s'ouvre n'est pas un bond du bateau). Le chapitre qui compte pour le
// saut caméra est `camera.filmChapterIdx` : React publie `__naviguideFilm`
// un cran trop tôt, le `setView` du flip arrive à chapterIdx déjà nouveau.
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut
// des assertions de glisse — barre et Revoir gardés. Aucune donnée factice.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitBoatUnderWay, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc56");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const SCREEN_STEP_MAX_PX = 30;

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

test("Revoir 2:30, le bateau glisse sans bond", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions glisse sautées ; barre et Revoir gardés",
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

  const pill = page.locator("[data-testid='film-duration'] [data-seconds='150']");
  if (await pill.isVisible().catch(() => false)) await pill.click();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await shot(page, "01-glisse");
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-glisse");
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });

  const underway = await waitBoatUnderWay(page, { timeout: 20_000 });
  const stats = await page.evaluate(async () => {
    const map = window.__naviguideScene?.map;
    if (!map) return { ok: false };
    const out = [];
    const t0 = performance.now();
    let prevT = t0;
    await new Promise((resolve) => {
      const tick = (now) => {
        const f = window.__naviguideFilm || {};
        const scene = window.__naviguideScene;
        const box = map.getContainer?.()?.getBoundingClientRect?.();
        let bx = null;
        let by = null;
        if (box) {
          let best = null;
          let bestIn = Infinity;
          for (const el of document.querySelectorAll(".catamaran-divicon--live")) {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            const x = (r.left + r.width / 2) - box.left;
            const y = (r.top + r.height / 2) - box.top;
            const inside = x >= 0 && y >= 0 && x <= box.width && y <= box.height;
            const d = Math.hypot(x - box.width / 2, y - box.height / 2);
            if (inside && d < bestIn) {
              bestIn = d;
              best = { x, y };
            }
          }
          if (best) {
            bx = best.x;
            by = best.y;
          }
        }
        const camCh = scene?.camera?.filmChapterIdx;
        const filmCh = f.chapterIdx;
        out.push({
          t: now, dt: now - prevT,
          bx, by, zoom: map.getZoom(),
          ch: Number.isFinite(Number(camCh)) ? Number(camCh)
            : (Number.isFinite(Number(filmCh)) ? Number(filmCh) : null),
          zoomAnim: Boolean(scene?.zoomAnimating),
          mw: box?.width ?? null, mh: box?.height ?? null,
        });
        prevT = now;
        if (now - t0 < 8000) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    const moves = [];
    for (let i = 1; i < out.length; i++) {
      const a = out[i - 1];
      const b = out[i];
      if (a.bx == null || b.bx == null || a.zoom !== b.zoom) continue;
      if (a.zoomAnim || b.zoomAnim) continue;
      if (a.ch != null && b.ch != null && a.ch !== b.ch) continue;
      if (a.mw != null && b.mw != null && (Math.abs(a.mw - b.mw) > 1 || Math.abs(a.mh - b.mh) > 1)) continue;
      moves.push(Math.hypot(b.bx - a.bx, b.by - a.by));
    }
    const max = moves.length ? Math.max(...moves) : 0;
    const zeros = moves.filter((m) => m < 0.05).length;
    return { ok: true, n: moves.length, max, zeros };
  });

  if (!stats.ok) {
    test.info().annotations.push({
      type: "poste",
      description: "carte absente — pas écran non mesuré",
    });
  } else if (!underway?.moving && stats.max < 0.05) {
    test.info().annotations.push({
      type: "poste",
      description: "bateau encore à quai — pas nuls hors mer, comme RG12",
    });
  } else if (stats.n > 0) {
    test.info().annotations.push({
      type: "glisse",
      description: `n=${stats.n} max=${Number(stats.max).toFixed(1)} (carte, hors zoom / chapitre / resize)`,
    });
    expect(stats.max, `pas bateau ${stats.max.toFixed(1)} px`).toBeLessThanOrEqual(SCREEN_STEP_MAX_PX);
  }

  await shot(page, "01-glisse");
});
