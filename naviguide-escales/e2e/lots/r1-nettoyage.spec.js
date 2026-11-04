// Nettoyage : Esri une fois, plus de phrases d'aide, remise, pilules grisées.
// Sans API : attribution, textes, chiffres et classes disabled tiennent seuls.
// Le film (aria-disabled en live) et « Polaires chargées » dépendent de l'API.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showLeftPanel(page) {
  const chat = page.getByTestId("logbook-chat");
  if (await chat.isVisible().catch(() => false)) return;
  const cinema = page.getByRole("button", { name: /^cinéma$/i });
  if (await cinema.isVisible().catch(() => false)) await cinema.click();
  if (await chat.isVisible({ timeout: 4000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(chat).toBeVisible({ timeout: 15_000 });
}

async function showToolsPanel(page) {
  const theme = page.getByRole("button", { name: /^(sombre|clair|dark|light)$/i });
  if (await theme.isVisible().catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect(theme).toBeVisible({ timeout: 10_000 });
}

test("Esri une fois, plus d'aide, remise du chiffre, pilules grisées", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 20_000 });

  const { leaveCinema } = await import("../helpers.js");
  await leaveCinema(page);
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  const attr = page.locator(".leaflet-control-attribution");
  await expect(attr).toBeVisible();
  const attrText = await attr.innerText();
  expect((attrText.match(/Esri/g) || []).length, `attribution : ${attrText}`).toBe(1);
  await expect(attr).toContainText("Tuiles");
  await expect(attr).toContainText("HERE");
  await expect(attr).toContainText("Garmin");
  await expect(attr).toContainText("OpenStreetMap");
  await expect(attr).not.toContainText("données Esri");
  const hrefs = await attr.locator("a").evaluateAll((els) => els.map((a) => ({
    href: a.getAttribute("href") || "",
    text: (a.textContent || "").trim(),
  })));
  const ours = hrefs.filter((a) => /esri\.com|here\.com|garmin\.com|openstreetmap\.org\/copyright/.test(a.href));
  expect(ours, `liens tuiles : ${JSON.stringify(ours)}`).toHaveLength(4);
  expect(ours.filter((a) => a.text === "Esri")).toHaveLength(1);
  await shot(page, "01-credits");
  await cinema.evaluate((el) => el.click());

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/Le journal répond avec/);
  expect(body).not.toMatch(/The logbook answers from/);
  expect(body).not.toMatch(/Par jambe : calendrier/);
  expect(body).not.toMatch(/Per leg: calendar/);
  expect(body).not.toMatch(/Réglages Expert, hors profil/);
  expect(body).not.toMatch(/Expert settings, outside the profile/);

  await showToolsPanel(page);
  const polarStatus = page.getByTestId("polar-status");
  await expect(polarStatus).toBeVisible();
  const polarText = (await polarStatus.innerText()).trim();
  if (/Polaires chargées|Polars loaded/.test(polarText)) {
    expect(polarText, `polar-status : ${polarText}`).not.toMatch(/Léopard|Leopard/);
  }

  const orders = page.getByTestId("skipper-orders");
  await expect(orders).toBeVisible();
  if (!(await orders.evaluate((el) => el.open))) {
    await orders.locator("summary").first().click();
  }
  const expert = page.getByTestId("skipper-expert");
  await expect(expert).toBeVisible();
  if (!(await expert.evaluate((el) => el.open))) {
    await expert.locator("summary").click();
  }
  const gale = page.getByTestId("skipper-expert-galePct");
  await expect(gale).toBeVisible();
  const profileValue = await gale.inputValue();
  await gale.fill("22");
  const reset = page.getByTestId("skipper-expert-galePct-reset");
  await expect(reset).toBeEnabled();
  await reset.click();
  await expect(gale).toHaveValue(profileValue);
  await expect(reset).toBeDisabled();
  await shot(page, "02-chiffres");

  const raw = page.getByTestId("film-style-raw");
  const written = page.getByTestId("film-style-written");

  const start = page.getByTestId("replay-start");
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!(await start.isVisible().catch(() => false))) {
    if (!apiUp) {
      test.info().annotations.push({ type: "sans API", description: "Revoir absent — pilules grisées en live non vérifiées" });
    } else {
      throw new Error("Revoir absent alors que l'API répond");
    }
    return;
  }
  if (apiUp) {
    const { waitFilmReady } = await import("../helpers.js");
    await waitFilmReady(page);
  }
  await start.click();
  const stop = page.getByTestId("replay-stop");
  const filmOn = await stop.isVisible({ timeout: 8000 }).catch(() => false);
  if (!filmOn) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "Revoir n'a pas démarré — aria-disabled en live non vérifié",
      });
      return;
    }
    throw new Error("Revoir n'a pas démarré alors que le film est prêt");
  }
  await expect(raw).toHaveAttribute("aria-disabled", "true");
  await expect(written).toHaveAttribute("aria-disabled", "true");
  await expect(raw).toHaveAttribute("title", /Arrêtez le film pour passer Brut\/Rédigé|Stop the film to switch Raw\/Edited/);
  await expect(written).toHaveAttribute("title", /Arrêtez le film pour passer Brut\/Rédigé|Stop the film to switch Raw\/Edited/);
  await expect(raw).toHaveClass(/cursor-not-allowed/);
});
