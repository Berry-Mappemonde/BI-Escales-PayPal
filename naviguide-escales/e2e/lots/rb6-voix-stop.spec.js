// Voix sans coupure, Stop total, caméra pas sur la Polynésie.
// Sans API : barre, Suivre, Revoir / Stop (horloge locale) tiennent seuls.
// Position live / script serveur : seulement si GET /voyage/official répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function isPolynesia(lat, lon) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return false;
  return la < 0 && lo < -120;
}

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

async function filmPos(page) {
  return page.evaluate(() => {
    const film = window.__naviguideFilm || {};
    const map = window.__naviguideScene?.map;
    const c = map?.getCenter?.();
    return {
      ended: Boolean(film.ended),
      chapter: film.chapterIdx ?? 0,
      lat: film.lat ?? c?.lat ?? null,
      lon: film.lon ?? c?.lng ?? null,
      stop: Boolean(document.querySelector("[data-testid='replay-stop']")),
      start: Boolean(document.querySelector("[data-testid='replay-start']")),
    };
  });
}

test("Stop coupe tout au premier clic ; pas de live sur incident", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — position live / script serveur non vérifiés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("listen")).toBeVisible();

  const replayStart = page.getByTestId("replay-start");
  if (!(await replayStart.isVisible({ timeout: 15_000 }).catch(() => false))) {
    test.info().annotations.push({
      type: "sans horloge",
      description: "Revoir absent — Stop / film non joués",
    });
    await expect(page.getByTestId("view-suivre")).toBeEnabled();
    await expect(page.getByTestId("listen")).toBeEnabled();
    await shot(page, "01-stop");
    return;
  }

  await replayStart.click();
  const stopBtn = page.getByTestId("replay-stop");
  await expect(stopBtn).toBeVisible({ timeout: 8_000 });
  await expect(stopBtn).toBeEnabled();
  await expect(stopBtn).toContainText(/^■?\s*Stop$/i);
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });

  await expect.poll(async () => page.evaluate(() => Boolean(window.__naviguideFilm?.startedAt)), {
    timeout: 5_000,
  }).toBe(true);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);

  await page.waitForTimeout(2_000);
  const mid = await filmPos(page);
  expect(mid.ended, "film encore en cours").toBe(false);
  expect(mid.stop, "Stop encore visible").toBe(true);
  if (apiUp) {
    expect(isPolynesia(mid.lat, mid.lon), "caméra pas sur la Polynésie pendant le film").toBe(false);
  }

  await stopBtn.click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("replay-stop")).toHaveCount(0);
  await expect(page.getByTestId("replay-start")).toContainText(/Revoir l.expédition|Replay the expedition/i);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const after = await filmPos(page);
  expect(after.stop).toBe(false);
  expect(after.start).toBe(true);

  await shot(page, "01-stop");
});
