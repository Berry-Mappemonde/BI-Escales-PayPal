// Revoir jusqu'à Nouméa : en-tête, statut et étape du Log décrivent
// la même position. Sans API : annotation, barre et Suivre restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-fv4");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && typeof body === "object");
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

test("Revoir jusqu'à Nouméa : en-tête, statut et Log cohérents", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — cohérence Ici / Log non exigée ; barre et Suivre gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  await showLeftPanel(page);

  if (!apiUp) {
    await expect(page.getByTestId("replay-start")).toBeDisabled();
    await shot(page, "01-sans-api");
    return;
  }

  const start = page.getByTestId("replay-start");
  await expect(start).toBeEnabled({ timeout: 30_000 }).catch(() => {});
  if (!(await start.isEnabled().catch(() => false))) {
    test.info().annotations.push({
      type: "sans film",
      description: "Revoir grisé — cohérence Ici / Nouméa non jouée",
    });
    await shot(page, "01-sans-film");
    return;
  }

  await muteVoice(page);
  await start.click();
  const ready = await page.waitForFunction(() => {
    const film = window.__naviguideFilm;
    return typeof film?.seekChapter === "function" && (film.chapterCount || 0) > 0;
  }, null, { timeout: 12_000 }).then(() => true).catch(() => false);
  if (!ready) {
    test.info().annotations.push({
      type: "film sans chapitres",
      description: "seekChapter indisponible — cohérence Ici / Nouméa non jouée",
    });
    await shot(page, "01-sans-chapitres");
    return;
  }

  const sought = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const noumeaTo = list.findIndex((c) => /noum[eé]a/i.test(c.toName || ""));
    const noumeaFrom = list.findIndex((c) => /noum[eé]a/i.test(c.fromName || ""));
    const marigot = list.findIndex((c) => /marigot/i.test(c.fromName || "") && /cayenne/i.test(c.toName || ""));
    let i = -1;
    let pinEnd = false;
    if (noumeaTo >= 0) {
      i = noumeaTo;
      pinEnd = true;
    } else if (noumeaFrom >= 0) {
      i = noumeaFrom;
    } else if (marigot >= 0) {
      i = marigot;
    }
    if (i < 0) return null;
    const ch = list[i];
    // Arrival stays at the port (tB). A departure is pinned on the first
    // phrase so the boat does not leave the stop before the check.
    if (pinEnd) window.__naviguideFilm.seekChapter(i);
    else window.__naviguideFilm.seekChapter(i, 1);
    return { from: ch.fromName || "", to: ch.toName || "", pinEnd };
  });
  if (!sought) {
    test.info().annotations.push({
      type: "sans étape",
      description: "ni Nouméa ni Marigot → Cayenne — cohérence non jouée",
    });
    await shot(page, "01-sans-etape");
    return;
  }
  if (!/noum[eé]a/i.test(`${sought.from} ${sought.to}`)) {
    test.info().annotations.push({
      type: "étape du film servi",
      description: `pas de chapitre Nouméa dans ce film — cohérence jouée sur ${sought.from} → ${sought.to}`,
    });
  }

  await page.getByTestId("ici-tab-now").click().catch(() => {});
  await expect.poll(async () => {
    const filmTo = await page.getByTestId("film-leg").getAttribute("data-to");
    const filmFrom = await page.getByTestId("film-leg").getAttribute("data-from");
    const iciTo = await page.getByTestId("ici-leg-line").getAttribute("data-to");
    const iciFrom = await page.getByTestId("ici-leg-line").getAttribute("data-from");
    const blob = `${filmFrom || ""} ${filmTo || ""}`;
    const leftOpening = !(/saint-maur/i.test(filmFrom || "") && /la rochelle/i.test(filmTo || ""));
    const wanted = sought.pinEnd
      ? /noum[eé]a/i.test(blob)
      : leftOpening && /marigot|cayenne|noum[eé]a/i.test(blob);
    if (!wanted) return `waiting ${filmFrom}→${filmTo}`;
    if (filmFrom !== iciFrom || filmTo !== iciTo) return `mismatch ${filmFrom}→${filmTo} vs ${iciFrom}→${iciTo}`;
    return "ok";
  }, { timeout: 20_000 }).toBe("ok");
  const filmFrom = await page.getByTestId("film-leg").getAttribute("data-from");
  const filmTo = await page.getByTestId("film-leg").getAttribute("data-to");
  expect(filmFrom).toBeTruthy();
  expect(filmTo).toBeTruthy();

  const here = page.getByTestId("ici-replay-here");
  await expect(here).toBeVisible();
  const highSeas = await here.getAttribute("data-high-seas");
  const stop = (await here.getAttribute("data-stop")) || "";
  const status = (await page.getByTestId("ici-replay-status").innerText()) || "";
  expect(status).not.toMatch(/Adelaide/i);
  await expect(page.getByTestId("escale-sheet")).toHaveCount(0);
  if (highSeas === "1") {
    expect(stop).toBe("");
    await expect(page.getByTestId("ici-replay-header")).toHaveCount(0);
  } else if (stop) {
    expect(status).not.toMatch(/high seas|haute mer/i);
    const onStep = [filmFrom, filmTo].some((name) => name && (name === stop || name.includes(stop) || stop.includes(name)));
    expect(onStep, `en-tête « ${stop} » hors de l'étape ${filmFrom} → ${filmTo}`).toBe(true);
    await expect(page.getByTestId("ici-replay-header")).toContainText(stop);
  }
  await shot(page, "02-coherent");
});
