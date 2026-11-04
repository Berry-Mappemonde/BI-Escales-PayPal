// A server error (500) or a network failure on /route draws nothing: no
// straight line across France, the point stays without a leg, and a message
// says why — in French and in English.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer } from "../helpers.js";

const LA_ROCHELLE = { lat: 46.15, lon: -1.25 };
const GULF_OF_LION = { lat: 43.0, lon: 4.0 };

const MESSAGES = {
  fr: { server: "Erreur du serveur de route : jambe non calculée, réessayez", network: "Réseau indisponible : jambe non calculée, réessayez" },
  en: { server: "Route server error: leg not computed, try again", network: "Network unavailable: leg not computed, try again" },
};

function ends(url) {
  const q = new URL(url).searchParams;
  return { s: [Number(q.get("start_lon")), Number(q.get("start_lat"))], e: [Number(q.get("end_lon")), Number(q.get("end_lat"))] };
}

async function open(page, lang, failure) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await page.route("**/route?*", async (route) => {
    const { s, e } = ends(route.request().url());
    // The first point's probe (same start and end) answers normally.
    if (s[0] === e[0] && s[1] === e[1]) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ type: "Feature", geometry: { type: "LineString", coordinates: [s, e] }, properties: { length: 0, units: "km" } }) });
      return;
    }
    if (failure === "network") {
      await route.abort("failed");
      return;
    }
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal Server Error" }) });
  });
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
}

// Lines the drawing could paint on the map (a routed leg is green; the old
// fallback chord was orange and dashed), read from Leaflet itself.
function drawnLines(page) {
  return page.evaluate(() => {
    let n = 0;
    window.__naviguideScene.map.eachLayer((layer) => {
      if (typeof layer.getLatLngs !== "function" || typeof layer.getLatLng === "function") return;
      const o = layer.options || {};
      if (o.color === "#22c55e" || o.color === "#f97316" || o.dashArray === "6 6") n += 1;
    });
    return n;
  });
}

for (const lang of ["fr", "en"]) {
  for (const failure of ["server", "network"]) {
    test(`${lang}: ${failure === "server" ? "a 500" : "a network abort"} draws no line and says why`, async ({ page }) => {
      test.setTimeout(90_000);
      await open(page, lang, failure);
      const before = await drawnLines(page);
      await page.evaluate(async ({ a, b }) => {
        await window.__naviguideAddDrawnPoint(a.lat, a.lon);
        await window.__naviguideAddDrawnPoint(b.lat, b.lon);
      }, { a: LA_ROCHELLE, b: GULF_OF_LION });

      await expect(page.getByTestId("route-import-error")).toHaveText(MESSAGES[lang][failure], { timeout: 10_000 });
      const state = await page.evaluate(() => ({
        points: window.__naviguideDrawn.points.length,
        legs: window.__naviguideDrawn.segments.length,
        coords: window.__naviguideDrawn.coords.length,
      }));
      expect(state).toEqual({ points: 2, legs: 0, coords: 0 });
      expect(await drawnLines(page)).toBe(before);
      await expect(page.getByText(/corde temporaire|temporary rhumb line/)).toHaveCount(0);
      await expect(page.getByTestId("drawing-summary")).not.toContainText(/[1-9]\d* nm/);
    });
  }
}
