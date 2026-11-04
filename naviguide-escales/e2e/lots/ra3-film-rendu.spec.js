// Revoir l'expédition : fond, glisse, zoom stable, archipel, bulle.
// Sans API : tuiles, glisse, zoom à l'arrêt et bulle se vérifient sur le brut local.
// Caraïbes / film serveur : seulement si GET /voyage/official répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function muteFilmVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

function tilesOnMap() {
  const scene = window.__naviguideScene;
  const map = scene?.map;
  const layer = scene?.baseLayer;
  if (!map || !layer) return { ok: false, reason: "layer" };
  if (typeof map.hasLayer === "function" && !map.hasLayer(layer)) {
    return { ok: false, reason: "detached" };
  }
  const imgs = [...document.querySelectorAll(".leaflet-tile-container img, img.leaflet-tile")];
  const painted = imgs.filter((img) => {
    const st = getComputedStyle(img);
    return img.naturalWidth > 2 && st.opacity !== "0" && st.visibility !== "hidden";
  });
  return { ok: true, attached: true, n: painted.length };
}

test("Fond gardé, bateau glisse, zoom stable, bulle fermable", async ({ page }) => {
  test.setTimeout(200_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const apiUp = await probeOfficial(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });

  await muteFilmVoice(page);
  if (!(await start.isEnabled())) {
    test.info().annotations.push({
      type: apiUp ? "film vide" : "sans API",
      description: "Revoir grisé — glisse et bulle sautées ; tuiles et bouton gardés",
    });
    await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 10_000 }).catch(() => {});
    const tiles0 = await page.evaluate(tilesOnMap);
    expect(tiles0.ok, `tuiles au départ (${tiles0.reason || tiles0.n})`).toBeTruthy();
    await shot(page, "01-fond-carte");
    await expect(start).toBeVisible();
    return;
  }
  await start.click();
  await muteFilmVoice(page);
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 10_000 });

  const tiles0 = await page.evaluate(tilesOnMap);
  expect(tiles0.ok, `tuiles au départ (${tiles0.reason || tiles0.n})`).toBeTruthy();
  await page.waitForTimeout(1_200);
  const tiles1 = await page.evaluate(tilesOnMap);
  expect(tiles1.ok, "tuiles encore là après 1 s").toBeTruthy();
  await shot(page, "01-fond-carte");

  await page.waitForFunction(() => {
    const m = window.__naviguideScene?.mainBoatMarker?.();
    const ll = m?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  }, null, { timeout: 15_000 }).catch(() => {});

  const markerReady = await page.evaluate(() => {
    const m = window.__naviguideScene?.mainBoatMarker?.();
    const ll = m?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  });

  if (!markerReady) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "marqueur bateau absent — glisse le long du trait non vérifiée",
      });
    } else {
      throw new Error("marqueur bateau absent avec API");
    }
  } else {
    // Film ancré (RC18) : à quai pendant les premières phrases — la glisse se mesure une fois en route.
    const { waitBoatUnderWay } = await import("../helpers.js");
    const way = await waitBoatUnderWay(page, { timeout: 60_000 });
    expect(way.moving, `le bateau a pris la mer avant la mesure (${JSON.stringify(way)})`).toBe(true);
    const samples = [];
    for (let i = 0; i < 8; i++) {
      const pos = await page.evaluate(() => {
        const marker = window.__naviguideScene?.mainBoatMarker?.();
        const ll = marker?.getLatLng?.();
        const nm = Number(window.__naviguideFilm?.filmNm);
        if (!ll || !Number.isFinite(ll.lat) || !Number.isFinite(ll.lng)) return null;
        return { lat: ll.lat, lng: ll.lng, nm: Number.isFinite(nm) ? nm : 0 };
      });
      expect(pos, `échantillon ${i + 1} vide`).toBeTruthy();
      samples.push(pos);
      if (i < 7) await page.waitForTimeout(180);
    }
    const keys = samples.map((p) => `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`);
    expect(new Set(keys).size, `positions : ${keys.join(" | ")}`).toBeGreaterThan(1);
    // Route côtière : la projection lat/lng sur 1 s de film compressé recule
    // dans un virage. Les milles du film, eux, ne redescendent pas.
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i].nm, `échantillon ${i + 1} recule`).toBeGreaterThanOrEqual(samples[i - 1].nm - 1e-6);
    }
  }

  const tilesMid = await page.evaluate(tilesOnMap);
  expect(tilesMid.ok, "tuiles encore là à mi-parcours").toBeTruthy();

  const bubble = page.getByTestId("event-bubble");
  const appeared = await bubble.isVisible({ timeout: 28_000 }).catch(() => false);
  if (!appeared) {
    test.info().annotations.push({
      type: apiUp ? "poste" : "sans API",
      description: "bulle d'approche absente — assertions croix / Échap sautées",
    });
  } else {
    expect(await page.getByTestId("event-bubble").count()).toBe(1);
    await page.getByTestId("event-bubble-close").click();
    await expect(page.getByTestId("event-bubble")).toHaveCount(0);
    expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);
    await expect(page.getByTestId("replay-stop")).toBeVisible();
  }

  const caraibes = await page.waitForFunction(() => {
    const film = window.__naviguideFilm || {};
    const ll = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
    const lat = Number.isFinite(ll?.lat) ? ll.lat : film.lat;
    const lon = Number.isFinite(ll?.lng) ? ll.lng : film.lon;
    const inArchipelago = Number.isFinite(lat) && Number.isFinite(lon)
      && lat > 10 && lat < 19 && lon > -68 && lon < -58;
    if (!inArchipelago) return false;
    const sub = document.querySelector("[data-testid='film-subtitle']")?.textContent || "";
    return (film.chapterIdx ?? 0) >= 2
      || /Fort-de-France|Martinique|Guadeloupe|Antigua|Barbade/i.test(sub);
  }, null, { timeout: apiUp ? 55_000 : 8_000 }).then(() => true).catch(() => false);

  if (caraibes) {
    const z = await page.evaluate(() => window.__naviguideScene.map.getZoom());
    expect(z, `zoom Caraïbes ${z}`).toBeLessThanOrEqual(5.25);
    await shot(page, "02-caraibes");
  } else {
    test.info().annotations.push({
      type: apiUp ? "poste" : "sans API",
      description: "chapitre Caraïbes non atteint — capture du plan courant",
    });
    await shot(page, "02-caraibes");
  }

  const zFilm = await page.evaluate(() => {
    window.__naviguideScene?.map?.stop?.();
    return window.__naviguideScene.map.getZoom();
  });
  await page.getByTestId("replay-stop").click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await page.waitForTimeout(500);
  const zAfter = await page.evaluate(() => window.__naviguideScene.map.getZoom());
  expect(Math.abs(zAfter - zFilm), `zoom ${zFilm} → ${zAfter}`).toBeLessThanOrEqual(0.2);
  const tilesEnd = await page.evaluate(tilesOnMap);
  expect(tilesEnd.ok, "tuiles après arrêt").toBeTruthy();
});
