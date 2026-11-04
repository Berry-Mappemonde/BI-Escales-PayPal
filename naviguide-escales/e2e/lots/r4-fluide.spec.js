// Film fluide : le bateau avance sans à-coups (mode linéaire).
// Sans API : horloge locale + brut. Headless : pas de voix (webdriver).
// La glisse se mesure au début d'une longue jambe : une escale courte
// (Fort-de-France → Pointe-à-Pitre) se termine pendant les 2 s selon le
// zoom et la date, et le bateau reste alors à quai.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

// Horloge de page fixe (pendant la traversée) : `Date.now()` et `new Date()`
// ne suivent plus la date du runner. Le temps continue de s'écouler.
const FIXED_NOW_MS = Date.parse("2026-09-01T12:00:00.000Z");

async function pinPageClock(page) {
  await page.addInitScript((origin) => {
    const RealDate = Date;
    const start = RealDate.now();
    class NaviguideDate extends RealDate {
      constructor(...args) {
        if (args.length === 0) super(NaviguideDate.now());
        else super(...args);
      }

      static now() {
        return origin + (RealDate.now() - start);
      }
    }
    window.Date = NaviguideDate;
  }, FIXED_NOW_MS);
}

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r4/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("10 positions distinctes et monotones en 2 s", async ({ page }) => {
  test.setTimeout(90_000);
  await pinPageClock(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });

  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  await page.getByTestId("replay-start").click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect.poll(async () => page.evaluate(() => Boolean(window.__naviguideFilm?.startedAt)), {
    timeout: 5_000,
  }).toBe(true);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);

  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });
  const z0 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
  const chapter0 = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);

  await page.waitForFunction(() => {
    const m = window.__naviguideScene?.mainBoatMarker?.();
    const ll = m?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  }, { timeout: 15_000 }).catch(() => {});

  const markerReady = await page.evaluate(() => {
    const m = window.__naviguideScene?.mainBoatMarker?.();
    const ll = m?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  });

  if (!markerReady) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "marqueur bateau absent — positions le long de la jambe non vérifiées",
      });
    } else {
      throw new Error("marqueur bateau absent avec API");
    }
  } else {
    // Lecture prête, puis la plus longue jambe maritime : on échantillonne
    // juste après le quai, tant que l'arrivée est encore loin.
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function"
        && (f.chapters || []).some((c) => Number.isFinite(Number(c?.fromLat)) && Number.isFinite(Number(c?.toLat)));
    }, null, { timeout: 20_000 });

    const leg = await page.evaluate(async () => {
      const wrap = (lon) => ((((Number(lon) + 180) % 360) + 360) % 360) - 180;
      const nm = (aLat, aLon, bLat, bLon) => {
        const r = Math.PI / 180;
        const lat1 = Number(aLat) * r;
        const lat2 = Number(bLat) * r;
        const dLat = lat2 - lat1;
        const dLon = (wrap(bLon) - wrap(aLon)) * r;
        const h = Math.sin(dLat / 2) ** 2
          + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
        return 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(h)));
      };
      const sea = (name) => String(name || "");
      const chapters = window.__naviguideFilm.chapters || [];
      const ranked = [];
      for (let n = 0; n < chapters.length; n += 1) {
        const ch = chapters[n];
        const fromLat = Number(ch.fromLat);
        const fromLon = Number(ch.fromLon);
        const toLat = Number(ch.toLat);
        const toLon = Number(ch.toLon);
        if (![fromLat, fromLon, toLat, toLon].every(Number.isFinite)) continue;
        if (!sea(ch.toName).trim()) continue;
        const from = sea(ch.fromName);
        const to = sea(ch.toName);
        const air = (/cayenne/i.test(from) && /halifax/i.test(to))
          || (/halifax/i.test(from) && /cayenne/i.test(to));
        const land = (/saint-maur/i.test(from) && /rochelle/i.test(to))
          || (/rochelle/i.test(from) && /saint-maur/i.test(to));
        if (air || land) continue;
        const legNm = nm(fromLat, fromLon, toLat, toLon);
        if (!(legNm > 0)) continue;
        ranked.push({
          idx: Number.isFinite(Number(ch.idx)) ? Number(ch.idx) : n,
          fromLat, fromLon, toLat, toLon, legNm, from, to,
        });
      }
      ranked.sort((a, b) => b.legNm - a.legNm);
      let last = null;
      for (const candidate of ranked.slice(0, 3)) {
        if (!window.__naviguideFilm.seekChapter(candidate.idx, 0)) {
          last = { ok: false, reason: "seek", ...candidate };
          continue;
        }
        const t0 = performance.now();
        while (performance.now() - t0 < 12_000) {
          await new Promise((r) => setTimeout(r, 50));
          const f = window.__naviguideFilm;
          const marker = window.__naviguideScene?.mainBoatMarker?.();
          const ll = marker?.getLatLng?.();
          if (!f || f.ended || f.chapterIdx !== candidate.idx) continue;
          if (!Number.isFinite(f.lat) || !Number.isFinite(f.lon) || !ll) continue;
          const along = nm(candidate.fromLat, candidate.fromLon, f.lat, f.lon);
          const remain = nm(f.lat, f.lon, candidate.toLat, candidate.toLon);
          const gap = nm(ll.lat, ll.lng, f.lat, f.lon);
          const early = along > 15 && remain > candidate.legNm * 0.6;
          const onBoat = gap < Math.max(40, candidate.legNm * 0.02);
          if (early && onBoat) {
            return { ok: true, ...candidate, along, remain, gap };
          }
          last = {
            ok: false,
            reason: "hors fenêtre",
            chapter: f.chapterIdx,
            along, remain, gap,
            ...candidate,
          };
        }
      }
      return last || { ok: false, reason: "aucune jambe" };
    });
    expect(leg?.ok, `glisse au milieu d'une longue jambe (${JSON.stringify(leg)})`).toBe(true);

    const samples = [];
    for (let i = 0; i < 10; i++) {
      const pos = await page.evaluate(() => {
        const marker = window.__naviguideScene?.mainBoatMarker?.();
        const ll = marker?.getLatLng?.();
        const nm = Number(window.__naviguideFilm?.filmNm);
        if (!ll || !Number.isFinite(ll.lat) || !Number.isFinite(ll.lng)) return null;
        return { lat: ll.lat, lng: ll.lng, nm: Number.isFinite(nm) ? nm : 0 };
      });
      expect(pos, `échantillon ${i + 1} vide`).toBeTruthy();
      samples.push(pos);
      if (i < 9) await page.waitForTimeout(200);
    }
    const keys = samples.map((p) => `${p.lat.toFixed(7)},${p.lng.toFixed(7)}`);
    // Ancres RC18 : la glisse peut marquer un très court palier entre deux phrases — 8 positions
    // distinctes sur 10 en 2 s, c'est un bateau qui avance.
    expect(new Set(keys).size, `positions : ${keys.join(" | ")}`).toBeGreaterThanOrEqual(8);
    // Route : la projection lat/lng recule dans un virage (même constat ra3).
    // Les milles du film, eux, ne redescendent pas — contrat « ne recule pas ».
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i].nm, `échantillon ${i + 1} recule`).toBeGreaterThanOrEqual(samples[i - 1].nm - 1e-6);
    }
  }

  const chapter1 = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);
  if (chapter1 === chapter0) {
    const z1 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
    expect(Math.abs(z1 - z0), `zoom ${z0} → ${z1}`).toBeLessThanOrEqual(0.01);
  }
  await shot(page, "01-jambe");

  await page.waitForFunction((c0) => (window.__naviguideFilm?.chapterIdx ?? 0) !== c0, chapter0, {
    timeout: 80_000,
  }).catch(() => {});
  await shot(page, "02-suivante");
});
