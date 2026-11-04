// Follow : une horloge 200 « preparing » (t0 sans vertices) ne fige pas Suivre.
// Revue #121 (remarque 3) : les premiers GET /clock répondent preparing, le PUT n'a pas d'horloge ;
// la relance espacée doit atteindre l'horloge prête, puis s'arrêter.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const T0 = "2026-05-15T08:00:00Z";
const PREPARING_GETS = 2;

test("NAV-C follow : preparing → ready sans rechargement", async ({ page }) => {
  test.setTimeout(90_000);
  const probe = await page.request.get("/voyage/official/clock", { timeout: 5000 }).catch(() => null);
  const clock = probe && probe.ok() ? await probe.json().catch(() => ({})) : {};
  test.skip(!(Array.isArray(clock.vertices) && clock.vertices.length > 1), "API du stock figé absente (PW_WITH_API=1)");

  let gets = 0;
  await page.route("**/voyage/official/clock*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    gets += 1;
    if (gets <= PREPARING_GETS) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "preparing", t0: T0 }),
      });
    }
    return route.continue();
  });
  await page.route(/\/voyage\/official(\?.*)?$/, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    let res;
    try {
      res = await route.fetch();
    } catch {
      // La requête peut encore être en vol lorsque le test se termine.
      return;
    }
    let body = {};
    try { body = await res.json(); } catch { body = {}; }
    delete body.clock;
    return route.fulfill({ response: res, body: JSON.stringify(body), contentType: "application/json" });
  });

  await page.goto("/");
  await dismissNotForNav(page);
  const line = page.getByTestId("clock-line");
  // « LIVE » peut venir du repli local avant que l'horloge serveur soit prête.
  // Attendre la reprise du GET après les réponses preparing avant de lire la ligne.
  await expect.poll(() => gets, { timeout: 45_000 }).toBeGreaterThan(PREPARING_GETS);
  await expect(line).toBeVisible({ timeout: 30_000 });
  await expect(line).toContainText(/\d[\d\s.,]* nm .*LIVE/i, { timeout: 45_000 });
  const settled = gets;
  await page.waitForTimeout(8_000);
  expect(gets, "plus de relance une fois l'horloge prête").toBe(settled);
});
