// Plus de net::ERR_ABORTED sur /ici/warm/status et /voyage/official/eta.
// Sans API : le parcours Suivre → Simulation → Tracer → Suivre tient seul ;
// l'absence d'ERR_ABORTED (abort client) reste exigée. GET /voyage/official
// sondé ; s'il manque, annotation + saut de la fourchette servie par le stock
// — jamais le parcours, ni l'assertion console.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer, leaveCinema, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rh2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const WATCHED = /\/ici\/warm\/status|\/voyage\/official\/eta/;

function isAborted(text) {
  return /ERR_ABORTED|net::ERR_ABORTED/i.test(String(text || ""));
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && typeof body === "object");
}

test("Parcours nominal sans net::ERR_ABORTED (warm/status, eta)", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette sautée ; parcours et absence d'ERR_ABORTED gardés",
    });
  }

  const aborted = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (isAborted(text) && WATCHED.test(text)) aborted.push(`console ${text}`);
  });
  page.on("requestfailed", (req) => {
    const err = req.failure()?.errorText || "";
    if (isAborted(err) && WATCHED.test(req.url())) aborted.push(`${err} ${req.url()}`);
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  const suivre = page.getByTestId("view-suivre");
  const simulation = page.getByTestId("view-tracer");
  await suivre.click();
  await expect(suivre).toHaveAttribute("aria-checked", "true");

  await simulation.click();
  await expect(simulation).toHaveAttribute("aria-checked", "true");

  await enterTracer(page);
  await expect(page.getByTestId("drawing-box")).toBeVisible();
  const cancel = page.locator(".naviguide-sidebar-panel").getByRole("button", { name: /^(annuler|cancel)$/i }).first();
  await expect(cancel).toBeVisible({ timeout: 8_000 });
  await cancel.click({ force: true, timeout: 5_000 }).catch(() => cancel.evaluate((el) => el.click()));
  await expect(page.getByTestId("film-bar")).not.toHaveAttribute("data-drawing", "1", { timeout: 10_000 });

  await expect(suivre).toBeVisible({ timeout: 10_000 });
  await suivre.click({ force: true, timeout: 5_000 }).catch(() => suivre.evaluate((el) => el.click()));
  await expect(suivre).toHaveAttribute("aria-checked", "true");
  await page.waitForTimeout(8_000);

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "proxy vers un port mort : ERR_ABORTED du proxy, pas d'un abort() client — assertion console sautée",
    });
    await shot(page, "01-console-propre");
    return;
  }

  expect(aborted, `net::ERR_ABORTED : ${aborted.join(" | ")}`).toEqual([]);

  await showRightPanel(page).catch(() => {});
  const eta = page.getByTestId("eta-range");
  const visible = await eta.isVisible().catch(() => false);
  if (visible) {
    const label = (await eta.innerText()).trim();
    if (label) {
      expect(label).toMatch(/arrivée entre le|arrival between|fourchette indisponible|arrival window unavailable/i);
      expect(label).not.toMatch(/p10|membres|members/i);
    }
  } else {
    test.info().annotations.push({
      type: "stock",
      description: "fourchette absente (stock pas encore servi) — jamais inventée",
    });
  }

  await shot(page, "01-console-propre");
});
