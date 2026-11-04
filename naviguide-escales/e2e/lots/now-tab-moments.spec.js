// Now tab in English: one card per fact, Now never repeats Next, the entry
// alert is translated and no card title is a hash.
import { expect, test } from "@playwright/test";

const T0 = "2026-05-15T08:00:00Z";
const JOURNAL_DAYS = ["2026-05-15", "2026-05-16", "2026-05-17", "2026-06-01", "2026-10-17"];

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function clockFromMarks(marks) {
  const list = Array.isArray(marks) ? marks.filter((m) => m && m.name) : [];
  if (list.length < 2) return null;
  let index = list.findIndex((m) => /Nouméa|Mata-Utu|Wallis|Papeete|Tahiti/i.test(m.name));
  if (index < 0 || index >= list.length - 1) {
    index = Math.max(0, Math.min(list.length - 2, Math.floor(list.length * 0.72)));
  }
  const from = list[index];
  const to = list[index + 1];
  const t0ms = Date.parse(T0);
  const nowHours = (Date.now() - t0ms) / 3600000;
  const clockMarks = list.map((m, i) => {
    const hours = i <= index
      ? nowHours * (i / Math.max(1, index)) * 0.98
      : nowHours + (i - index) * 72;
    return {
      ...m,
      iso: new Date(t0ms + hours * 3600000).toISOString(),
      holdHours: i === index ? 0 : 0,
    };
  });
  const vertex = (hours, mark, knots) => ({
    tHours: hours,
    sailNm: Number(mark.nm) || 0,
    filmNm: Number(mark.filmNm ?? mark.nm) || 0,
    lat: mark.lat,
    lon: mark.lon,
    speedKnots: knots,
    bearing: 210,
    vehicle: "main",
    kind: "climatology",
  });
  return {
    fromName: from.name,
    toName: to.name,
    from,
    clock: {
      t0: T0,
      marks: clockMarks,
      vertices: [
        vertex(0, list[0], 6),
        vertex(Math.max(1, nowHours - 24), from, 7.5),
        vertex(nowHours + 400, to, 7.5),
      ],
    },
  };
}

async function dismissNotForNav(page) {
  const ok = page.getByRole("button", { name: /compris|j.ai compris|ok|continuer|accepter|understand|accept/i }).first();
  if (await ok.isVisible({ timeout: 3000 }).catch(() => false)) {
    const ack = page.getByTestId("not-for-nav-ack");
    if (await ack.isVisible().catch(() => false)) await ack.check();
    await ok.click();
  }
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

const SHA = "3f9c2a7be41d08c5a6e2f1b0d9c87a65";

async function routeApi(page, { moment, dossier = null, onMoment = null }) {
  let built = null;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const api = path.includes("/voyage") || path.includes("/ici");
    if (!api) return route.continue();
    if (path.includes("/ici/moment")) {
      if (onMoment) onMoment(url);
      return json(route, moment);
    }
    if (dossier && /\/ici\/?$/.test(path)) {
      return json(route, { ...dossier, at: { lat: Number(url.searchParams.get("lat")), lon: Number(url.searchParams.get("lon")) } });
    }
    if (path.endsWith("/voyage/official/journal")) {
      return json(route, { voyageId: "official", status: "ready", count: 0, days: [], latest: [], events: [] });
    }
    if (path.includes("/voyage/official/moments")) {
      return json(route, { voyageId: "official", status: "ready", count: 0, moments: [] });
    }
    if (path.includes("/voyage/official/grib")) return json(route, { status: "absent" });
    if (path.includes("/voyage/official/film")) return json(route, { status: "ready", chapters: [] });
    if (path.endsWith("/voyage/official/clock")) {
      if (!built?.clock) return json(route, { detail: "clock" }, 404);
      return json(route, built.clock);
    }
    if (path.endsWith("/voyage/official")) {
      if (route.request().method() === "PUT") {
        let body = {};
        try { body = route.request().postDataJSON(); } catch { body = {}; }
        built = clockFromMarks(body.marks) || built;
      }
      return json(route, { voyageId: "official", status: "ready", clock: built?.clock || null });
    }
    return json(route, { status: "ready" });
  });
}

const WEATHER = "Weather at the boat: wind 12 kn.";

test("Now tab EN: empty EEZ answer never says high seas, one fact once", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  const badQueries = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  await routeApi(page, {
    onMoment: (url) => {
      const lat = url.searchParams.get("lat");
      const lon = url.searchParams.get("lon");
      if (!Number.isFinite(Number(lat)) || lat === "null" || lon === "null") badQueries.push(url.search);
    },
    // In port at Ajaccio, the EEZ lookup gave nothing.
    dossier: {
      version: 1,
      radiusNm: 30,
      zee: null,
      poe: [],
      amp: [],
      projects: [],
      nearby: { marinas: [{ name: "Port Tino Rossi", nm: 0.3 }], capitaineries: [], wpi: [], anchorages: [] },
      marks: [],
      sources: { zee: "unavailable", bi: "ok" },
    },
    moment: {
      signature: SHA,
      t: "2026-10-18T00:00:00Z",
      alerts: [],
      here: { zee: {}, sentences: [WEATHER, WEATHER] },
      around: [],
      sources: ["clock"],
    },
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await showLeftPanel(page);

  const box = page.getByTestId("ici-maintenant");
  await expect(page.getByTestId("ici-here-sentence").filter({ hasText: WEATHER })).toHaveCount(1, { timeout: 25_000 });
  // The briefing is built from the empty-EEZ answer above.
  await expect(page.getByTestId("ici-briefing")).toContainText("Port Tino Rossi", { timeout: 25_000 });
  await expect(box).not.toContainText(/high seas|haute mer/i);
  expect(badQueries, badQueries.join("\n")).toEqual([]);
  expect(errors, errors.join("\n")).toEqual([]);
});

test("Now tab EN: deduplicated cards, translated entry alert, no hash", async ({ page }) => {
  test.setTimeout(90_000);
  let built = null;
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const api = path.includes("/voyage") || path.includes("/ici");
    if (!api) return route.continue();
    if (path.includes("/ici/moment")) {
      return json(route, {
        signature: SHA,
        t: "2026-10-18T00:00:00Z",
        alerts: [],
        here: { sentences: [] },
        around: [
          { kind: "layer", title: "Bathymétrie – Nouvelle-Calédonie", fact: "GEBCO" },
          { kind: "zee", title: "Haute mer", fact: "haute mer : aucune ZEE" },
          { kind: "zee", title: "Haute mer", fact: "haute mer : aucune ZEE" },
        ],
        sources: ["clock"],
      });
    }
    if (path.endsWith("/voyage/official/journal")) {
      return json(route, { voyageId: "official", status: "ready", count: 0, days: [], latest: [], events: [] });
    }
    if (path.includes("/voyage/official/moments")) {
      // Before the Follow PUT the boat position is unknown: answer "building" so
      // the client polls again instead of keeping a moment far from the boat.
      if (!built?.from) return json(route, { voyageId: "official", status: "building", count: 0, moments: [] });
      const lat = built?.from?.lat ?? -22.2;
      const lon = built?.from?.lon ?? 166.4;
      const bathy = { kind: "layer", layer: "bathymetry", title: "Bathymétrie – Nouvelle-Calédonie", fact: "GEBCO", lat, lon };
      return json(route, {
        voyageId: "official",
        status: "ready",
        count: 1,
        moments: [{
          t: "2026-10-18T00:00:00Z",
          signature: SHA,
          pos: { lat, lon },
          alerts: [{ id: "poe", kind: "entry", title: "Vanuatu", fact: "Aucun port d'entrée officiel n'est connu pour Vanuatu", severity: "alert" }],
          around: [
            bathy,
            { ...bathy },
            { ...bathy, fact: "GEBCO 2024" },
            { kind: "marina", title: "Marina de Nouméa", fact: "nearby", url: "https://example.test/marina", lat, lon },
          ],
        }],
      });
    }
    if (path.includes("/voyage/official/grib")) return json(route, { status: "absent" });
    if (path.includes("/voyage/official/film")) return json(route, { status: "ready", chapters: [] });
    if (path.endsWith("/voyage/official/clock")) {
      if (!built?.clock) return json(route, { detail: "clock" }, 404);
      return json(route, built.clock);
    }
    if (path.endsWith("/voyage/official")) {
      if (route.request().method() === "PUT") {
        let body = {};
        try { body = route.request().postDataJSON(); } catch { body = {}; }
        built = clockFromMarks(body.marks) || built;
      }
      return json(route, { voyageId: "official", status: "ready", clock: built?.clock || null });
    }
    return json(route, { status: "ready" });
  });

  await page.goto("/");
  await dismissNotForNav(page);
  // The moments feed belongs to Suivre; Tracer intentionally hides the Now tab.
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);

  const nowCard = page.getByTestId("moment-now");
  const freeCard = page.getByTestId("moment-free");
  await expect(nowCard).toContainText("No official port of entry is known for Vanuatu", { timeout: 25_000 });
  await expect(nowCard).not.toContainText("Aucun port");
  await expect(freeCard).toContainText("Bathymétrie");
  // The three bathymetry entries make one card: Next goes to the marina.
  await freeCard.getByTestId("moment-next").evaluate((el) => el.click());
  await expect(freeCard).toContainText("Marina de Nouméa");
  await expect(page.getByTestId("moment-now")).toHaveCount(1);
  // « haute mer : aucune ZEE » once in the around list.
  await expect(page.getByTestId("ici-around").filter({ hasText: "aucune ZEE" })).toHaveCount(1);
  const box = page.getByTestId("ici-maintenant");
  await expect(box).not.toContainText(SHA);

  expect(errors, errors.join("\n")).toEqual([]);
});
