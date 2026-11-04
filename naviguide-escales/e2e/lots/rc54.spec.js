// Revue du plan : Mata-Utu → Nouméa sans couloir atlantique ;
// Nouméa → La Rochelle : jours de mer et dates ne se contredisent pas.
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions jambes — onglet Revue et Suivre gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  dismissNotForNav,
  leaveCinema,
  openReviewTab,
  probeOfficialPlanReview,
  showLeftPanel,
} from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc54");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const ATLANTIC_LANES = /Bay of Biscay|N Atlantic/i;

function calendarDays(departIso, arriveIso) {
  const a = Date.parse(departIso || "");
  const b = Date.parse(arriveIso || "");
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return (b - a) / 86400000;
}

test("Mata-Utu → Nouméa sans Biscay ; dates Nouméa cohérentes", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp, reviewReady, legs } = await probeOfficialPlanReview(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions jambes sautées ; Suivre et Revue gardés",
    });
  } else if (!reviewReady) {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready — PLAN_REVIEW_REV, jambes sautées ; onglet gardé",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await openReviewTab(page);
  const review = page.getByTestId("ici-review-slot").getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 15_000 });

  if (!apiUp || !reviewReady) {
    await shot(page, "01-jambes");
    return;
  }

  const mata = legs.filter((leg) => (
    /Mata-Utu/i.test(leg?.from || "") && /Nouméa|Noumea/i.test(leg?.to || "")
  ));
  expect(mata.length, "jambe Mata-Utu → Nouméa dans la revue").toBeGreaterThan(0);
  for (const leg of mata) {
    const lanes = Array.isArray(leg?.antiShipping?.lanes) ? leg.antiShipping.lanes.join(" ") : "";
    expect(lanes, "Mata-Utu → Nouméa sans Bay of Biscay").not.toMatch(/Bay of Biscay/i);
    expect(lanes, "Mata-Utu → Nouméa sans N Atlantic").not.toMatch(/N Atlantic/i);
  }

  const noumeaRochelle = legs.filter((leg) => (
    /Nouméa|Noumea/i.test(leg?.from || "") && /La Rochelle/i.test(leg?.to || "")
  ));
  for (const leg of noumeaRochelle) {
    const span = calendarDays(leg.departIso, leg.arriveIso);
    const days = Number(leg.daysAtSea);
    expect(Number.isFinite(span) && span > 0, "dates Nouméa → La Rochelle").toBeTruthy();
    expect(Number.isFinite(days) && days > 0, "jours de mer Nouméa → La Rochelle").toBeTruthy();
    const lo = Math.min(span, days);
    const hi = Math.max(span, days);
    expect(hi / Math.max(lo, 1e-9), "jours et dates sans facteur dix").toBeLessThan(10);
  }

  const row = review.getByTestId("plan-review-leg").filter({ hasText: /Mata-Utu/i });
  await expect(row.first()).toBeVisible({ timeout: 8_000 });
  await row.first().scrollIntoViewIfNeeded();
  const mataText = await row.first().innerText();
  expect(mataText).not.toMatch(ATLANTIC_LANES);

  const noumeaOnward = review.getByTestId("plan-review-leg")
    .filter({ hasText: /Nouméa|Noumea/i })
    .filter({ hasText: /Dzaoudzi|La Rochelle/i });
  if (await noumeaOnward.count()) {
    await noumeaOnward.first().scrollIntoViewIfNeeded();
  }

  await shot(page, "01-jambes");
});
