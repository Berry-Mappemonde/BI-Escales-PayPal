// A port-of-call sheet belongs to the stop the boat is at: once the clock
// carries the boat away from that stop, the sheet leaves the screen (no
// Tromelin sheet while the boat sails off Papeete).
import { expect, test } from "@playwright/test";
import { centerOnFlag, dismissNotForNav } from "../helpers.js";

async function openAjaccioFromFlag(page) {
  const ready = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 20_000 }).then(() => true).catch(() => false);
  if (!ready) return false;
  await centerOnFlag(page, /Ajaccio/);
  const flag = page.locator("[data-testid='waypoint-flag'][data-escale*='Ajaccio']").first();
  if (await flag.isVisible({ timeout: 8_000 }).catch(() => false)) await flag.click({ force: true });
  if (await page.getByTestId("escale-sheet").count()) return true;
  await page.evaluate(() => {
    for (const marker of window.__naviguideScene?.waypointMarkers?.values() || []) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) { marker.fire("click"); return; }
    }
  });
  return (await page.getByTestId("escale-sheet").count()) > 0;
}

test("a clicked sheet closes when the clock takes the boat far from that stop", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const opened = await openAjaccioFromFlag(page);
  if (!opened) {
    expect(process.env.PW_WITH_API !== "1", "with the API the Ajaccio flag must open its sheet").toBe(true);
    test.skip(true, "no Ajaccio flag without the API: the distance rule is not checked");
  }
  const sheet = page.getByTestId("escale-sheet");
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  await expect(sheet).toContainText("Ajaccio");
  // Just clicked, the boat has not moved: the requested sheet stays.
  await page.waitForTimeout(1_500);
  await expect(sheet).toBeVisible();

  // Scrub to the Pacific, thousands of nm from Ajaccio.
  const bar = page.getByTestId("film-bar").locator("button.absolute.inset-0").first();
  const box = await bar.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.click(box.x + box.width * 0.42, box.y + box.height / 2);
  await expect(page.getByTestId("escale-sheet")).toHaveCount(0, { timeout: 10_000 });
  await page.waitForTimeout(2_000);
  await expect(page.getByTestId("escale-sheet")).toHaveCount(0);
});
