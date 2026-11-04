// Clic sur un point de calque : la fiche s'ouvre même si un autre canevas
// (AMP) recouvre la carte. Données de catalogue simulées, aucun écriture.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, panelClosed } from "../helpers.js";

const project = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-19, 56.5] },
      properties: {
        naviguideCatalogId: "projects:1",
        name: "Récif sentinelle",
        title: "Récif sentinelle",
        url: "https://example.org/projet",
        funder: "Fondation",
      },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-17, 57] },
      properties: {
        naviguideCatalogId: "projects:cluster",
        name: "4 points regroupés",
        title: "4 points regroupés",
        url: "https://example.org/cluster",
        clusterCount: 4,
      },
    },
  ],
};

const marina = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
      geometry: { type: "Point", coordinates: [-18, 56] },
    properties: {
      naviguideCatalogId: "marinas:1",
      name: "Port des Minimes",
      website: "https://example.org/marina",
      country: "FR",
    },
  }],
};

const amp = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [[[-16.5, 54.2], [-14.5, 54.2], [-14.5, 55.5], [-16.5, 55.5], [-16.5, 54.2]]],
    },
    properties: {
      naviguideCatalogId: "amp:1",
      name: "Pertuis Charentais",
      designation: "Natura 2000",
      country: "FR",
      manager_url: "https://example.org/manager",
      visit_url: "https://example.org/visit",
      lfp: 3,
    },
  }],
};

async function openLayers(page) {
  const drawer = page.getByTestId("layers-drawer");
  if (!(await drawer.locator("summary").isVisible().catch(() => false))) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
    await expect(drawer.locator("summary")).toBeVisible({ timeout: 10_000 });
  }
  if (!(await drawer.evaluate((el) => el.open))) await drawer.locator("summary").click();
}

async function enableLayer(page, key, catalog) {
  const button = page.getByTestId(`layer-${key}`);
  await button.scrollIntoViewIfNeeded();
  if ((await button.getAttribute("aria-pressed")) === "true") return;
  const loaded = page.waitForResponse((response) => (
    response.url().includes(`/proxy/catalog/${catalog}`) && response.ok()
  ));
  await button.click();
  await loaded;
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

async function releaseCamera(page, lat, lng) {
  await page.evaluate(({ lat, lng }) => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.fire("dragstart");
    scene.map.setView([lat, lng], 7, { animate: false });
  }, { lat, lng });
}

async function clickLatLng(page, lat, lng) {
  await releaseCamera(page, lat, lng);
  const point = await page.evaluate(({ lat, lng }) => {
    const map = window.__naviguideScene.map;
    const projected = map.latLngToContainerPoint([lat, lng]);
    return { x: projected.x, y: projected.y };
  }, { lat, lng });
  const box = await page.locator("#simulator-map").boundingBox();
  await page.mouse.click(box.x + point.x, box.y + point.y);
}

test("clic AMP, projet ou marina : la fiche et son lien s'ouvrent", async ({ page }) => {
  await page.route("**/proxy/catalog/projects**", (route) => route.fulfill({ json: project }));
  await page.route("**/proxy/catalog/marinas**", (route) => route.fulfill({ json: marina }));
  await page.route("**/proxy/catalog/amp**", (route) => route.fulfill({ json: amp }));
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => window.__naviguideScene?.map);
  await openLayers(page);
  await enableLayer(page, "projects", "projects");
  await enableLayer(page, "marinas", "marinas");
  await enableLayer(page, "amp", "amp");
  await page.waitForFunction(() => {
    const map = window.__naviguideScene?.map;
    if (!map) return false;
    let points = 0;
    let polygons = 0;
    map.eachLayer((layer) => {
      if (typeof layer.getLatLng === "function" && Number.isFinite(layer.options?.radius)) points += 1;
      if (typeof layer.getLatLngs === "function" && (layer.options?.fillOpacity || 0) > 0) polygons += 1;
    });
    return points >= 3 && polygons >= 1;
  });

  const fiche = page.getByTestId("layer-fiche");

  await clickLatLng(page, 56, -18);
  await expect(fiche).toBeVisible();
  await expect(fiche).toContainText("Port des Minimes");
  await expect(fiche.locator("a[href='https://example.org/marina']")).toBeVisible();

  await clickLatLng(page, 56.5, -19);
  await expect(fiche).toContainText("Récif sentinelle");
  await expect(fiche.locator("a[href='https://example.org/projet']")).toBeVisible();

  await clickLatLng(page, 54.8, -15.5);
  await expect(fiche).toContainText("Pertuis Charentais");
  const links = fiche.locator("a");
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toHaveAttribute("href", "https://example.org/manager");
  await expect(links.nth(1)).toHaveAttribute("href", "https://example.org/visit");

  await clickLatLng(page, 57, -17);
  await expect(fiche).toContainText("4 points regroupés");
  // One point's link is not the group's: none on a grouped cell.
  await expect(fiche.locator("a")).toHaveCount(0);
  await expect(fiche).toContainText("Zoomez pour voir chaque point");
});

async function openThreeLayers(page, { ampLayer = amp } = {}) {
  await page.route("**/proxy/catalog/projects**", (route) => route.fulfill({ json: project }));
  await page.route("**/proxy/catalog/marinas**", (route) => route.fulfill({ json: marina }));
  await page.route("**/proxy/catalog/amp**", (route) => route.fulfill({ json: ampLayer }));
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => window.__naviguideScene?.map);
  await openLayers(page);
  await enableLayer(page, "projects", "projects");
  await enableLayer(page, "marinas", "marinas");
  await enableLayer(page, "amp", "amp");
  await page.waitForFunction(() => {
    const map = window.__naviguideScene?.map;
    if (!map) return false;
    let points = 0;
    map.eachLayer((layer) => {
      if (typeof layer.getLatLng === "function" && Number.isFinite(layer.options?.radius)) points += 1;
    });
    return points >= 3;
  });
}

const FRENCH_LABELS = /\b(Site|Projet|Voir le projet|Téléphone|Gestionnaire|Visite|Navire|regroupés|Port d'entrée|Aire marine protégée)\b/;

test("en anglais, la fiche n'affiche aucun libellé français", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  await openThreeLayers(page);
  const fiche = page.getByTestId("layer-fiche");

  await clickLatLng(page, 56, -18);
  await expect(fiche).toContainText("Port des Minimes");
  await expect(fiche).toContainText("Website");
  await expect(fiche).not.toContainText(FRENCH_LABELS);

  await clickLatLng(page, 56.5, -19);
  await expect(fiche).toContainText("Récif sentinelle");
  await expect(fiche).not.toContainText(FRENCH_LABELS);
  const projectLink = fiche.getByRole("link", { name: "View the project →" });
  await expect(projectLink).toBeVisible();
  await expect(projectLink).toHaveAttribute("href", "https://example.org/projet");

  await clickLatLng(page, 54.8, -15.5);
  await expect(fiche).toContainText("Pertuis Charentais");
  await expect(fiche).toContainText("Manager");
  await expect(fiche).toContainText("Visit");
  await expect(fiche).not.toContainText(FRENCH_LABELS);

  await clickLatLng(page, 57, -17);
  await expect(fiche).toContainText("4 grouped points");
  await expect(fiche).not.toContainText(FRENCH_LABELS);
  await expect(fiche.getByRole("button", { name: "Close the card" })).toBeVisible();
});

test("à 390 px, la fiche reste au-dessus de la barre du film", async ({ page }) => {
  await openThreeLayers(page);
  await page.setViewportSize({ width: 390, height: 844 });
  // Panneaux fermés : la carte reçoit le clic.
  for (const side of ["left", "right"]) {
    if (await panelClosed(page, side)) continue;
    await page.locator(`.naviguide-sidebar-toggle--${side}`).evaluate((el) => el.click());
    await expect.poll(() => panelClosed(page, side), { timeout: 10_000 }).toBe(true);
  }
  const fiche = page.getByTestId("layer-fiche");
  await clickLatLng(page, 54.8, -15.5);
  await expect(fiche).toContainText("Pertuis Charentais");
  const bar = page.getByTestId("film-bar");
  await expect(bar).toBeVisible();
  const ficheBox = await fiche.boundingBox();
  const barBox = await bar.boundingBox();
  expect(ficheBox.y).toBeGreaterThanOrEqual(0);
  expect(ficheBox.x).toBeGreaterThanOrEqual(0);
  expect(ficheBox.x + ficheBox.width).toBeLessThanOrEqual(390);
  expect(ficheBox.y + ficheBox.height, "la fiche ne recouvre pas la barre").toBeLessThanOrEqual(barBox.y + 0.5);
});

test("a point kept across a zoom takes the new radius", async ({ page }) => {
  await openThreeLayers(page);
  const radiusAt = (lat, lng) => page.evaluate(({ lat, lng }) => {
    let r = null;
    window.__naviguideScene.map.eachLayer((layer) => {
      if (typeof layer.getLatLng !== "function" || !Number.isFinite(layer.options?.radius)) return;
      const p = layer.getLatLng();
      if (Math.abs(p.lat - lat) < 1e-6 && Math.abs(p.lng - lng) < 1e-6) r = layer.options.radius;
    });
    return r;
  }, { lat, lng });
  await releaseCamera(page, 56, -18);
  await expect.poll(() => radiusAt(56, -18), { timeout: 10_000 }).not.toBeNull();
  const before = await radiusAt(56, -18);
  await page.evaluate(() => new Promise((resolve) => {
    const map = window.__naviguideScene.map;
    const done = () => resolve(true);
    map.once("zoomend", done);
    map.setView([56, -18], 12, { animate: false });
    if (map.getZoom() === 12) {
      map.off("zoomend", done);
      resolve(true);
    }
  }));
  await expect.poll(() => radiusAt(56, -18), { timeout: 15_000 }).toBeGreaterThan(before);
});

test("on a short screen the card scrolls inside itself, above the film bar", async ({ page }) => {
  // A long designation: the card is taller than the room left above the bar.
  const longAmp = structuredClone(amp);
  longAmp.features[0].properties.designation = Array.from({ length: 24 }, (_, i) => `Zone de protection ${i + 1}`).join(", ");
  await openThreeLayers(page, { ampLayer: longAmp });
  await page.setViewportSize({ width: 390, height: 600 });
  for (const side of ["left", "right"]) {
    if (await panelClosed(page, side)) continue;
    await page.locator(`.naviguide-sidebar-toggle--${side}`).evaluate((el) => el.click());
    await expect.poll(() => panelClosed(page, side), { timeout: 10_000 }).toBe(true);
  }
  const fiche = page.getByTestId("layer-fiche");
  await clickLatLng(page, 54.8, -15.5);
  await expect(fiche).toContainText("Pertuis Charentais");
  const box = () => fiche.evaluate((el) => {
    const css = getComputedStyle(el);
    return {
      overflowY: css.overflowY,
      maxHeight: css.maxHeight,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      scrollTop: el.scrollTop,
    };
  });
  const before = await box();
  expect(before.overflowY).toBe("auto");
  expect(before.maxHeight).not.toBe("none");
  expect(before.scrollHeight, "the card is taller than its box").toBeGreaterThan(before.clientHeight);
  const bar = page.getByTestId("film-bar");
  const ficheBox = await fiche.boundingBox();
  const barBox = await bar.boundingBox();
  expect(ficheBox.y).toBeGreaterThanOrEqual(0);
  expect(ficheBox.y + ficheBox.height, "the card never covers the bar").toBeLessThanOrEqual(barBox.y + 0.5);
  // The wheel scrolls the card, not the map, and reaches its last link.
  await fiche.hover();
  await page.mouse.wheel(0, 400);
  await expect.poll(async () => (await box()).scrollTop).toBeGreaterThan(0);
  const visit = fiche.getByRole("link").last();
  await visit.scrollIntoViewIfNeeded();
  await expect(visit).toBeInViewport();
});
