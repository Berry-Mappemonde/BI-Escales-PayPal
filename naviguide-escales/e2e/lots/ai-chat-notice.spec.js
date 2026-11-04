// Avis du journal : il apparaît au premier échange, se ferme, et ne revient pas.
// Fermer « Ne convient pas à la navigation » ne doit pas le fermer.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showLeftPanel, showRightPanel } from "../helpers.js";

async function openChat(page) {
  await page.goto("/");
  await dismissNotForNav(page);
  await showLeftPanel(page);
  const input = page.getByTestId("logbook-chat-input");
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.focus();
  return page.getByTestId("logbook-chat-ai-notice");
}

// The disclaimer only opens on a gated layer: switch one on, so there is a
// real modal to close while the logbook notice is showing.
async function openNotForNavModal(page) {
  await showRightPanel(page);
  const drawer = page.getByTestId("layers-drawer");
  if (!(await drawer.evaluate((el) => el.open))) await drawer.locator("summary").click();
  const layer = page.getByTestId("layer-bathymetry");
  await layer.scrollIntoViewIfNeeded();
  await layer.click();
  const modal = page.getByTestId("not-for-nav-modal");
  await expect(modal).toBeVisible();
  return modal;
}

async function assertReadable(locator) {
  const size = await locator.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size).toBeGreaterThanOrEqual(12);
}

async function dismissNoticeAndWait(page, dismiss) {
  await dismiss.click();
  await expect.poll(() => page.evaluate(() => (
    localStorage.getItem("naviguide-ai-act-chat-notice-v1")
  ))).toBe("1");
  await expect(page.getByTestId("logbook-chat-ai-notice")).toHaveCount(0);
}

test("English: the AI notice appears at the first exchange and stays dismissed", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  const notice = await openChat(page);
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("artificial intelligence");
  await assertReadable(notice);
  const dismiss = notice.getByTestId("logbook-chat-ai-notice-dismiss");
  await expect(dismiss).toHaveText("Got it");
  await assertReadable(dismiss);
  const modal = await openNotForNavModal(page);
  await expect(notice).toBeVisible();
  await dismissNotForNav(page, { timeout: 3000 });
  await expect(modal).toHaveCount(0);
  await expect(notice).toBeVisible();
  await dismissNoticeAndWait(page, dismiss);
  await page.reload();
  await dismissNotForNav(page);
  await showLeftPanel(page);
  await page.getByTestId("logbook-chat-input").focus();
  await expect(page.getByTestId("logbook-chat-ai-notice")).toHaveCount(0);
});

test("Français : l’avis apparaît au premier échange et « Compris » du modal ne le ferme pas", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "fr"));
  const notice = await openChat(page);
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("intelligence artificielle");
  await assertReadable(notice);
  const dismiss = notice.getByTestId("logbook-chat-ai-notice-dismiss");
  await expect(dismiss).toHaveText("Compris");
  await assertReadable(dismiss);
  const modal = await openNotForNavModal(page);
  await expect(notice).toBeVisible();
  await dismissNotForNav(page, { timeout: 3000 });
  await expect(modal).toHaveCount(0);
  await expect(notice).toBeVisible();
  await dismissNoticeAndWait(page, dismiss);
  await page.reload();
  await dismissNotForNav(page);
  await showLeftPanel(page);
  await page.getByTestId("logbook-chat-input").focus();
  await expect(page.getByTestId("logbook-chat-ai-notice")).toHaveCount(0);
});

// R44 : notice AI Act annoncée (région live), noms accessibles, focus rendu au champ.
for (const [lang, inputName, sendName] of [["fr", "Votre question au carnet de bord", "Envoyer"], ["en", "Ask the logbook", "Send"]]) {
  test(`R44 ${lang} : notice en région live, noms accessibles, focus rendu au champ`, async ({ page }) => {
    await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
    const notice = await openChat(page);
    await expect(notice.getByRole("status")).toHaveAttribute("aria-live", "polite");
    await expect(page.getByRole("textbox", { name: inputName })).toBeVisible();
    await expect(page.getByRole("button", { name: sendName, exact: true })).toHaveAttribute("data-testid", "logbook-chat-send");
    await notice.getByTestId("logbook-chat-ai-notice-dismiss").focus();
    await page.keyboard.press("Enter");
    await expect(notice).toHaveCount(0);
    await expect(page.getByTestId("logbook-chat-input")).toBeFocused();
  });
}
