// Langue EN : source du récit ici() visible (Lightning ou règles).
// Sans API : le libellé dit « rules ». La traduction Nemotron exige l'API.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function switchToEnglish(page) {
  const en = page.getByTestId("lang-en");
  if (!(await en.isVisible().catch(() => false))) {
    const right = page.locator(".naviguide-sidebar-toggle--right");
    if (await right.isVisible().catch(() => false)) await right.click();
  }
  await expect(en).toBeVisible({ timeout: 15_000 });
  await en.click();
}

test("Langue EN : story-source présent et non vide", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await switchToEnglish(page);
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  // Suivre ouvre le cinéma : on le quitte pour le libellé sous le récit ici().
  await page.getByRole("button", { name: /^(cinéma|cinema)$/i }).click();

  const source = page.getByTestId("story-source");
  await expect(source).toBeVisible({ timeout: 10_000 });
  const text = (await source.innerText()).trim();
  expect(text, "story-source ne doit pas être vide").not.toBe("");
  if (await source.getAttribute("data-llm-source") === "rules") {
    expect(text).toBe("Written from raw data");
  } else {
    expect(text).toMatch(/Token Factory|cache|budget/i);
  }
  await shot(page, "01-en");
});
