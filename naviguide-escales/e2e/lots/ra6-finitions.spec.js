// Finitions : skipper sans redite, crédits au-dessus, km terre, cadre chat.
// Sans API : skipper, crédits, info-bulle, cadre de réponse tiennent seuls.
// Jambe Saint-Maur « km par la route » : seulement si GET /voyage/official répond
// (ou si le repli interne affiche déjà le libellé).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showLeftPanel(page) {
  const chat = page.getByTestId("logbook-chat");
  if (await chat.isVisible({ timeout: 1500 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
}

async function showToolsPanel(page) {
  const orders = page.getByTestId("skipper-orders");
  if (await orders.isVisible({ timeout: 1500 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
}

test("Skipper, crédits, info-bulle, km terre, cadre chat", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — jambe Saint-Maur sautée si le libellé n'apparaît pas",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });

  await showToolsPanel(page);
  const orders = page.getByTestId("skipper-orders");
  await expect(orders).toBeVisible({ timeout: 15_000 });
  await orders.evaluate((el) => { el.open = false; });
  const collapsed = await orders.innerText();
  expect(collapsed, "en-tête replié sans Croisière · 36 h").not.toMatch(/Croisière\s*·\s*36\s*h/);
  if (!(await orders.evaluate((el) => el.open))) {
    await orders.locator("summary").first().click();
  }
  await expect(orders).toBeVisible();
  const openText = await orders.innerText();
  const cruise = openText.match(/Croisière/g) || [];
  expect(cruise.length, `Croisière ×${cruise.length}`).toBe(1);
  const phrase = openText.match(/Croisière\s*·\s*36\s*h/g) || [];
  expect(phrase.length, "phrase Croisière · 36 h une seule fois").toBeLessThanOrEqual(1);
  const profile = page.getByTestId("skipper-profile");
  if (await profile.isVisible().catch(() => false)) {
    await profile.scrollIntoViewIfNeeded();
  }
  await shot(page, "01-skipper");

  const attr = page.locator(".leaflet-control-attribution");
  await expect(attr).toBeVisible();
  const bar = page.getByTestId("film-bar");
  const attrBox = await attr.boundingBox();
  const barBox = await bar.boundingBox();
  expect(attrBox && barBox, "crédits et barre ont une boîte").toBeTruthy();
  expect(attrBox.y + attrBox.height, "crédits au-dessus de la barre").toBeLessThanOrEqual(barBox.y + 1);
  await shot(page, "02-credits");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const legend = page.getByTestId("regime-legend");
  await expect(legend).toBeVisible();
  const tip = await legend.getAttribute("title");
  expect(tip, `title pilule Suivre : ${tip}`).toMatch(/hindcast/i);
  expect(tip).toMatch(/prévision|forecast/i);
  expect(tip).toMatch(/climatolog/i);
  const pillTip = await page.getByTestId("speed-regime-pill").getAttribute("title");
  expect(pillTip).toMatch(/hindcast/i);

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  const land = page.getByTestId("film-land-leg");
  const landVisible = await land.isVisible({ timeout: 8000 }).catch(() => false);
  if (landVisible) {
    await expect(land).toContainText(/Transfert routier Saint-Maur \(Indre\) → La Rochelle : \d[\d\s\u202f]* km, ≈ \d+ h|Road transfer Saint-Maur \(Indre\) → La Rochelle: \d[\d,\s]* km, ≈ \d+ h/);
  } else if (apiUp) {
    test.info().annotations.push({
      type: "sans jambe terre",
      description: "horloge officielle hors Saint-Maur — libellé km non affiché",
    });
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "jambe Saint-Maur absente — assertion km sautée",
    });
  }

  await showLeftPanel(page);
  const reply = page.getByTestId("logbook-chat-reply");
  await expect(reply).toBeVisible();
  const replyBox = await reply.boundingBox();
  expect(replyBox && replyBox.height, "cadre de réponse visible").toBeGreaterThan(40);
  await expect(page.getByTestId("logbook-chat-list")).toBeVisible();
  await expect(page.getByTestId("logbook-chat-input")).toBeVisible();
});
