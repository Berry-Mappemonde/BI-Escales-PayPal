// RC1 — aucune erreur console React au chargement ni pendant la visite ?tour=1.
// Régression visée : « Attempted to synchronously unmount a root while React was
// already rendering » (racines des popups démontées dans un nettoyage d'effet).
// Le double effet de StrictMode n'existe qu'en dev : `PW_DEV_ORIGIN=http://127.0.0.1:5174`
// pointe le test vers `vite` (dev-mac.sh) ; sinon il tourne sur le build servi.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const ORIGIN = process.env.PW_DEV_ORIGIN || "";
const STEPS = ["welcome", "models", "live", "briefing", "layers", "replay", "trace", "return"];
const REACT_ERR = /synchronously unmount|while React was already rendering|Warning: |React (?:has )?detected|Minified React error/i;

function watch(page) {
  const bad = [];
  page.on("console", (m) => {
    if (m.type() === "error" && REACT_ERR.test(m.text())) bad.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => bad.push(`pageerror: ${e.message}`));
  return bad;
}

test("RC1 chargement : console sans erreur React", async ({ page }) => {
  const bad = watch(page);
  await page.goto(`${ORIGIN}/`);
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expect(bad, bad.join("\n")).toEqual([]);
});

test("RC1 ?tour=1 : visite complète sans erreur React", async ({ page }) => {
  test.setTimeout(90_000);
  const bad = watch(page);
  await page.goto(`${ORIGIN}/?tour=1`);
  await dismissNotForNav(page);
  const panel = page.getByTestId("demo-walkthrough-panel");
  await expect(panel).toHaveAttribute("data-step", "welcome", { timeout: 30_000 });
  for (const id of STEPS.slice(1)) {
    await page.getByTestId("demo-walkthrough-next").click();
    await expect(panel).toHaveAttribute("data-step", id);
  }
  await page.waitForTimeout(1000);
  expect(bad, bad.join("\n")).toEqual([]);
});

test("RC1 bulles : EventBubble et EscalePopup ouvertes puis détruites sans erreur React", async ({ page }) => {
  test.setTimeout(90_000);
  const bad = watch(page);
  await page.goto(`${ORIGIN}/`);
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => window.__naviguideScene?.mainBoatMarker?.(), null, { timeout: 30_000 });
  // Bulle d'événement (racine React n° 1).
  await page.evaluate(() => window.__naviguideScene.eventBubble.setCard({
    id: "rc1", kind: "wx", at: "2026-05-27T12:00:00Z", title: "Coup de vent",
  }));
  await expect(page.getByTestId("event-bubble")).toBeVisible({ timeout: 10_000 });
  // Fiche d'escale (racine React n° 2) : un drapeau cliqué en Tracer (il faut l'API).
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  if (process.env.PW_WITH_API === "1") {
    // Le changement de vue déclenche le chargement asynchrone des marqueurs.
    // Ne pas laisser l'évaluation ci-dessous réussir à vide avant Ajaccio.
    await page.waitForFunction(() => {
      for (const m of window.__naviguideScene?.waypointMarkers?.values() || []) {
        if (/Ajaccio/i.test(m._naviguideWaypoint?.name || "")) return true;
      }
      return false;
    }, null, { timeout: 15_000 });
    const clickedAjaccio = await page.evaluate(() => {
      for (const m of window.__naviguideScene?.waypointMarkers?.values() || []) {
        if (/Ajaccio/i.test(m._naviguideWaypoint?.name || "")) { m.fire("click"); return true; }
      }
      return false;
    });
    expect(clickedAjaccio, "marqueur Ajaccio trouvé au moment du clic").toBe(true);
  }
  // Hors film, la fiche d'escale est rendue dans le panneau ; la popup Leaflet
  // reste neutralisée pour éviter de masquer les drapeaux et les autres fiches.
  const escale = page.getByTestId("escale-sheet").filter({ hasText: /Ajaccio/i });
  const escaleOpen = await escale.waitFor({ state: "visible", timeout: 10_000 }).then(() => true).catch(() => false);
  if (!escaleOpen) {
    expect(process.env.PW_WITH_API !== "1", "avec l'API, la fiche d'Ajaccio doit s'ouvrir").toBe(true);
    test.info().annotations.push({ type: "sans API", description: "fiche d'escale non ouverte : seule la bulle est vérifiée" });
  }
  // Détruit la scène (même chemin que le nettoyage d'effet de MapScene).
  await page.evaluate(() => window.__naviguideScene.dispose());
  await expect(page.getByTestId("event-bubble")).toHaveCount(0);
  await expect(page.locator(".leaflet-popup.escale-popup")).toHaveCount(0);
  // La fiche reste visible : elle appartient au panneau latéral, hors de la scène détruite.
  if (escaleOpen) await expect(escale).toBeVisible();
  expect(bad, bad.join("\n")).toEqual([]);
});
