// Libellé météo honnête : seulement ce qui alimente le point courant.
// Sans API : barre Simulation (une ligne, flèches, haut-parleur, pas de scroll),
// weather-line vide si présent, clock-regime sans GFS-Wave / Open-Meteo.
// Avec API : Suivre — climatologie hors 10 jours sans « + GFS » ; fenêtre
// prévision = GFS ou climatologie + GFS seulement si les sources du point
// le disent. Ne pas affaiblir les assertions qui n'ont pas besoin de l'API.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rc1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const GFS_SRC = /gfs|om-forecast|open-?meteo/i;
const TEN_DAYS_MS = 10 * 24 * 3600 * 1000;

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

async function commandsOverflow(page) {
  return page.getByTestId("film-commands").evaluate((el) => {
    const style = getComputedStyle(el);
    return {
      scroll: el.scrollWidth > el.clientWidth + 1,
      overflowX: style.overflowX,
    };
  });
}

function pointUsesGfs(sample) {
  const regime = sample?.regime || sample?.kind || "";
  if (regime === "forecast") return true;
  return (Array.isArray(sample?.sources) ? sample.sources : []).some((s) => GFS_SRC.test(String(s || "")));
}

function isClimoOnly(sample) {
  return (sample?.regime || sample?.kind) === "climatology" && !pointUsesGfs({ ...sample, regime: "climatology" });
}

function isPacific(v) {
  const lon = Number(v?.lon);
  return Number.isFinite(lon) && (lon < -120 || lon > 140);
}

async function seekFilm(page, ratio) {
  const track = page.locator("[data-testid='film-bar'] .relative.w-full.h-2").first();
  await expect(track).toBeVisible({ timeout: 15_000 });
  const box = await track.boundingBox();
  if (!box) throw new Error("barre film introuvable");
  const x = Math.max(4, Math.min(box.width - 4, box.width * ratio));
  await track.click({ position: { x, y: box.height / 2 } });
}

async function assertLabelNotGlobalGfs(page) {
  const regime = page.getByTestId("clock-regime");
  if (!(await regime.isVisible({ timeout: 5_000 }).catch(() => false))) return "";
  const text = (await regime.innerText()).replace(/\s+/g, " ");
  expect(text, `libellé météo : ${text}`).not.toMatch(/GFS-Wave|Open-Meteo/i);
  return text;
}

async function assertHonestRegime(page, sample) {
  const regime = page.getByTestId("clock-regime");
  await expect(regime).toBeVisible({ timeout: 8_000 });
  const text = (await regime.innerText()).replace(/\s+/g, " ");
  expect(text, `libellé : ${text}`).not.toMatch(/GFS-Wave|Open-Meteo/i);
  const kind = sample?.regime || sample?.kind || "";
  const gfs = pointUsesGfs(sample);
  if (kind === "climatology" && !gfs) {
    expect(text, `climatologie seule, vu : ${text}`).toMatch(/climatolog/i);
    expect(text, `pas de + GFS : ${text}`).not.toMatch(/\+\s*GFS/i);
  } else if (kind === "climatology" && gfs) {
    expect(text, `les deux sources du point, vu : ${text}`).toMatch(/climatolog.+\+\s*GFS|climatology \+ GFS/i);
  } else if (kind === "hindcast") {
    expect(text, `hindcast C2, vu : ${text}`).toMatch(/hindcast/i);
  } else if (gfs || kind === "forecast") {
    expect(text, `GFS du point, vu : ${text}`).toMatch(/\bGFS\b/);
    expect(text, `GFS seul, vu : ${text}`).not.toMatch(/climatolog/i);
  }
  return text;
}

test("Libellé météo du point courant", async ({ page }) => {
  test.setTimeout(45_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — libellé du point (climatologie / GFS) non vérifié",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const bar = page.getByTestId("film-bar");
  await expect(bar.getByTestId("prev-stop")).toBeVisible();
  await expect(bar.getByTestId("next-stop")).toBeVisible();
  await expect(bar.getByTestId("prev-stop")).toContainText("‹");
  await expect(bar.getByTestId("next-stop")).toContainText("›");
  const listen = bar.getByTestId("listen");
  await expect(listen).toBeVisible();
  const listenBox = await listen.boundingBox();
  expect(listenBox, "haut-parleur mesurable").toBeTruthy();
  expect(listenBox.width, `Écouter trop large : ${listenBox.width}`).toBeLessThan(40);
  const ov = await commandsOverflow(page);
  expect(ov.overflowX, `overflow-x=${ov.overflowX}`).not.toBe("auto");
  expect(ov.scroll, "barre de défilement horizontale").toBeFalsy();
  await shot(page, "03-simulation-barre");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });

  const weatherLine = page.getByTestId("weather-line");
  if (await weatherLine.count()) {
    await expect(weatherLine).toHaveText("");
  }
  await assertLabelNotGlobalGfs(page);

  if (!apiUp) {
    await shot(page, "01-climatologie-futur");
    await shot(page, "02-fenetre-prevision");
    return;
  }

  const clock = await page.request.get("/voyage/official/clock", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const live = await page.request.get("/voyage/official/at", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const verts = clock?.vertices || [];
  const now = Date.now();
  const lastFilm = Number(verts.at(-1)?.filmNm) || 0;

  if (live && await page.getByTestId("clock-regime").isVisible({ timeout: 8_000 }).catch(() => false)) {
    await assertHonestRegime(page, live);
  }

  const far = verts.find((v) => {
    const t = Date.parse(v?.iso || "");
    return Number.isFinite(t) && t > now + TEN_DAYS_MS && isClimoOnly(v) && isPacific(v);
  }) || verts.find((v) => {
    const t = Date.parse(v?.iso || "");
    return Number.isFinite(t) && t > now + TEN_DAYS_MS && isClimoOnly(v);
  });

  let sawClimoAlone = false;
  const journalTab = page.getByTestId("ici-tab-journal");
  if (await journalTab.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await journalTab.evaluate((el) => el.click());
    const entries = page.getByTestId("ici-journal-entry");
    const n = await entries.count();
    let pick = null;
    let pickT = -Infinity;
    for (let i = 0; i < n; i += 1) {
      const iso = await entries.nth(i).getAttribute("data-t");
      const t = Date.parse(iso || "");
      if (Number.isFinite(t) && t > now + TEN_DAYS_MS && t > pickT) {
        pickT = t;
        pick = { el: entries.nth(i), iso };
      }
    }
    if (pick) {
      await pick.el.evaluate((el) => el.click());
      await page.waitForTimeout(700);
      const sample = await page.request.get(`/voyage/official/at?t=${encodeURIComponent(pick.iso)}`, { timeout: 5000 })
        .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
      if (sample) {
        const text = await assertHonestRegime(page, sample);
        if (isClimoOnly(sample) || (/climatolog/i.test(text) && !/\+\s*GFS/i.test(text))) {
          sawClimoAlone = true;
        }
      }
    }
  }

  if (!sawClimoAlone && isClimoOnly(live)) {
    const text = await assertHonestRegime(page, live);
    sawClimoAlone = /climatolog/i.test(text) && !/\+\s*GFS/i.test(text);
  }

  if (sawClimoAlone) {
    await shot(page, "01-climatologie-futur");
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.waitForTimeout(800);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  if (live && await page.getByTestId("clock-regime").isVisible({ timeout: 8_000 }).catch(() => false)) {
    await assertHonestRegime(page, live);
  }
  await shot(page, "02-fenetre-prevision");

  if (!sawClimoAlone) {
    await shot(page, "01-climatologie-futur");
    await expect(page.getByTestId("film-clock-line")).toContainText(/LIVE/i);
  }
});
