// ↶ pendant le calcul d'une jambe (réponse /route retenue jusqu'à ce que le test la libère) : la page reste affichée,
// la console reste propre, la réponse tardive est ignorée, aucun trou de jambe.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer } from "../helpers.js";

// Each /route answer is held until the test releases it: the ↶ always lands
// while the leg is being computed, however loaded the machine is.
const SETTLE_MS = 500;
const A = { lat: 46.0, lon: -2.5, name: "A" };
const B = { lat: 44.5, lon: -4.0, name: "B" };
const C = { lat: 43.8, lon: -8.5, name: "C" };
const D = { lat: 42.0, lon: -10.0, name: "D" };
const NAMES = [A, B, C, D];

function nameAt(lat, lon) {
  return NAMES.find((p) => Math.abs(p.lat - lat) < 1e-6 && Math.abs(p.lon - lon) < 1e-6)?.name || "?";
}

async function heldRoute(page) {
  const held = [];
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    let open;
    const gate = new Promise((resolve) => { open = resolve; });
    const entry = { leg: `${nameAt(slat, slon)}-${nameAt(elat, elon)}`, released: false, open, seq: held.length };
    // Each answer is told apart by its middle vertex (one per request).
    const midLat = (slat + elat) / 2 + entry.seq * 0.01;
    entry.done = gate.then(() => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [(slon + elon) / 2, midLat], [elon, elat]] },
        properties: { length: 185.2, units: "km" },
      }),
    }).catch(() => {}));
    held.push(entry);
  });
  const find = (leg) => held.find((e) => e.leg === leg && !e.released);
  return {
    // The request for this leg has reached the server (it is pending).
    async arrived(leg) {
      await expect.poll(() => Boolean(find(leg)), { timeout: 30_000, message: `request ${leg}` }).toBe(true);
    },
    // Let its answer go and wait until it has been delivered; returns the
    // request number (its answer's middle vertex is offset by seq × 0.01°).
    async release(leg) {
      await this.arrived(leg);
      const entry = find(leg);
      entry.released = true;
      entry.open();
      await entry.done;
      return entry.seq;
    },
  };
}

function drawn(page) {
  return page.evaluate(() => {
    const d = window.__naviguideDrawn || { points: [], segments: [] };
    return {
      names: d.points.map((p) => p.name),
      legs: d.segments.map((s) => (s ? `${s.from?.name}-${s.to?.name}` : null)),
    };
  });
}

async function add(page, p) {
  await page.evaluate((q) => { window.__naviguideAddDrawnPoint(q.lat, q.lon, { name: q.name }); }, p);
}

test("↶ pendant le calcul d'une jambe ne vide pas la page", async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    // Tuiles ou ressources hors ligne : bruit réseau, pas une erreur de l'application.
    if (/Failed to load resource/i.test(text)) return;
    consoleErrors.push(text);
  });
  const server = await heldRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  // Le ↶ du cadre de tracé (la pilule du haut porte le même titre).
  const undo = page.getByTitle(/Annuler le dernier point|Undo last point/).filter({ hasText: "↶" });

  // 1) ↶ pendant la toute première jambe.
  await add(page, A);
  await add(page, B);
  await server.arrived("A-B");
  await undo.click();
  await expect.poll(() => drawn(page), { timeout: 15_000 }).toEqual({ names: ["A"], legs: [] });
  await server.release("A-B");
  await page.waitForTimeout(SETTLE_MS);
  expect(await drawn(page)).toEqual({ names: ["A"], legs: [] });

  // 2) Deux jambes posées, ↶ pendant la deuxième, puis un nouveau point.
  await add(page, B);
  await server.release("A-B");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 1, null, { timeout: 15_000 });
  await add(page, C);
  await server.arrived("B-C");
  await undo.click();
  await expect.poll(() => drawn(page), { timeout: 15_000 }).toEqual({ names: ["A", "B"], legs: ["A-B"] });
  // La réponse tardive B→C arrive : elle est ignorée.
  await server.release("B-C");
  await page.waitForTimeout(SETTLE_MS);
  expect(await drawn(page)).toEqual({ names: ["A", "B"], legs: ["A-B"] });

  await add(page, D);
  await server.release("B-D");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 2, null, { timeout: 15_000 });
  expect(await drawn(page)).toEqual({ names: ["A", "B", "D"], legs: ["A-B", "B-D"] });

  // 3) Rétablir après un ↶ pendant le calcul recalcule la jambe.
  await add(page, C);
  await server.arrived("D-C");
  await undo.click();
  await expect.poll(() => drawn(page), { timeout: 15_000 }).toEqual({ names: ["A", "B", "D"], legs: ["A-B", "B-D"] });
  await page.getByTitle(/^(Rétablir|Redo)$/).click();
  await server.release("D-C");
  await server.release("D-C");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 3, null, { timeout: 15_000 });
  expect(await drawn(page)).toEqual({ names: ["A", "B", "D", "C"], legs: ["A-B", "B-D", "D-C"] });

  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("drawing-box")).toBeVisible();
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("↶ puis D aussitôt : la jambe B-C n'apparaît jamais", async ({ page }) => {
  test.setTimeout(90_000);
  const server = await heldRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  const undo = page.getByTitle(/Annuler le dernier point|Undo last point/).filter({ hasText: "↶" });
  // Toutes les jambes vues pendant le test, image par image.
  await page.evaluate(() => {
    window.__seenLegs = new Set();
    const tick = () => {
      for (const s of window.__naviguideDrawn?.segments || []) {
        if (s) window.__seenLegs.add(`${s.from?.name}-${s.to?.name}`);
      }
      window.__seenLegsRaf = requestAnimationFrame(tick);
    };
    tick();
  });
  await add(page, A);
  await add(page, B);
  await server.release("A-B");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 1, null, { timeout: 15_000 });
  await add(page, C);
  await server.arrived("B-C");
  await undo.click();
  await add(page, D);
  // The late B→C answer comes back after the ↶ and after D: it is never shown.
  await server.release("B-C");
  await server.release("B-D");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 2, null, { timeout: 15_000 });
  await page.waitForTimeout(SETTLE_MS);
  expect(await drawn(page)).toEqual({ names: ["A", "B", "D"], legs: ["A-B", "B-D"] });
  const seen = await page.evaluate(() => [...window.__seenLegs]);
  expect(seen).not.toContain("B-C");
  expect(seen).toContain("B-D");
});

test("↶ then redo while B-C loads: only the new B-C answer is used (slot generation)", async ({ page }) => {
  test.setTimeout(90_000);
  const server = await heldRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  const undo = page.getByTitle(/Annuler le dernier point|Undo last point/).filter({ hasText: "↶" });
  const legBC = () => page.evaluate(() => {
    const s = (window.__naviguideDrawn?.segments || []).find((x) => x?.from?.name === "B" && x?.to?.name === "C");
    return s ? s.coords[1][1] : null;
  });

  await add(page, A);
  await add(page, B);
  await server.release("A-B");
  await page.waitForFunction(() => window.__naviguideDrawn?.segments?.length === 1, null, { timeout: 15_000 });
  await add(page, C);
  await server.arrived("B-C");
  await undo.click();
  await page.getByTitle(/^(Rétablir|Redo)$/).click();
  // Same point C again: the leg is asked once more.
  await expect.poll(() => drawn(page), { timeout: 15_000 }).toEqual({ names: ["A", "B", "C"], legs: ["A-B"] });

  // The answer asked before the ↶ comes back first: it is dropped.
  const oldSeq = await server.release("B-C");
  await page.waitForTimeout(SETTLE_MS);
  expect(await legBC(), "the pre-↶ answer must not be drawn").toBeNull();

  // The answer of the new request is the one drawn.
  const newSeq = await server.release("B-C");
  expect(newSeq).toBeGreaterThan(oldSeq);
  await expect.poll(legBC, { timeout: 15_000 }).not.toBeNull();
  const mid = await legBC();
  expect(mid).toBeCloseTo((B.lat + C.lat) / 2 + newSeq * 0.01, 6);
  expect(await drawn(page)).toEqual({ names: ["A", "B", "C"], legs: ["A-B", "B-C"] });
});
