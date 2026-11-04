// Fourchette d'arrivée sous la prochaine escale, ou la ligne
// honnête quand l'ensemble est vide (même contrat que RG17).
// members > 0 : la vraie fenêtre du stock. members = 0 : « indisponible »,
// jamais une date inventée. Sans API : Suivre + liste tiennent seuls.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re5");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

async function probeOfficial(request) {
  const official = await request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  if (!official || !official.ok()) return null;
  const ct = official.headers()["content-type"] || "";
  if (!ct.includes("json")) return null;
  const body = await official.json().catch(() => null);
  return body && typeof body === "object" ? body : null;
}

function retryYear(iso) {
  if (iso == null || iso === "") return 0;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return 0;
  return new Date(t).getUTCFullYear();
}

test("Fourchette sous la prochaine escale, ou la ligne honnête", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette / members sautés (jamais inventés)",
    });
  }

  // Pas d'interception : fenêtre du stock si members>0, ligne honnête si
  // members=0. Jamais une date écrite par le spec.

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  await showToolsPanel(page);

  const legend = page.getByTestId("escale-legend");
  await expect(legend).toBeVisible({ timeout: 20_000 });
  await legend.scrollIntoViewIfNeeded();

  const legendEta = page.getByTestId("eta-range");
  // Sans membres : pas de date inventée sous l'escale (vrai avec ou sans API).
  if (!apiUp) {
    await expect(legendEta).toHaveCount(0);
    await shot(page, "01-fourchette");
    return;
  }

  await expect(legendEta.first()).toBeVisible({ timeout: 25_000 });
  const nextRow = page.locator("[data-testid='escale-legend-row']").filter({ has: legendEta }).first();
  const stopName = (await nextRow.getAttribute("data-escale")) || "";
  const etaRes = stopName
    ? await request.get(`/voyage/official/eta?stop=${encodeURIComponent(stopName)}`, { timeout: 8000 }).catch(() => null)
    : null;
  const etaBody = etaRes && etaRes.ok() ? await etaRes.json().catch(() => null) : null;
  expect(etaBody, `GET /eta pour « ${stopName || "?"} »`).toBeTruthy();
  const members = Number(etaBody.members || 0);

  const a = (await legendEta.first().innerText()).trim();
  expect(a).not.toMatch(/p10|membres|members/i);
  expect(a).not.toMatch(/1 janv\.?|1 Jan\.?/i);
  if (members > 0) {
    expect(etaBody.p10 && etaBody.p90, "ensemble sans fourchette").toBeTruthy();
    expect(a).toMatch(/arrivée entre le|arrival between/i);
  } else {
    expect(etaBody.p10, "sans membres, pas de p10 inventé").toBeFalsy();
    expect(etaBody.p90, "sans membres, pas de p90 inventé").toBeFalsy();
    if (etaBody.reason) {
      expect(String(etaBody.reason).length, "raison honnête").toBeGreaterThan(0);
    }
    expect(a).toMatch(/fourchette indisponible|arrival window unavailable/i);
    expect(a).not.toMatch(/arrivée entre le|arrival between/i);
    if (retryYear(etaBody.nextRetry) > 1970) {
      expect(a).toMatch(/nouvel essai|retry on/i);
    } else {
      expect(a).not.toMatch(/nouvel essai|retry on/i);
    }
  }
  expect(await legendEta.count(), "une seule ligne sous la prochaine escale").toBe(1);
  await nextRow.scrollIntoViewIfNeeded().catch(() => {});
  await legendEta.first().scrollIntoViewIfNeeded().catch(() => {});
  await shot(page, "01-fourchette");
});
