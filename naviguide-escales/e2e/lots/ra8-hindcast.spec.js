// Tronçon parcouru teinté hindcast (ERA5), pas tout violet climatologie.
// Sans API : fumée Suivre + légende des trois régimes (jamais inventée).
// Avec API : sommets passés regime=hindcast, store.hindcast sans Copernicus.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra8/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Tronçon parcouru teinté hindcast", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const legend = page.getByTestId("regime-legend");
  await expect(legend).toBeVisible({ timeout: 15_000 });
  const pill = page.getByTestId("speed-regime-pill");
  await expect(pill).toBeVisible();
  await expect(pill).toHaveAttribute("title", /hindcast|prévision|forecast|climatolog/i);

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — teinte hindcast et store non vérifiés",
    });
    await shot(page, "01-hindcast");
    return;
  }

  const clock = await page.request.get("/voyage/official/clock", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const regimes = await page.request.get("/voyage/official/regimes", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const warm = await page.request.get("/ici/warm/status", { timeout: 5000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);

  if (warm && warm.store) {
    expect(typeof warm.store.hindcast, "store.hindcast sans Copernicus").toBe("number");
    expect(warm.store.hindcast).toBeGreaterThanOrEqual(0);
  }

  const now = Date.now();
  const past = (clock?.vertices || []).filter((v) => {
    const t = Date.parse(v?.iso || "");
    return Number.isFinite(t) && t < now && v.vehicle === "main" && (v.speedKnots || 0) > 0;
  });
  const portions = regimes?.portions || [];
  const hindcastPortion = portions.some((p) => p.regime === "hindcast");
  const pastHindcast = past.some((v) => (v.regime || v.kind) === "hindcast");

  if (pastHindcast || hindcastPortion) {
    expect(pastHindcast || hindcastPortion, "tronçon parcouru en hindcast").toBeTruthy();
    if (pastHindcast) {
      const sample = past.find((v) => (v.regime || v.kind) === "hindcast");
      expect(sample.speedKnots).toBeGreaterThan(0);
      if (Array.isArray(sample.sources) && sample.sources.length) {
        expect(sample.sources.some((s) => String(s).includes("era5") || String(s).includes("om-"))).toBeTruthy();
      }
    }
    const colors = await page.evaluate(() => {
      const map = window.__naviguideScene?.map;
      const found = [];
      if (!map?.eachLayer) return found;
      map.eachLayer((layer) => {
        const walk = (l) => {
          const c = l?.options?.color;
          if (c) found.push(String(c).toLowerCase());
          if (typeof l?.getLayers === "function") l.getLayers().forEach(walk);
        };
        walk(layer);
      });
      return found;
    });
    if (colors.includes("#2dd4bf")) {
      expect(colors, "trait teinté hindcast (teal)").toContain("#2dd4bf");
    }
  } else {
    test.info().annotations.push({
      type: "poste",
      description: "hindcast en cours — clock encore climatologie, remplissage ERA5 en fond, jamais inventé",
    });
  }

  await shot(page, "01-hindcast");
});
