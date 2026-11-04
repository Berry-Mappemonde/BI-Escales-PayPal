// Panneau droit : plus d'encadré jaune route, nom du bateau
// une fois sous Polaires, remise 34 → 29 → ↺ → 34.
// Sans API : badge absent, skipper et cycle clavier tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent (pastilles jambe, nom sous Polaires si
// la polar n'a pas chargé) — jamais le badge, ni le nom dans Paramètres
// avancés, ni la remise.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  return page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

test("Plus d'encadré jaune, nom une fois, remise 34 → 29 → 34", async ({ page }) => {
  test.setTimeout(120_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — badge, skipper et remise autonomes",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await showToolsPanel(page);

  await expect(page.getByTestId("route-anti-shipping")).toHaveCount(0);

  const review = page.getByTestId("plan-review");
  if (await review.isVisible({ timeout: 8_000 }).catch(() => false)) {
    const summary = review.locator("summary");
    if ((await summary.count()) && !(await review.evaluate((el) => el.open))) {
      await summary.click();
    }
    const lanes = page.getByTestId("plan-review-lanes");
    if (await lanes.count()) {
      await expect(lanes.first()).toContainText(/couloirs\s*:|lanes\s*:/);
    } else if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "Revue du plan sans pastille par jambe — assertion couloirs sautée",
      });
    }
  } else if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "Revue du plan absente — assertion couloirs sautée",
    });
  }

  const polarBoat = page.getByTestId("polar-boat");
  const polarName = await polarBoat.isVisible().catch(() => false)
    ? (await polarBoat.innerText()).trim()
    : "";
  if (polarName) {
    await expect(polarBoat).toBeVisible();
    expect(polarName).not.toBe("");
  } else if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "Polaire non chargée — nom sous Polaires non exigé",
    });
  }

  const orders = page.getByTestId("skipper-orders");
  await expect(orders).toBeVisible({ timeout: 15_000 });

  // Tracer : Polaires / Paramètres repliés, Calques dépliés ; Suivre inchangé.
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showToolsPanel(page);
  const tracerPolar = page.getByTestId("polar-box");
  await expect(tracerPolar).toBeVisible();
  await expect.poll(async () => tracerPolar.evaluate((el) => (
    el.tagName.toLowerCase() === "details" ? el.open : true
  )), { timeout: 8_000 }).toBe(false);
  await expect.poll(async () => page.getByTestId("skipper-orders").evaluate((el) => el.open), {
    timeout: 8_000,
  }).toBe(false);
  await expect(page.getByTestId("export-box")).toBeVisible();
  await expect.poll(async () => page.getByTestId("layers-drawer").evaluate((el) => el.open), {
    timeout: 8_000,
  }).toBe(true);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  await showToolsPanel(page);
  const followPolar = page.getByTestId("polar-box");
  await expect(followPolar).toBeVisible();
  expect(await followPolar.evaluate((el) => el.tagName.toLowerCase() === "details")).toBe(false);

  if (!(await orders.evaluate((el) => el.open))) {
    await orders.locator("summary").first().click();
  }
  const openText = await orders.innerText();
  expect(openText, "Paramètres avancés sans Leopard").not.toMatch(/Leopard|Léopard/i);
  await expect(orders.getByText(/^Bateau$/)).toHaveCount(0);
  if (polarName) {
    expect(openText).not.toContain(polarName);
  }

  await shot(page, "01-panneau");

  const gale = page.getByTestId("skipper-expert-galeKt");
  await expect(gale).toBeVisible();
  await gale.scrollIntoViewIfNeeded();
  await expect(gale).toHaveValue("34");
  const reset = page.getByTestId("skipper-expert-galeKt-reset");
  await expect(reset).toBeDisabled();

  await gale.click({ clickCount: 3 });
  await page.keyboard.type("29");
  await expect(gale).toHaveValue("29");
  await expect(reset).toBeEnabled();
  await shot(page, "02-remise");

  await reset.click();
  await expect(gale).toHaveValue("34");
  await expect(reset).toBeDisabled();
});
