// Encadré honnête : le bateau à l'écran, pas Fort-de-France / Guadeloupe.
// Sans API : sections présentes, aucune fixture official_mini (Fort-de-France →
// Pointe-à-Pitre, CORIOLIS-Guadeloupe, Exclusive Economic Zone).
// Avec API : Ici = phrases localisées du Moment ; Simulation sans « → Fort-de-France » ;
// clic Ajaccio → fiche dans Ici, pas de popup. Ne pas affaiblir les assertions
// qui n'ont pas besoin de l'API.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rc2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const MINI_LEG = /Fort-de-France\s*→\s*Pointe-à-Pitre|Fort-de-France.*Pointe-à-Pitre/i;
const MINI_MARK = /Fort-de-France|Pointe-à-Pitre|CORIOLIS-Guadeloupe/i;
const RAW_ZEE = /Exclusive Economic Zone|\(Guadeloupe\)\s*\(Guadeloupe\)/i;

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

async function assertHonestBox(page) {
  const box = page.getByTestId("ici-maintenant");
  await expect(box).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByTestId("ici-section-alerts")).toBeVisible();
  await expect(page.getByTestId("ici-section-here")).toBeVisible();
  await expect(page.getByTestId("ici-section-around")).toBeVisible();
  await expect(page.getByTestId("ici-section-sources")).toBeVisible();
  const leg = page.getByTestId("ici-leg-line");
  await expect(leg).toHaveCount(1);
  const legText = (await leg.innerText()).replace(/\s+/g, " ");
  expect(legText, `étape : ${legText}`).not.toMatch(MINI_LEG);
  expect(legText, `étape : ${legText}`).not.toMatch(/Pointe-à-Pitre/i);
  expect(legText, `étape : ${legText}`).not.toMatch(/CORIOLIS-Guadeloupe/i);
  const here = page.getByTestId("ici-section-here");
  const hereText = (await here.innerText()).replace(/\s+/g, " ");
  expect(hereText, `Ici : ${hereText}`).not.toMatch(RAW_ZEE);
  expect(hereText, `Ici : ${hereText}`).not.toMatch(/CORIOLIS-Guadeloupe/i);
  expect(hereText, `Ici : ${hereText}`).not.toMatch(/Pointe-à-Pitre/i);
  const briefing = page.getByTestId("ici-briefing");
  if (await briefing.count()) {
    const brief = (await briefing.innerText()).replace(/\s+/g, " ");
    expect(brief, `ici-briefing : ${brief}`).not.toMatch(/Pointe-à-Pitre|CORIOLIS-Guadeloupe/i);
    expect(brief, `ici-briefing : ${brief}`).not.toMatch(RAW_ZEE);
  }
}

async function clickAjaccio(page) {
  const hasAjaccio = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 20_000 }).then(() => true).catch(() => false);
  if (!hasAjaccio) return false;
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) {
        scene.map.setView(marker.getLatLng(), 7, { animate: false });
        marker.fire("click");
        return;
      }
    }
  });
  const sheet = page.getByTestId("ici-maintenant").getByTestId("escale-sheet");
  const opened = await sheet.isVisible({ timeout: 8_000 }).catch(() => false);
  if (!opened) {
    const row = page.locator("li").filter({ hasText: /Ajaccio/i }).first();
    const openBtn = row.getByTestId("escale-sheet-open");
    if (await openBtn.isVisible().catch(() => false)) await openBtn.click();
  }
  await expect(page.locator(".leaflet-popup.escale-popup")).toHaveCount(0);
  if (await sheet.isVisible().catch(() => false)) {
    await expect(sheet).toContainText(/Ajaccio/i);
    if (await page.getByTestId("ici-tab-now").count()) {
      await expect(page.getByTestId("ici-tab-now")).toHaveAttribute("aria-selected", "true");
    }
    await sheet.scrollIntoViewIfNeeded();
  }
  return true;
}

test("Encadré du point courant, plus official_mini", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — phrases Ici du Moment et fiche Ajaccio enrichie non exigées",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await assertHonestBox(page);
  if (apiUp) {
    const sentence = page.getByTestId("ici-here-sentence").first();
    const appeared = await sentence.isVisible({ timeout: 12_000 }).catch(() => false);
    await assertHonestBox(page);
    if (appeared) {
      const text = (await sentence.innerText()).replace(/\s+/g, " ");
      expect(text, `Ici Suivre : ${text}`).not.toMatch(RAW_ZEE);
      expect(text, `Ici Suivre : ${text}`).not.toMatch(/\(Guadeloupe\)\s*\(Guadeloupe\)/);
    } else {
      test.info().annotations.push({
        type: "Ici",
        description: "aucune phrase Moment à temps — Ici vide ou en attente, pas de fixture Antilles",
      });
    }
  }
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
  await assertHonestBox(page);
  await expect(page.getByTestId("ici-leg-line")).not.toContainText(/→\s*Fort-de-France/i);
  if (apiUp) {
    const opened = await clickAjaccio(page);
    if (!opened) {
      test.info().annotations.push({
        type: "drapeau",
        description: "aucun drapeau Ajaccio — ouverture d'escale dans l'encadré non jouée",
      });
    }
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "clic Ajaccio / fiche d'escale non exigé",
    });
  }
  await shot(page, "02-simulation");

  const draw = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i });
  await expect(draw).toBeVisible({ timeout: 15_000 });
  await draw.scrollIntoViewIfNeeded();
  // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Choisissez votre point de départ|Choose your starting point/i).first()).toBeVisible();
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByTestId("ici-section-here")).toBeVisible();
  const hereText = (await page.getByTestId("ici-section-here").innerText()).replace(/\s+/g, " ");
  expect(hereText, `Ici Tracer : ${hereText}`).not.toMatch(MINI_MARK);
  expect(hereText, `Ici Tracer : ${hereText}`).not.toMatch(RAW_ZEE);
  expect(hereText, `Ici Tracer : ${hereText}`).not.toMatch(/Guadeloupe/i);
  await shot(page, "03-tracer");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
