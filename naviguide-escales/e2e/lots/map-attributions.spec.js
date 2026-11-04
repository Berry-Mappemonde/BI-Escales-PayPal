// Crédits des tuiles : OpenStreetMap reste affiché, OpenSeaMap seulement
// tant que le calque est actif. Les serveurs de tuiles sont simulés.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

const TILE_URL = /arcgisonline\.com|openseamap\.org|emodnet|geoserver|\/proxy\/seamark\/|\/proxy\/zee\/wms/i;

async function panelClosed(page, side) {
  const loc = side === "left"
    ? page.locator(".naviguide-sidebar-panel.left-0").first()
    : page.locator(".naviguide-sidebar-panel.right-0").first();
  return loc.evaluate((el) => el.className.includes("translate-x-full"));
}

async function setTools(page, open) {
  if (await panelClosed(page, "right") !== !open) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
  }
  await expect.poll(() => panelClosed(page, "right"), { timeout: 10_000 }).toBe(!open);
}

async function setSidebar(page, open) {
  if (await panelClosed(page, "left") !== !open) {
    await page.locator(".naviguide-sidebar-toggle--left").evaluate((el) => el.click());
  }
  await expect.poll(() => panelClosed(page, "left"), { timeout: 10_000 }).toBe(!open);
}

function creditBand(page) {
  return page.evaluate(() => {
    const attr = document.querySelector(".leaflet-control-attribution");
    if (!attr) return null;
    const r = attr.getBoundingClientRect();
    return { top: r.top, height: r.height, width: r.width };
  });
}

function creditLayout(page, needle) {
  return page.evaluate((needle) => {
    const attr = document.querySelector(".leaflet-control-attribution");
    const zoom = document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    if (!attr) return { ok: false, reason: "contrôle absent" };
    const walker = document.createTreeWalker(attr, NodeFilter.SHOW_TEXT);
    let node = null;
    let found = null;
    while ((node = walker.nextNode())) {
      const text = node.textContent || "";
      const at = text.indexOf(needle);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + needle.length);
      found = range;
      break;
    }
    if (!found) return { ok: false, reason: "texte absent", text: attr.textContent || "" };
    const rects = [...found.getClientRects()];
    const box = attr.getBoundingClientRect();
    const z = zoom?.getBoundingClientRect();
    const overlaps = (r) => Boolean(
      z && r.right > z.left + 1 && r.left < z.right - 1 && r.bottom > z.top + 1 && r.top < z.bottom - 1,
    );
    const onScreen = rects.length > 0 && rects.every((r) => (
      r.width > 0.5 && r.height > 0.5
      && r.left >= -1 && r.top >= -1
      && r.right <= window.innerWidth + 1
      && r.bottom <= window.innerHeight + 1
      && r.left >= box.left - 1 && r.right <= box.right + 1
      && r.top >= box.top - 1 && r.bottom <= box.bottom + 1
      && !overlaps(r)
    ));
    return {
      ok: onScreen,
      reason: onScreen ? "ok" : "hors cadre ou sous le zoom",
      n: rects.length,
      text: (attr.textContent || "").replace(/\s+/g, " ").trim(),
    };
  }, needle);
}

test("OpenSeaMap s'affiche avec le calque, OpenStreetMap reste", async ({ page }) => {
  test.setTimeout(60_000);
  await page.route(TILE_URL, (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: PNG,
  }));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await leaveCinema(page);

  const attr = page.locator(".leaflet-control-attribution");
  const osm = attr.locator('a[href="https://www.openstreetmap.org/copyright"]');
  await expect(osm).toBeVisible();
  await expect(osm).toHaveText("OpenStreetMap contributors");
  await expect.poll(() => creditLayout(page, "OpenStreetMap contributors")).toMatchObject({ ok: true });

  await setTools(page, true);
  const drawer = page.getByTestId("layers-drawer");
  const balisage = page.getByTestId("layer-balisage");
  if (!(await balisage.isVisible().catch(() => false))) {
    await drawer.locator("summary").click();
  }
  await expect(balisage).toBeVisible();
  await balisage.click();
  const modal = page.getByTestId("not-for-nav-modal");
  if (await modal.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await page.getByTestId("not-for-nav-ack").check();
    await page.getByTestId("not-for-nav-accept").click();
  }
  await expect(balisage).toHaveAttribute("aria-pressed", "true");
  await setTools(page, false);

  await expect(attr).toContainText("© OpenSeaMap contributors");
  await expect.poll(() => creditLayout(page, "© OpenSeaMap contributors")).toMatchObject({ ok: true });
  await expect.poll(() => creditLayout(page, "OpenStreetMap contributors")).toMatchObject({ ok: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await setSidebar(page, true);
  await expect.poll(async () => {
    const band = await creditBand(page);
    return Boolean(band && band.top >= 0 && band.height <= 120);
  }, { message: "bande de crédits dans l'écran, hauteur bornée, panneau gauche ouvert" }).toBe(true);
  await setSidebar(page, false);
  await expect.poll(() => creditLayout(page, "© OpenSeaMap contributors")).toMatchObject({ ok: true });
  await expect.poll(() => creditLayout(page, "OpenStreetMap contributors")).toMatchObject({ ok: true });

  await page.setViewportSize({ width: 1280, height: 800 });
  await setTools(page, true);
  await balisage.click();
  await expect(balisage).toHaveAttribute("aria-pressed", "false");
  await setTools(page, false);

  await expect(attr).not.toContainText("OpenSeaMap");
  await expect(osm).toBeVisible();
  await expect.poll(() => creditLayout(page, "OpenStreetMap contributors")).toMatchObject({ ok: true });
});

const ALL_CREDITS = [
  "OpenStreetMap contributors",
  "© OpenSeaMap contributors",
  "EMODnet Bathymetry Consortium",
  "EMODnet Geology",
  "EMODnet Human Activities",
  "Flanders Marine Institute (VLIZ)",
  "Marine Regions",
];

async function layerOn(page, key) {
  const btn = page.getByTestId(`layer-${key}`);
  await expect(btn).toBeVisible();
  if ((await btn.getAttribute("aria-pressed")) !== "true") await btn.click();
  const modal = page.getByTestId("not-for-nav-modal");
  if (await modal.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await page.getByTestId("not-for-nav-ack").check();
    await page.getByTestId("not-for-nav-accept").click();
  }
  await expect(btn).toHaveAttribute("aria-pressed", "true");
}

/** Credit button or bar and zoom: inside the visible map, never under an open panel. */
function cornerLayout(page) {
  return page.evaluate(() => {
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    };
    const panel = (side) => {
      const el = document.querySelector(`.naviguide-sidebar-panel.${side}-0`);
      if (!el || el.className.includes("translate-x-full")) return null;
      return box(el);
    };
    const leftPanel = panel("left");
    const rightPanel = panel("right");
    const minX = leftPanel ? leftPanel.right : 0;
    const maxX = rightPanel ? rightPanel.left : window.innerWidth;
    const map = document.querySelector(".leaflet-container");
    const compact = Boolean(map?.classList.contains("naviguide-attrib-compact"));
    const credits = compact
      ? box(document.querySelector('[data-testid="attribution-toggle"]'))
      : box(document.querySelector(".leaflet-control-attribution"));
    const zoom = box(document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom"));
    const inside = (r) => Boolean(r && r.width > 0.5 && r.height > 0.5
      && r.left >= minX - 1 && r.right <= maxX + 1
      && r.top >= -1 && r.bottom <= window.innerHeight + 1);
    const onScreen = (r) => Boolean(r && r.width > 0.5
      && r.left >= -1 && r.right <= window.innerWidth + 1
      && r.top >= -1 && r.bottom <= window.innerHeight + 1);
    return {
      compact,
      creditsInside: inside(credits),
      zoomInside: inside(zoom),
      zoomOnScreen: onScreen(zoom),
      minX,
      maxX,
      credits,
      zoom,
    };
  });
}

/** One credit inside the open popover: on screen, inside the box, not clipped. */
function popoverCredit(page, needle) {
  return page.evaluate((needle) => {
    const pop = document.querySelector('[data-testid="attribution-popover"]');
    if (!pop || pop.hidden) return { ok: false, reason: "fermé" };
    const walker = document.createTreeWalker(pop, NodeFilter.SHOW_TEXT);
    let node = null;
    let range = null;
    let all = "";
    while ((node = walker.nextNode())) all += node.textContent || "";
    const flat = all.replace(/\s+/g, " ");
    const walker2 = document.createTreeWalker(pop, NodeFilter.SHOW_TEXT);
    while ((node = walker2.nextNode())) {
      const at = (node.textContent || "").indexOf(needle);
      if (at < 0) continue;
      range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + needle.length);
      break;
    }
    if (!range) return { ok: false, reason: "texte absent", text: flat };
    const b = pop.getBoundingClientRect();
    const rects = [...range.getClientRects()];
    const ok = rects.length > 0
      && pop.scrollHeight <= pop.clientHeight + 1
      && pop.scrollWidth <= pop.clientWidth + 1
      && rects.every((r) => r.width > 0.5
        && r.left >= Math.max(0, b.left) - 1 && r.right <= Math.min(window.innerWidth, b.right) + 1
        && r.top >= Math.max(0, b.top) - 1 && r.bottom <= Math.min(window.innerHeight, b.bottom) + 1);
    return { ok, reason: ok ? "ok" : "tronqué ou hors écran", text: flat };
  }, needle);
}

test("390 px, cinq couches : bouton ou bande dans la carte visible, crédits complets", async ({ page }) => {
  test.setTimeout(90_000);
  await page.route(TILE_URL, (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: PNG,
  }));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await leaveCinema(page);

  await setTools(page, true);
  const drawer = page.getByTestId("layers-drawer");
  if (!(await page.getByTestId("layer-balisage").isVisible().catch(() => false))) {
    await drawer.locator("summary").click();
  }
  for (const key of ["balisage", "bathymetry", "fonds", "cables", "zee"]) await layerOn(page, key);
  await setTools(page, false);
  await page.setViewportSize({ width: 390, height: 844 });

  const cases = [
    { name: "panneau gauche ouvert", left: true, tools: false, compact: true },
    { name: "panneau outils ouvert", left: false, tools: true, compact: true },
    { name: "deux panneaux fermés", left: false, tools: false, compact: false },
  ];
  for (const c of cases) {
    await setSidebar(page, c.left);
    await setTools(page, c.tools);
    await expect.poll(() => cornerLayout(page), { message: `${c.name} : coin des crédits` }).toMatchObject({
      compact: c.compact,
      creditsInside: true,
      zoomInside: true,
      zoomOnScreen: true,
    });
    if (c.compact) {
      const toggle = page.getByTestId("attribution-toggle");
      await toggle.click();
      await expect(page.getByTestId("attribution-popover")).toBeVisible();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      for (const needle of ALL_CREDITS) {
        await expect.poll(() => popoverCredit(page, needle), { message: `${c.name} : ${needle}` }).toMatchObject({ ok: true });
      }
      const text = await page.getByTestId("attribution-popover-text").innerText();
      expect(text, `${c.name} : espaces gardés`).not.toMatch(/©\S|\S\(CC-BY|Leaflet\||\|Tuiles/);
      await page.getByTestId("attribution-close").click();
      await expect(page.getByTestId("attribution-popover")).toBeHidden();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
    } else {
      for (const needle of ALL_CREDITS) {
        await expect.poll(() => creditLayout(page, needle), { message: `${c.name} : ${needle}` }).toMatchObject({ ok: true });
      }
      const band = page.locator(".leaflet-control-attribution");
      const text = await band.innerText();
      expect(text, `${c.name} : espaces gardés`).not.toMatch(/©\S|\S\(CC-BY|Leaflet\||\|Tuiles/);
      const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
      expect(lines.some((line) => line.startsWith(",")), `${c.name} : aucune ligne ne commence par une virgule`).toBe(false);
    }
  }
});
