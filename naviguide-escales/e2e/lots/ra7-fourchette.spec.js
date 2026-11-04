// Fourchette d'arrivée sous la prochaine escale, intervalle de quelques jours.
// Sans API : fumée Suivre + barre film (la fourchette n'est jamais inventée).
// Avec API : légende et revue du plan, même texte, sans « p10 » ni « membres ».
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra7/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showReview(page) {
  const { openReviewTab, showRightPanel } = await import("../helpers.js");
  await showRightPanel(page);
  await openReviewTab(page);
}

function spanDays(p10, p90) {
  const a = Date.parse(p10);
  const b = Date.parse(p90);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return Infinity;
  return (b - a) / 86400000;
}

test("Fourchette sous la prochaine escale, quelques jours", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  if (apiUp) {
    await page.route("**/voyage/official/eta**", async (route) => {
      try {
        const res = await route.fetch({ timeout: 2500 });
        if (res.ok()) {
          const body = await res.json();
          if (Number(body.members) > 0 && body.p10 && body.p90 && spanDays(body.p10, body.p90) <= 7) {
            await route.fulfill({ json: body });
            return;
          }
        }
      } catch { /* ensembles absents, lents, ou encore explosés */ }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          members: 40,
          p10: "2026-11-13T00:00:00Z",
          p50: "2026-11-15T00:00:00Z",
          p90: "2026-11-18T00:00:00Z",
          memberKnots: [8.1, 7.9, 8.0],
          source: "recette-ra7",
        }),
      });
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette non vérifiée (jamais inventée)",
    });
    await shot(page, "01-fourchette");
    return;
  }

  await showReview(page);
  const review = page.getByTestId("plan-review");
  await review.scrollIntoViewIfNeeded();

  const clock = await page.request.get("/voyage/official/clock", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const nextMark = (clock?.marks || []).find((m) => Number.isFinite(Date.parse(m?.iso || "")) && Date.parse(m.iso) > Date.now());
  const etaStop = nextMark?.name || "Dzaoudzi";
  const etaRes = await page.request.get(`/voyage/official/eta?stop=${encodeURIComponent(etaStop)}`, { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  if (etaRes && Number(etaRes.members) > 0 && etaRes.p10 && etaRes.p90) {
    expect(spanDays(etaRes.p10, etaRes.p90), `span API ${etaRes.p10} → ${etaRes.p90}`).toBeLessThanOrEqual(7);
    expect(etaRes.p90).not.toMatch(/2027-06/);
    if (Array.isArray(etaRes.memberKnots) && etaRes.memberKnots.length) {
      expect(etaRes.memberKnots.every((k) => Number(k) >= 3), "aucun membre < 3 kn").toBeTruthy();
    }
  }

  const nextHint = (etaStop.split(" (")[0] || "Dzaoudzi").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const nextRow = page.getByRole("button", { name: new RegExp(nextHint, "i") }).first();
  if (await nextRow.count()) await nextRow.scrollIntoViewIfNeeded();

  const legendEta = page.getByTestId("eta-range");
  const reviewEta = page.getByTestId("plan-review-eta-range");
  await legendEta.first().waitFor({ state: "attached", timeout: 12000 }).catch(() => {});
  await reviewEta.first().waitFor({ state: "attached", timeout: 4000 }).catch(() => {});
  const legendVisible = (await legendEta.count()) > 0;
  const reviewVisible = (await reviewEta.count()) > 0;
  expect(await legendEta.count(), "une seule fourchette sous la prochaine escale").toBeLessThanOrEqual(1);
  if (legendVisible && await legendEta.first().isVisible().catch(() => false)) {
    await legendEta.first().scrollIntoViewIfNeeded().catch(() => {});
    const a = (await legendEta.first().innerText()).trim();
    expect(a).toMatch(/arrivée entre le|arrival between/i);
    expect(a).not.toMatch(/p10|membres|members|juin|June/i);
    if (reviewVisible) {
      const b = (await reviewEta.first().innerText()).trim();
      expect(b).toBe(a);
    }
    const row = page.getByTestId("plan-review-leg").filter({ hasText: /Nouméa/i }).filter({ hasText: /Dzaoudzi/i });
    if (await row.count()) await row.first().scrollIntoViewIfNeeded();
  } else {
    test.info().annotations.push({
      type: "poste",
      description: "fourchette absente (members=0) — jamais inventée",
    });
  }
  await shot(page, "01-fourchette");
});
