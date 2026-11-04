// Avis du journal ouvert : la réponse reste lisible. Avant, l'avis vivait dans le cadre du chat
// (168 px fixes) et écrasait la liste des messages à 0 px jusqu'à « Compris ».
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showLeftPanel } from "../helpers.js";

const ANSWER = "Wind 14 kn from the north-east, sea 1.2 m.";

async function askWithNoticeOpen(page, lang) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await page.route("**/logbook/chat", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ answer: ANSWER, status: "ready", logged: false, engine: "facts", t: new Date().toISOString() }),
  }));
  await page.goto("/");
  await dismissNotForNav(page);
  await showLeftPanel(page);
  const input = page.getByTestId("logbook-chat-input");
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.fill("What is the wind?");
  await input.press("Enter");
  await expect(page.getByTestId("logbook-chat-list")).toContainText(ANSWER);
  await expect(page.getByTestId("logbook-chat-ai-notice")).toBeVisible();
}

/** Part visible de `inner` dans `outer`, en px (0 = masqué par le cadre). */
async function visibleHeightIn(inner, outer) {
  const a = await inner.boundingBox();
  const b = await outer.boundingBox();
  if (!a || !b) return 0;
  return Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
}

for (const lang of ["en", "fr"]) {
  test(`${lang}: the answer stays readable while the AI notice is open`, async ({ page }) => {
    await askWithNoticeOpen(page, lang);
    const box = page.getByTestId("logbook-chat");
    const list = page.getByTestId("logbook-chat-list");
    const listH = await list.evaluate((el) => el.clientHeight);
    expect(listH, "message list height").toBeGreaterThanOrEqual(48);
    const answer = list.locator("div", { hasText: ANSWER }).last();
    expect(await visibleHeightIn(answer, list), "answer visible in the list").toBeGreaterThan(10);
    // Le cadre garde ses 168 px ; l'avis, dessous, est entier et cliquable (ni coupé ni recouvert).
    expect(Math.round((await box.boundingBox()).height)).toBe(168);
    const input = page.getByTestId("logbook-chat-input");
    expect(await visibleHeightIn(input, box), "input inside the chat box").toBeGreaterThanOrEqual((await input.boundingBox()).height - 1);
    for (const id of ["logbook-chat-ai-notice", "logbook-chat-ai-notice-dismiss"]) {
      // Sondé : le panneau gauche glisse encore à l'ouverture.
      await expect.poll(() => page.getByTestId(id).evaluate((el) => {
        const r = el.getBoundingClientRect();
        const hit = (x, y) => el.contains(document.elementFromPoint(x, y));
        return r.height > 0 && hit(r.left + 4, r.top + 4) && hit(r.right - 4, r.bottom - 4);
      }), { message: `${id} fully shown` }).toBe(true);
    }
    // « Compris » rend au cadre sa hauteur d'origine.
    await page.getByTestId("logbook-chat-ai-notice-dismiss").click();
    await expect(page.getByTestId("logbook-chat-ai-notice")).toHaveCount(0);
    expect(Math.round((await box.boundingBox()).height)).toBe(168);
  });
}
