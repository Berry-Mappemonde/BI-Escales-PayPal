// Questions d'exemple du carnet : un clic envoie la question traduite par le flux
// existant (POST /logbook/chat), et la réponse arrive sous la question.
import { expect, test } from "@playwright/test";
import { dismissAiChatNotice, dismissNotForNav, showLeftPanel } from "../helpers.js";

async function openChat(page, lang) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await page.goto("/");
  await dismissNotForNav(page);
  await showLeftPanel(page);
  await expect(page.getByTestId("logbook-chat-examples")).toBeVisible({ timeout: 15_000 });
}

test("English: three example chips, one click posts the question and gets a reply", async ({ page }) => {
  await openChat(page, "en");
  await expect(page.getByTestId("logbook-chat-example-deep")).toHaveText("Why? · Ultra");
  await expect(page.getByTestId("logbook-chat-example-deep")).toHaveAttribute("title", /^Why is the boat heading/);
  await expect(page.getByTestId("logbook-chat-example-web")).toHaveText("Port news · Tavily");
  await expect(page.getByTestId("logbook-chat-example-fast")).toHaveText("Wind · Lightning");
  await expect(page.getByTestId("logbook-chat-input")).toBeVisible();
  const posted = page.waitForRequest((r) => r.url().includes("/logbook/chat") && r.method() === "POST");
  await page.getByTestId("logbook-chat-example-fast").click();
  const body = (await posted).postDataJSON();
  expect(body.question).toBe("Wind at the boat?");
  expect(body.lang).toBe("en");
  const list = page.getByTestId("logbook-chat-list");
  await expect(list).toContainText("Wind at the boat?");
  await expect(list.getByText("Logbook:")).toBeVisible({ timeout: 25_000 });
  await dismissAiChatNotice(page);
});

test("Français : la puce Ultra envoie la question en français", async ({ page }) => {
  await openChat(page, "fr");
  const posted = page.waitForRequest((r) => r.url().includes("/logbook/chat") && r.method() === "POST");
  await page.getByTestId("logbook-chat-example-deep").click();
  const body = (await posted).postDataJSON();
  expect(body.question).toMatch(/^Pourquoi le bateau/);
  expect(body.lang).toBe("fr");
  await expect(page.getByTestId("logbook-chat-input")).toHaveValue("");
});
