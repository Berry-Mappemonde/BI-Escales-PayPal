// Bulle événement pendant le film seulement (mode sans voix).
// Sans API : l'ouverture sans bulle se vérifie toujours ; le film local
// peut encore poser une bulle (départ / escale du brut).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function muteFilmVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

function bubbleNearBoat() {
  const bubble = document.querySelector("[data-testid='event-bubble']");
  const scene = window.__naviguideScene;
  const marker = scene?.mainBoatMarker?.();
  const map = scene?.map;
  if (!bubble || !marker || !map) return { ok: false, dist: Infinity, kind: "" };
  const boat = map.latLngToContainerPoint(marker.getLatLng());
  const popup = scene.eventBubble?.popup;
  const pll = popup?.getLatLng?.();
  const tip = pll ? map.latLngToContainerPoint(pll) : boat;
  const tipDist = Math.hypot(tip.x - boat.x, tip.y - boat.y);
  const icon = typeof marker.getElement === "function" ? marker.getElement() : null;
  const m = icon ? icon.getBoundingClientRect() : null;
  const b = bubble.getBoundingClientRect();
  let boxDist = Infinity;
  if (m && m.width > 2 && m.height > 2 && b.width > 2) {
    const mx = m.left + m.width / 2;
    const my = m.top + m.height / 2;
    const cx = Math.max(b.left, Math.min(mx, b.right));
    const cy = Math.max(b.top, Math.min(my, b.bottom));
    boxDist = Math.hypot(cx - mx, cy - my);
  }
  const dist = Math.min(tipDist, boxDist);
  return {
    ok: dist <= 60,
    dist,
    tipDist,
    boxDist,
    kind: bubble.getAttribute("data-kind") || "",
  };
}

test("Aucune bulle à l'ouverture, bulle pendant le film", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await expect(page.getByTestId("event-bubble")).toHaveCount(0);
  await shot(page, "01-ouverture-sans-bulle");

  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  await muteFilmVoice(page);
  await page.getByTestId("replay-start").click();
  await muteFilmVoice(page);

  await page.waitForFunction(() => Boolean(window.__naviguideFilm?.startedAt), { timeout: 8_000 });

  const bubble = page.getByTestId("event-bubble");
  const appeared = await bubble.isVisible({ timeout: 25_000 }).catch(() => false);
  if (!appeared) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "bulle film absente — assertions ancrage / croix / NOW sautées",
      });
      return;
    }
    throw new Error("bulle attendue pendant le film");
  }

  await expect(bubble).toBeVisible();
  expect(await page.getByTestId("event-bubble").count()).toBe(1);

  await page.waitForFunction(() => Boolean(window.__naviguideScene?.mainBoatMarker?.()), { timeout: 10_000 });
  const pos = await page.evaluate(bubbleNearBoat);
  expect(pos.ok, `distance bulle→bateau ${pos.dist} px`).toBeTruthy();
  expect(pos.dist).toBeLessThan(60);
  await shot(page, "02-bulle-film");

  const now = page.getByTestId("moment-now");
  if (await now.isVisible().catch(() => false)) {
    const bubbleLines = (await bubble.innerText()).split("\n").map((s) => s.trim()).filter((s) => s && s !== "×");
    const snippet = bubbleLines.find((s) => s.length >= 4) || "";
    if (snippet) {
      await expect(now).toContainText(snippet.slice(0, Math.min(24, snippet.length)));
    }
  }

  await page.getByTestId("event-bubble-close").click();
  await expect(page.getByTestId("event-bubble")).toHaveCount(0);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);
  await expect(page.getByTestId("replay-stop")).toBeVisible();

  await page.waitForTimeout(4_000);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);
  expect(await page.getByTestId("event-bubble").count()).toBeLessThanOrEqual(1);
});
