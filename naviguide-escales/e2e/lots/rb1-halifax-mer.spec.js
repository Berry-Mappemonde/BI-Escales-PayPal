// Halifax ↔ Saint-Pierre est une jambe mer ; avion = Cayenne ↔ Halifax.
// Sans API : geojson local + flatten. Chorégraphie et popup satellite se vérifient seuls.
// GET /voyage/official : seulement si on veut confirmer l'horloge officielle (milles voile).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb1/${name}.webp`,
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

function inspectRoute() {
  const scene = window.__naviguideScene;
  const segs = scene?.routeInputs?.segments || scene?.config?.segments || [];
  const halifaxSpm = segs.filter((s) => {
    const a = `${s.from?.name || ""}|${s.to?.name || ""}`;
    return /halifax/i.test(a) && /saint-pierre|miquelon/i.test(a);
  }).map((s) => ({
    from: s.from?.name,
    to: s.to?.name,
    air: Boolean(s.air),
    n: (s.coords || []).length,
  }));
  const cayenneHalifax = segs.filter((s) => {
    const a = `${s.from?.name || ""}|${s.to?.name || ""}`;
    return /cayenne/i.test(a) && /halifax/i.test(a);
  });
  const map = scene?.map;
  const air = [];
  const nearHalifaxSpm = [];
  if (map?.eachLayer) {
    map.eachLayer((layer) => {
      const opt = layer.options || {};
      if (!layer.getLatLngs || opt.dashArray !== "7 7") return;
      const color = String(opt.color || "").toLowerCase();
      if (color !== "#111111" && color !== "black" && color !== "#111") return;
      const raw = layer.getLatLngs();
      const ll = Array.isArray(raw[0]) ? raw[0] : raw;
      const first = ll[0];
      const last = ll[ll.length - 1];
      if (!first || !last) return;
      const item = {
        interactive: opt.interactive !== false,
        a: { lat: first.lat, lng: first.lng },
        b: { lat: last.lat, lng: last.lng },
      };
      air.push(item);
      const near = (p, lat, lng) => Math.abs(p.lat - lat) < 1.2 && Math.abs(((p.lng + 540) % 360) - 180 - lng) < 1.2;
      const touchesH = near(item.a, 44.65, -63.57) || near(item.b, 44.65, -63.57);
      const touchesS = near(item.a, 46.78, -56.16) || near(item.b, 46.78, -56.16);
      if (touchesH && touchesS) nearHalifaxSpm.push(item);
    });
  }
  const flat = scene?.routeInputs?.flat || scene?.config?.flat;
  const ep = flat?.episodes?.[0];
  return {
    halifaxSpm,
    cayenneHalifaxNamed: cayenneHalifax.length,
    airCount: air.length,
    halifaxSpmAirLines: nearHalifaxSpm.length,
    airInteractive: air.some((l) => l.interactive),
    hasEpisode: Boolean(ep),
    parkLat: ep?.park?.lat ?? null,
    hubLat: ep?.hub?.lat ?? null,
    viaLat: ep?.via?.lat ?? null,
  };
}

test("Halifax ↔ Saint-Pierre mer, chorégraphie Guyane", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — horloge officielle (milles voile) non relue",
    });
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    const segs = scene?.routeInputs?.segments || scene?.config?.segments || [];
    return segs.length > 4;
  }, null, { timeout: 25_000 });

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.fire("dragstart");
    scene.map.setView([45.7, -60], 5, { animate: false });
  });
  await page.waitForTimeout(700);
  await page.waitForFunction(() => document.querySelectorAll(".leaflet-tile-loaded").length > 2, null, { timeout: 12_000 }).catch(() => {});

  const route = await page.evaluate(inspectRoute);
  expect(route.halifaxSpm.length, "jambes Halifax ↔ Saint-Pierre dans le geojson").toBeGreaterThan(0);
  expect(route.halifaxSpm.every((s) => s.air === false), "Halifax ↔ Saint-Pierre n'est pas air").toBeTruthy();
  expect(route.halifaxSpmAirLines, "aucun trait noir pointillé Halifax ↔ Saint-Pierre").toBe(0);
  expect(route.airCount, "jambes avion (Cayenne ↔ Halifax / Pacifique) encore dessinées").toBeGreaterThan(0);
  expect(route.airInteractive, "vraies jambes avion non cliquables").toBeFalsy();

  const click = await page.evaluate(() => {
    const scene = window.__naviguideScene;
    const map = scene.map;
    const segs = scene.routeInputs?.segments || scene.config?.segments || [];
    const sea = segs.find((s) => {
      const a = `${s.from?.name || ""}|${s.to?.name || ""}`;
      return /halifax/i.test(a) && /saint-pierre|miquelon/i.test(a) && s.coords?.length > 1;
    });
    if (!sea) return { ok: false, reason: "no-seg" };
    const mid = sea.coords[Math.floor(sea.coords.length / 2)];
    map.fire("click", { latlng: { lat: mid[1], lng: mid[0] } });
    return { ok: true, lat: mid[1], lon: mid[0] };
  });
  expect(click.ok, "clic sur la jambe mer Halifax ↔ Saint-Pierre").toBeTruthy();
  await expect(page.getByRole("button", { name: /vent|wind/i }).first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByRole("button", { name: /vagues|waves/i }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /courants|currents/i }).first()).toBeVisible();

  await shot(page, "01-halifax-mer");

  if (apiUp) {
    const clock = await page.request.get("/voyage/official/clock", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
    if (clock?.vertices?.length) {
      const planes = clock.vertices.filter((v) => v.vehicle === "plane");
      expect(planes.length, "sauts avion Cayenne ↔ Halifax encore à l'horloge").toBeGreaterThan(0);
      const seaNearSpm = clock.vertices.filter((v) => (
        v.vehicle === "main" && Math.abs((v.lat || 0) - 46.78) < 1.5 && Math.abs((v.lon || 0) + 56.2) < 3
      ));
      expect(seaNearSpm.length, "sommets mer Halifax ↔ Saint-Pierre dans l'horloge figée").toBeGreaterThan(0);
    } else {
      throw new Error("GET /voyage/official/clock vide — milles voile non relus");
    }
  }

  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });

  const cast = await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    const flat = scene.routeInputs?.flat || scene.config?.flat;
    const eps = flat?.episodes || [];
    const ep = eps.find((e) => Math.abs((e.park?.lat || 0) - 4.93) < 1.5) || eps[0];
    if (!ep || !flat?.points) return { ok: false, nEp: eps.length };
    const sideMid = (flat.points[ep.ja].filmCum + flat.points[ep.jb - 1].filmCum) / 2;
    const airOut = (flat.points[ep.ja - 1].filmCum + flat.points[ep.ja].filmCum) / 2;
    scene.playback.pause();
    scene.playback.seek(airOut, { jump: true });
    const out = scene.currentCast;
    scene.playback.seek(sideMid, { jump: true });
    const side = scene.currentCast;
    scene.map.setView([26, -58], 4, { animate: false });
    return {
      ok: true,
      nEp: eps.length,
      parkLat: ep.park?.lat,
      hubLat: ep.hub?.lat,
      viaLat: ep.via?.lat,
      outPhase: out?.phase,
      outMainLat: out?.main?.lat,
      outPlane: Boolean(out?.plane?.visible),
      outSide: Boolean(out?.side?.visible),
      sidePhase: side?.phase,
      sideMainLat: side?.main?.lat,
      sideBoat: Boolean(side?.side?.visible),
      sidePlane: Boolean(side?.plane?.visible),
      sideLat: side?.side?.lat,
    };
  });
  expect(cast.ok, "épisode Guyane présent").toBeTruthy();
  expect(cast.parkLat).toBeGreaterThan(3);
  expect(cast.parkLat).toBeLessThan(8);
  expect(cast.hubLat).toBeGreaterThan(43);
  expect(cast.viaLat).toBeGreaterThan(44);
  expect(cast.outPhase).toBe("air-out");
  expect(cast.outPlane).toBeTruthy();
  expect(cast.outSide).toBeFalsy();
  expect(cast.outMainLat).toBeGreaterThan(3);
  expect(cast.outMainLat).toBeLessThan(8);
  expect(cast.sidePhase).toBe("side-sail");
  expect(cast.sideBoat).toBeTruthy();
  expect(cast.sidePlane).toBeFalsy();
  expect(cast.sideMainLat).toBeGreaterThan(3);
  expect(cast.sideMainLat).toBeLessThan(8);
  expect(cast.sideLat).toBeGreaterThan(43);

  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await shot(page, "02-choregraphie");

  await muteFilmVoice(page);
  await page.getByTestId("replay-start").click();
  await muteFilmVoice(page);
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
});
