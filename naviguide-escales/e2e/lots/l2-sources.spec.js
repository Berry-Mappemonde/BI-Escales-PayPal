// Source sous le chat (et la fiche si un paragraphe est là).
// Sans API : poser une question échoue honnêtement ; chat-source n'existe
// alors pas. S'il existe, il n'est pas vide.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Chat-source : s'il est là après une question, il n'est pas vide", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  const { showLeftPanel } = await import("../helpers.js");
  await showLeftPanel(page);
  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 10_000 });
  await chat.getByTestId("logbook-chat-input").fill("Quel vent au bateau ?");
  await chat.getByTestId("logbook-chat-send").click();
  await page.waitForTimeout(800);
  const source = page.getByTestId("chat-source");
  if (await source.count()) {
    await expect(source.last()).toBeVisible();
    const text = (await source.last().innerText()).trim();
    expect(text, "chat-source ne doit pas être vide").not.toBe("");
  }
  await shot(page, "01-chat");
});
