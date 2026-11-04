// Carte au dézoom : drapeaux et bateaux plantés, un seul monde.
// Sans API : plancher de dézoom, Tracer et les drapeaux ITINERARY_POINTS tiennent
// seuls. GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions film / bateau live — jamais le plancher ni la stabilité des drapeaux.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  dismissNotForNav,
  enterSimulation,
  enterTracer,
  leaveCinema,
  probeOfficial,
  waitFilmCanStart,
} from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg15");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const WALLIS = { name: "Mata-Utu (Wallis-et-Futuna)", lat: -13.2725, lon: -176.2036 };
const FDF = { name: "Fort-de-France (Martinique)", lat: 14.5887, lon: -61.0731 };
const PX_TOL = 0.5;

async function waitMap(page) {
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 20_000 });
}

async function setView(page, lat, lon, zoom) {
  await page.evaluate(([la, lo, z]) => {
    const map = window.__naviguideScene.map;
    map.setView([la, lo], z, { animate: false });
  }, [lat, lon, zoom]);
  await page.waitForTimeout(80);
}

async function zoomSteps(page, n, dir) {
  await page.evaluate(async ([count, sign]) => {
    const map = window.__naviguideScene.map;
    for (let i = 0; i < count; i += 1) {
      const before = map.getZoom();
      await new Promise((resolve) => {
        const done = () => {
          map.off("zoomend", done);
          resolve();
        };
        map.on("zoomend", done);
        if (sign > 0) map.zoomIn(1, { animate: false });
        else map.zoomOut(1, { animate: false });
        if (Math.abs(map.getZoom() - before) < 1e-6) {
          map.off("zoomend", done);
          resolve();
        }
      });
    }
  }, [n, dir]);
}

async function wheelNotches(page, n, deltaY) {
  const box = await page.locator(".leaflet-container").boundingBox();
  expect(box).toBeTruthy();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < n; i += 1) await page.mouse.wheel(0, deltaY);
  await page.waitForTimeout(120);
}

async function clickZoomButtons(page, n, which) {
  const sel = which === "in" ? ".leaflet-control-zoom-in" : ".leaflet-control-zoom-out";
  for (let i = 0; i < n; i += 1) {
    await page.locator(sel).click({ force: true });
    await page.waitForTimeout(40);
  }
  await page.waitForTimeout(80);
}

async function readAnchors(page, names) {
  return page.evaluate((want) => {
    const map = window.__naviguideScene?.map;
    const scene = window.__naviguideScene;
    if (!map || !scene) return { ok: false, flags: [], boats: [] };
    const flags = [];
    for (const marker of scene.waypointMarkers?.values?.() || []) {
      const point = marker._naviguideWaypoint;
      const ll = marker.getLatLng?.();
      if (!point?.name || !ll) continue;
      if (want.length && !want.some((n) => point.name.includes(n))) continue;
      const wrap = (x) => {
        let v = Number(x);
        while (v > 180) v -= 360;
        while (v < -180) v += 360;
        return v;
      };
      const wrapKey = Math.round((ll.lng - wrap(point.lon)) / 360);
      const planted = map.latLngToContainerPoint([point.lat, wrap(point.lon) + wrapKey * 360]);
      const actual = map.latLngToContainerPoint(ll);
      flags.push({
        name: point.name,
        wrap: wrapKey,
        lon: ll.lng,
        lat: ll.lat,
        lonErr: Math.abs(wrap(ll.lng) - wrap(point.lon)),
        dx: actual.x - planted.x,
        dy: actual.y - planted.y,
        sx: actual.x,
        sy: actual.y,
      });
    }
    const boats = [];
    for (const markers of scene.markerSets?.values?.() || []) {
      for (const marker of markers || []) {
        const ll = marker.getLatLng?.();
        if (!ll) continue;
        const pt = map.latLngToContainerPoint(ll);
        boats.push({ lat: ll.lat, lon: ll.lng, sx: pt.x, sy: pt.y });
      }
    }
    const size = map.getSize();
    const zoom = map.getZoom();
    return {
      ok: true,
      flags,
      boats,
      zoom,
      minZoom: map.getMinZoom(),
      worldW: 256 * 2 ** zoom,
      screenW: size.x,
      screenH: size.y,
    };
  }, names);
}

function flagDrift(before, after, namePart) {
  const a = before.flags.find((f) => f.name.includes(namePart));
  const b = after.flags.find((f) => f.name.includes(namePart));
  if (!a || !b) return { ok: false, missing: true };
  return {
    ok: true,
    wrapJump: a.wrap !== b.wrap,
    dLon: Math.abs(((b.lon - a.lon + 540) % 360) - 180),
    pixel: Math.hypot(b.dx - a.dx, b.dy - a.dy),
    geoPx: Math.hypot(b.dx, b.dy),
  };
}

function boatDrift(before, after) {
  if (!before.boats.length || !after.boats.length) return { ok: false };
  const a = before.boats[0];
  const b = after.boats[0];
  return {
    ok: true,
    dLat: Math.abs(b.lat - a.lat),
    dLon: Math.abs(((b.lon - a.lon + 540) % 360) - 180),
  };
}

async function assertFlagPlanted(page, stop, label) {
  const snap = await readAnchors(page, [stop.name.split(" ")[0]]);
  const flag = snap.flags.find((f) => f.name.includes(stop.name.split(" ")[0]));
  expect(flag, `${label} : drapeau ${stop.name}`).toBeTruthy();
  expect(flag.lonErr, `${label} : lon ${flag.lonErr}`).toBeLessThan(1e-3);
  expect(Math.hypot(flag.dx, flag.dy), `${label} : ancre ${flag.dx},${flag.dy}`).toBeLessThanOrEqual(PX_TOL);
}

async function zoomCycleOver(page, stop) {
  await setView(page, stop.lat, stop.lon, 6);
  await assertFlagPlanted(page, stop, "avant cycle");
  const before = await readAnchors(page, [stop.name.split(" ")[0]]);
  await zoomSteps(page, 10, 1);
  await zoomSteps(page, 10, -1);
  await wheelNotches(page, 4, -80);
  await wheelNotches(page, 4, 80);
  await clickZoomButtons(page, 2, "in");
  await clickZoomButtons(page, 2, "out");
  const after = await readAnchors(page, [stop.name.split(" ")[0]]);
  const drift = flagDrift(before, after, stop.name.split(" ")[0]);
  expect(drift.ok, `${stop.name} drapeau encore là`).toBeTruthy();
  expect(drift.wrapJump, `${stop.name} copie monde a sauté`).toBeFalsy();
  expect(drift.geoPx, `${stop.name} ancre ${drift.geoPx} px`).toBeLessThanOrEqual(PX_TOL);
  if (before.boats.length && after.boats.length) {
    expect(
      Math.abs(after.boats[0].lon - before.boats[0].lon),
      `${stop.name} bateau saut 360°`,
    ).toBeLessThan(300);
  }
  return after;
}

async function assertOneWorld(page, label) {
  await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    const z = map.getMinZoom();
    map.setView([22, 5], z, { animate: false });
  });
  await page.waitForTimeout(200);
  const snap = await readAnchors(page, []);
  expect(snap.worldW, `${label} : monde ${snap.worldW} px < écran ${snap.screenW}`).toBeGreaterThanOrEqual(snap.screenW - 1);
  return snap;
}

test("Drapeaux plantés, un seul monde", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await probeOfficial(page);
  const apiUp = Boolean(official);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — film et bateau live sautés ; plancher et drapeaux gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await waitMap(page);

  const flagsReady = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    return Boolean(scene?.waypointMarkers?.size);
  }, null, { timeout: 15_000 }).then(() => true).catch(() => false);

  if (flagsReady) {
    await setView(page, WALLIS.lat, WALLIS.lon, 6);
    await page.waitForTimeout(300);
    await shot(page, "01-wallis-zoom");
    await zoomCycleOver(page, WALLIS);
    await zoomCycleOver(page, FDF);
  } else {
    test.info().annotations.push({
      type: "sans drapeaux",
      description: "waypointMarkers vides — cycle Wallis / Fort-de-France sauté ; plancher gardé",
    });
    await setView(page, WALLIS.lat, WALLIS.lon, 6);
    await shot(page, "01-wallis-zoom");
  }

  const followWorld = await assertOneWorld(page, "Suivre");
  expect(followWorld.minZoom, "plancher Suivre").toBeGreaterThanOrEqual(2);
  await shot(page, "02-dezoom-max");

  await enterSimulation(page);
  await waitMap(page);
  await assertOneWorld(page, "Simulation");

  await enterTracer(page);
  await waitMap(page);
  const tracer = await assertOneWorld(page, "Tracer");
  expect(tracer.minZoom, "plancher Tracer").toBeGreaterThanOrEqual(2);
  expect(tracer.zoom, "Tracer monde entier").toBeLessThanOrEqual(3);

  if (!apiUp) return;

  const cancelDraw = page.getByRole("button", { name: /^(annuler|cancel)$/i });
  if (await cancelDraw.isVisible().catch(() => false)) await cancelDraw.click();
  await leaveCinema(page);
  const followBtn = page.getByTestId("view-suivre");
  if (!(await followBtn.isVisible({ timeout: 5_000 }).catch(() => false))) {
    test.info().annotations.push({
      type: "film",
      description: "Suivre inaccessible après Tracer — zoom pendant le film sauté",
    });
    return;
  }
  await followBtn.click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const canPlay = await waitFilmCanStart(page, 15_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — zoom pendant le film sauté",
    });
    return;
  }
  await page.getByTestId("replay-start").click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await waitMap(page);
  const beforeFilm = await readAnchors(page, ["Mata-Utu", "Fort-de-France", "La Rochelle"]);
  await wheelNotches(page, 6, -80);
  await wheelNotches(page, 6, 80);
  const afterFilm = await readAnchors(page, ["Mata-Utu", "Fort-de-France", "La Rochelle"]);
  for (const part of ["Mata-Utu", "Fort-de-France", "La Rochelle"]) {
    const a = beforeFilm.flags.find((f) => f.name.includes(part));
    const b = afterFilm.flags.find((f) => f.name.includes(part));
    if (!a || !b) continue;
    expect(a.wrap === b.wrap, `film ${part} copie monde`).toBeTruthy();
    expect(Math.hypot(b.dx, b.dy), `film ${part} ancre`).toBeLessThanOrEqual(PX_TOL);
  }
  if (beforeFilm.boats.length && afterFilm.boats.length) {
    const boat = boatDrift(beforeFilm, afterFilm);
    expect(boat.dLon, "film bateau wrap").toBeLessThan(2);
  }
});
