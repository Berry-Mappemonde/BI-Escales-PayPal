// Fourchette ou raison sous la jambe live (Nouméa tant que
// le bateau n'y est pas), jamais sous Dzaoudzi / Papeete / La Rochelle
// à la place. Instant officiel (iso / filmNm), jamais Date.now().
// Sans API : Suivre + légende tiennent seuls. GET /voyage/official sondé ;
// s'il manque, annotation + saut des seules assertions fourchette / raison.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { nextStopFromMarks } from "../../src/hooks/usePlanReview.js";
import { dismissNotForNav, leaveCinema, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc28");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  let clock = body.clock || null;
  const clockRes = await page.request.get("/voyage/official/clock", { timeout: 5000 }).catch(() => null);
  if (clockRes && clockRes.ok()) {
    const c = await clockRes.json().catch(() => null);
    if (c && typeof c === "object") clock = c;
  }
  let live = null;
  const atRes = await page.request.get("/voyage/official/at", { timeout: 5000 }).catch(() => null);
  if (atRes && atRes.ok()) {
    const a = await atRes.json().catch(() => null);
    if (a && typeof a === "object" && a.status !== "preparing") live = a;
  }
  return { apiUp: true, body, clock, live };
}

function nextStopName(official, clock, live) {
  const marks = clock?.marks || official?.clock?.marks || official?.marks || [];
  const nowMs = Date.parse(live?.iso || "");
  const liveNm = live?.filmNm;
  return nextStopFromMarks(marks, Number.isFinite(nowMs) ? nowMs : undefined, liveNm);
}

function stopShort(name) {
  return String(name || "").split(" (")[0];
}

function retryYear(iso) {
  if (iso == null || iso === "") return 0;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return 0;
  return new Date(t).getUTCFullYear();
}

test("Fourchette sous la jambe live, pas sous Dzaoudzi", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp, body: official, clock, live } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette / raison sautées ; légende gardée",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showRightPanel(page);

  const legend = page.getByTestId("escale-legend");
  await expect(legend).toBeVisible({ timeout: 20_000 });
  await legend.scrollIntoViewIfNeeded();

  const legendEta = page.getByTestId("eta-range");
  const lrRow = legend.locator('[data-testid="escale-legend-row"]').filter({ hasText: /La Rochelle/i }).first();
  const dzRow = legend.locator('[data-testid="escale-legend-row"]').filter({ hasText: /Dzaoudzi/i }).first();

  if (!apiUp) {
    await expect(legendEta).toHaveCount(0);
    await expect(lrRow.getByTestId("eta-range")).toHaveCount(0);
    await expect(dzRow.getByTestId("eta-range")).toHaveCount(0);
    await shot(page, "01-suivre-jambe-live");
    if (await lrRow.count()) {
      await lrRow.first().scrollIntoViewIfNeeded();
      await shot(page, "02-suivre-la-rochelle");
    }
    return;
  }

  const stop = nextStopName(official, clock, live);
  let eta = null;
  if (stop) {
    const etaRes = await page.request.get(
      `/voyage/official/eta?stop=${encodeURIComponent(stop)}`,
      { timeout: 8000 },
    ).catch(() => null);
    if (etaRes && etaRes.ok()) {
      eta = await etaRes.json().catch(() => null);
    }
  }

  if (!eta) {
    test.info().annotations.push({
      type: "poste",
      description: "GET /eta sans corps — ligne sautée ; légende gardée, aucune date inventée",
    });
    await expect(legendEta).toHaveCount(0);
    if (stop && !/la rochelle/i.test(stop)) {
      await expect(lrRow.getByTestId("eta-range")).toHaveCount(0);
    }
    if (stop && /nouméa/i.test(stop)) {
      await expect(dzRow.getByTestId("eta-range")).toHaveCount(0);
    }
    await shot(page, "01-suivre-jambe-live");
    if (await lrRow.count()) {
      await lrRow.first().scrollIntoViewIfNeeded();
      await shot(page, "02-suivre-la-rochelle");
    }
    return;
  }

  if (stop) {
    const nextRow = legend.locator('[data-testid="escale-legend-row"]').filter({
      hasText: stopShort(stop),
    }).first();
    await expect(nextRow.getByTestId("eta-range")).toBeVisible({ timeout: 25_000 });
    await nextRow.scrollIntoViewIfNeeded();
  } else {
    await expect(legendEta.first()).toBeVisible({ timeout: 25_000 });
  }
  expect(await legendEta.count(), "une seule ligne sous la jambe live").toBe(1);

  const a = (await legendEta.first().innerText()).trim();
  expect(a).not.toMatch(/1 janv\.?|1 Jan\.?/i);
  if (Number(eta.members) > 0) {
    expect(a).toMatch(/arrivée entre le|arrival between/i);
    expect(a).not.toMatch(/p10|membres|members/i);
  } else {
    expect(a).toMatch(/fourchette indisponible|arrival window unavailable/i);
    expect(a).not.toMatch(/arrivée entre le|arrival between/i);
    if (retryYear(eta.nextRetry) > 1970) {
      expect(a).toMatch(/nouvel essai|retry on/i);
    } else {
      expect(a).not.toMatch(/nouvel essai|retry on/i);
    }
  }

  if (stop && !/la rochelle/i.test(stop)) {
    await expect(lrRow.getByTestId("eta-range")).toHaveCount(0);
  }
  if (stop && /nouméa/i.test(stop)) {
    await expect(dzRow.getByTestId("eta-range")).toHaveCount(0);
  }

  await shot(page, "01-suivre-jambe-live");
  if (await lrRow.count()) {
    await lrRow.scrollIntoViewIfNeeded();
    await shot(page, "02-suivre-la-rochelle");
  }
  if (stop && /nouméa/i.test(stop) && await dzRow.count()) {
    await dzRow.scrollIntoViewIfNeeded();
    await shot(page, "03-suivre-dzaoudzi");
  }
});
