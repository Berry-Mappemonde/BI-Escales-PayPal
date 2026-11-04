// Cinématique du film : glisse, zoom stable, fond dessiné.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; zoom / glisse / fond
// pendant le film sont sautés. GET /voyage/official sondé ; s'il manque,
// annotation + saut des seules assertions caméra — jamais Revoir retiré.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf6");
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

function tilesOnMap() {
  const imgs = [...document.querySelectorAll(".leaflet-tile-container img, img.leaflet-tile")];
  const painted = imgs.filter((img) => {
    const st = getComputedStyle(img);
    return img.naturalWidth > 2 && st.opacity !== "0" && st.visibility !== "hidden";
  });
  return { n: painted.length, ok: painted.length > 0 };
}

test("Caméra glisse, zoom stable 4 s, fond dessiné", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — glisse / zoom / fond pendant le film sautés ; Suivre et Revoir gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("replay-departure")).toBeVisible();
    await shot(page, "01-glisse");
    await shot(page, "02-fond");
    return;
  }

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });

  await page.waitForTimeout(1_200);
  let z0 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
  let chapter0 = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);
  let z1 = z0;
  let chapter1 = chapter0;
  for (let i = 0; i < 4; i++) {
    chapter0 = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);
    z0 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
    await page.waitForTimeout(4_000);
    const end = await page.evaluate(() => ({
      z: window.__naviguideScene.map.getZoom(),
      ch: window.__naviguideFilm?.chapterIdx ?? 0,
    }));
    z1 = end.z;
    chapter1 = end.ch;
    if (chapter1 === chapter0) break;
  }
  expect(chapter1, "mesure à cheval sur deux chapitres").toBe(chapter0);
  expect(Math.abs(z1 - z0), `zoom ${z0} → ${z1}`).toBeLessThanOrEqual(0.01);

  // Film ancré : caméra immobile tant que le bateau est à quai — on mesure la glisse une fois en route.
  const { waitBoatUnderWay } = await import("../helpers.js");
  const way = await waitBoatUnderWay(page, { timeout: 60_000 });
  expect(way.moving, `le bateau a pris la mer avant la mesure (${JSON.stringify(way)})`).toBe(true);
  const centers = [];
  for (let i = 0; i < 8; i++) {
    const c = await page.evaluate(() => {
      const ll = window.__naviguideScene?.map?.getCenter?.();
      if (!ll || !Number.isFinite(ll.lat)) return null;
      return { lat: ll.lat, lng: ll.lng };
    });
    expect(c, `centre ${i + 1} vide`).toBeTruthy();
    centers.push(c);
    if (i < 7) await page.waitForTimeout(180);
  }
  const keys = centers.map((p) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`);
  expect(new Set(keys).size, `centres : ${keys.join(" | ")}`).toBeGreaterThan(1);
  const dLat = centers.at(-1).lat - centers[0].lat;
  const dLng = centers.at(-1).lng - centers[0].lng;
  const progress = centers.map((p) => (
    (p.lat - centers[0].lat) * dLat + (p.lng - centers[0].lng) * dLng
  ));
  // Cadrage au tiers avant sur le cap instantané : la caméra peut reculer d'un cheveu quand le cap
  // tourne — on refuse un vrai retour en arrière (> 25 % du chemin parcouru), pas ce frémissement (RG13 lissera le cap).
  const span = Math.abs(progress[progress.length - 1] - progress[0]) || 1e-9;
  for (let i = 1; i < progress.length; i++) {
    expect(progress[i], `centre ${i + 1} recule`).toBeGreaterThanOrEqual(progress[i - 1] - 0.25 * span);
  }

  await shot(page, "01-glisse");

  const tiles = await page.evaluate(tilesOnMap);
  expect(tiles.ok, `fond damier (${tiles.n} tuiles)`).toBeTruthy();
  await shot(page, "02-fond");
});
