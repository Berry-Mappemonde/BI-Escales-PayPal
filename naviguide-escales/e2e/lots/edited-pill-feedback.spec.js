import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

for (const [lang, note, retry, playingTip] of [
  ["en", "The edited film is temporarily unavailable.", "Retry", "Stop the film to switch Raw/Edited"],
  ["fr", "Le film rédigé est momentanément indisponible.", "Réessayer", "Arrêtez le film pour passer Brut/Rédigé"],
]) {
  test(`Edited pill feedback (${lang})`, async ({ page }) => {
    let writtenRequests = 0;
    await page.route("**/voyage/official/film**", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      writtenRequests += 1;
      const success = writtenRequests > 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        status: success ? "ready" : "preparing", lang, style: success ? "written" : "raw", source: success ? "nemotron-super-token-factory" : "rules",
        hasWritten: success,
        ...(!success ? { reason: "all-providers-failed" } : {}),
        chapters: [{ text: "A short film for the tour.", anchors: [{ t: 0, i: 0 }] }],
      }) });
    });
    await page.goto(`/?lang=${lang}`);
    await dismissNotForNav(page);
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
    const langButton = page.getByTestId(`lang-${lang}`);
    if (!(await langButton.isVisible().catch(() => false))) {
      const toggle = page.locator(".naviguide-sidebar-toggle--right");
      if (await toggle.isVisible().catch(() => false)) await toggle.click();
    }
    await langButton.click();
    await page.getByTestId("view-suivre").click();
    const edited = page.getByTestId("film-style-written");
    await expect(edited).toBeVisible();
    await expect(edited).toHaveAttribute("aria-disabled", "false");
    await edited.click();
    await expect(page.getByRole("status")).toContainText(note);
    await expect(page.getByRole("button", { name: retry })).toBeVisible();
    await page.getByRole("button", { name: retry }).click();
    await expect(edited).toHaveAttribute("aria-pressed", "true");
    expect(writtenRequests).toBe(2);

    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 15_000 });
    await expect(edited).toHaveAttribute("title", playingTip);
  });
}
