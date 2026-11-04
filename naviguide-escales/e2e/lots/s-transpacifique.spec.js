// Route dessinée Brisbane → San Francisco dans le Pacifique.
// La jambe vient toujours de /route (aucune corde de repli) : sommet ≤ 50° N,
// pas de saut de 360°, distance du résumé entre 6 000 et 7 500 nm. Sans jambe
// (serveur occupé, erreur, searoute absent) : échec avec PW_WITH_API=1, sinon
// test.skip avec la raison — jamais réussi sans avoir vérifié la distance.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-s/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const BRISBANE = { lat: -27.0, lon: 153.4 };
// SF (−122,4) sur la copie-monde +360 : c'est la lon dépliée envoyée avant le lot S.
const SAN_FRANCISCO_UNFOLDED = { lat: 37.7, lon: 237.6 };

async function clickLatLng(page, lat, lon) {
  // Même chemin que le clic carte (handleDrawingClick → addPoint).
  // map.fire('click') ne transmet pas toujours latlng jusqu'au handler Leaflet.
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => {
    window.__naviguideAddDrawnPoint(lat, lon);
  }, { lat, lon });
}

function parseNm(text) {
  const matches = [...String(text || "").matchAll(/(\d[\d\s\u00a0\u202f.,]*)\s*nm/gi)];
  if (!matches.length) return null;
  const raw = matches[matches.length - 1][1].replace(/[\s\u00a0\u202f,]/g, "");
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

test("Tracer Brisbane → SF : aucun sommet au nord de 50° N", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 12_000 });

  const { enterTracer } = await import("../helpers.js");
  await enterTracer(page);

  const tools = page.getByTestId("drawing-summary");
  if (!(await tools.isVisible().catch(() => false))) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
  }
  await expect(page.getByTestId("drawing-summary")).toBeVisible({ timeout: 10_000 });

  // « Server busy » is told apart from « no searoute » by the answer itself.
  let busyAnswers = 0;
  // A server error (500, 502) is an answer too: the leg will not come.
  let errorAnswers = 0;
  let lastError = 0;
  page.on("response", (res) => {
    if (!res.url().includes("/route?")) return;
    if (res.status() === 503) busyAnswers += 1;
    else if (res.status() === 500 || res.status() === 502) {
      errorAnswers += 1;
      lastError = res.status();
    }
  });
  await clickLatLng(page, BRISBANE.lat, BRISBANE.lon);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, null, { timeout: 10_000 });
  await clickLatLng(page, SAN_FRANCISCO_UNFOLDED.lat, SAN_FRANCISCO_UNFOLDED.lon);
  // Wait for the server's answer itself: a leg, or a 503. Under load the 503
  // can land after the 12 s deadline (ROUTE_DEADLINE_S) plus the queue in
  // front of it — a fixed wait could give up before it and skip the retry.
  const legShown = async () => {
    const busyBefore = busyAnswers;
    const errorsBefore = errorAnswers;
    const deadline = Date.now() + 45_000;
    while (Date.now() < deadline) {
      const legs = await page.evaluate(() => window.__naviguideDrawn?.segments?.length || 0);
      if (legs >= 1) return true;
      if (busyAnswers > busyBefore || errorAnswers > errorsBefore) return false;
      await page.waitForTimeout(250);
    }
    return false;
  };
  const busyShown = () => page.getByText(/Serveur occupé|Server busy/).first().isVisible().catch(() => false);
  let gotSeg = await legShown();

  // A busy server (other routes computed in parallel) says « try again » and
  // keeps the point: do what the reader would, undo it and click again.
  const undo = page.getByTitle(/Annuler le dernier point|Undo last point/).filter({ hasText: "↶" });
  for (let attempt = 0; !gotSeg && attempt < 3; attempt += 1) {
    if (!busyAnswers && !(await busyShown())) break;
    await undo.click();
    await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1, null, { timeout: 5_000 });
    await clickLatLng(page, SAN_FRANCISCO_UNFOLDED.lat, SAN_FRANCISCO_UNFOLDED.lon);
    gotSeg = await legShown();
  }
  if (!gotSeg) {
    // No leg was routed: the point stays, and nothing is drawn in its place.
    const state = await page.evaluate(() => ({
      points: window.__naviguideDrawn?.points?.length || 0,
      legs: window.__naviguideDrawn?.segments?.length || 0,
    }));
    expect(state).toEqual({ points: 2, legs: 0 });
    // The message is cleared after 4 s (App.jsx): read it if it is there, never wait for it.
    const errorText = (await page.getByTestId("route-import-error").textContent({ timeout: 1000 }).catch(() => "")) || "";
    const reason = busyAnswers > 0
      ? `serveur occupé : /route a répondu 503 busy ${busyAnswers} fois (échéance atteinte)`
      : errorAnswers > 0
        ? `jambe en échec : /route a répondu ${lastError}${errorText ? ` — ${errorText}` : ""}`
        : errorText
          ? `jambe en échec : ${errorText}`
          : "searoute absent (ou interdit sur ce poste) : aucune jambe Brisbane→SF";
    await shot(page, "01-sans-jambe").catch(() => {});
    // With the API the distance must be checked: no leg is a failure. Without
    // it, the test is skipped — never passed without checking the distance.
    expect(process.env.PW_WITH_API !== "1", `distance non vérifiée avec l'API — ${reason}`).toBe(true);
    test.skip(true, reason);
  }

  const info = await page.evaluate(() => {
    const drawn = window.__naviguideDrawn || {};
    const sceneSegs = window.__naviguideScene?.routeInputs?.drawnSegments || [];
    const segs = drawn.segments?.length ? drawn.segments : sceneSegs;
    const coords = drawn.coords?.length
      ? drawn.coords
      : segs.flatMap((s) => s.coords || []);
    const lats = coords.map((c) => c[1]).filter((lat) => Number.isFinite(lat));
    const lons = coords.map((c) => c[0]);
    let jump = 0;
    for (let i = 1; i < lons.length; i++) jump = Math.max(jump, Math.abs(lons[i] - lons[i - 1]));
    return {
      n: coords.length,
      maxLat: lats.length ? Math.max(...lats) : null,
      jump,
      points: drawn.points || [],
    };
  });

  expect(info.points.length).toBeGreaterThanOrEqual(2);
  expect(info.points[0].lat).toBeCloseTo(BRISBANE.lat, 1);
  expect(info.points[0].lon).toBeCloseTo(BRISBANE.lon, 1);
  expect(info.points[1].lat).toBeCloseTo(SAN_FRANCISCO_UNFOLDED.lat, 1);
  expect(info.points[1].lon).toBeCloseTo(SAN_FRANCISCO_UNFOLDED.lon, 1);
  expect(info.n).toBeGreaterThanOrEqual(2);
  expect(info.maxLat).not.toBeNull();
  expect(info.maxLat).toBeLessThanOrEqual(50);
  expect(info.jump).toBeLessThanOrEqual(180);

  const summary = await page.getByTestId("drawing-summary").innerText();
  const nm = parseNm(summary);
  expect(nm, `résumé: ${summary}`).not.toBeNull();
  expect(nm).toBeGreaterThanOrEqual(6000);
  expect(nm).toBeLessThanOrEqual(7500);

  await page.evaluate(({ a, b }) => {
    const map = window.__naviguideScene?.map;
    if (!map) return;
    map.fitBounds([[a.lat, a.lon], [b.lat, b.lon]], {
      animate: false,
      padding: [56, 56],
      maxZoom: 3,
    });
  }, { a: BRISBANE, b: SAN_FRANCISCO_UNFOLDED });
  await page.waitForTimeout(600);
  await shot(page, "01-pacifique");
});
