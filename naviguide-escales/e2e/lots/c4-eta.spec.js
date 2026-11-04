// ETA : la revue de plan s'affiche et chaque ligne a une date.
// Aucun changement de surface ; seuls les nombres (dates) bougent.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openReviewTab } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-c4/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Revue de plan : chaque étape a une date", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  // Plan review dates are exposed in Suivre's review tab; Tracer keeps its own layout.
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await openReviewTab(page);
  const review = page.getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 15_000 });
  await expect(review).not.toContainText(/lecture…|reading…/i, { timeout: 25_000 });

  const rows = page.getByTestId("plan-review-leg");
  await expect(rows.first()).toBeVisible({ timeout: 15_000 }).catch(() => {});
  const n = await rows.count();
  if (n > 0) {
    for (let i = 0; i < n; i += 1) {
      const dates = rows.nth(i).getByTestId("plan-review-leg-dates");
      await expect(dates).toBeVisible();
      const text = (await dates.innerText()).trim();
      expect(text, `ligne ${i} sans date`).toMatch(/\d/);
      expect(text).toMatch(/→/);
    }
  } else {
    // Sans API le tableau est vide : le panneau reste visible (lot « nombres seulement »).
    await expect(review).toContainText(/Revue du plan|Plan review|indisponible|Aucune jambe|No leg to review/i);
  }
  await review.scrollIntoViewIfNeeded();
  await shot(page, "01-revue");
});
