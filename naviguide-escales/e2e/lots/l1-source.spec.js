// Source du récit ici() (Token Factory ou règles).
// Sans API : le libellé dit « règles ». La recette réelle (Nemotron Super)
// exige NEBIUS_API_KEY sur le VPS / l’API locale.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Story-source : Token Factory ou règles, jamais vide", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  // Suivre ouvre le cinéma et range les panneaux : on sort du cinéma pour
  // le libellé sous le récit ici().
  await page.getByRole("button", { name: /^cinéma$/i }).click();
  const source = page.getByTestId("story-source");
  if (await source.count()) {
    await source.scrollIntoViewIfNeeded();
    await expect(source).toBeVisible({ timeout: 10_000 });
    const text = (await source.innerText()).trim();
    expect(text, "story-source ne doit pas être vide").not.toBe("");
    if (await source.getAttribute("data-llm-source") === "rules") {
      expect(text).toBe("Formulé par les données brutes");
    } else {
      expect(text).toMatch(/Token Factory/i);
    }
  }
  await shot(page, "01-source");
});
