// Libellés du parcours décrit dans le README (ouverture anglaise).
// GET /voyage/official est sondé. S'il ne répond pas, les assertions qui
// en dépendent sont annotées puis sautées. Celles qui n'en dépendent pas restent.
import { test, expect } from "@playwright/test";
import { dismissNotForNav, showLeftPanel, showRightPanel } from "../helpers.js";

test.use({ storageState: { cookies: [], origins: [] } });

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/rm1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("parcours README : EN, Suivre, journal, tracer", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — /ici/warm/status non exigé",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  const follow = page.getByTestId("view-suivre");
  await expect(follow).toHaveText("Follow expedition");
  await follow.click();
  await shot(page, "01-en-follow");

  await showRightPanel(page);
  const en = page.getByTestId("lang-en");
  await expect(en).toHaveText("EN");
  await en.click();
  await expect(follow).toHaveText("Follow expedition");

  await showLeftPanel(page);
  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 15_000 });
  await expect(chat).toContainText("Logbook — ask a question");
  await expect(page.getByTestId("logbook-chat-input")).toHaveAttribute(
    "placeholder",
    "Wind at the boat? Next stop?",
  );
  await expect(page.getByTestId("logbook-chat-send")).toHaveAttribute("title", "Send");
  const draw = page.getByRole("button", { name: /Draw your own route/ }).first();
  await expect(draw).toBeVisible();
  await shot(page, "02-journal-tracer");

  const start = page.getByTestId("replay-start");
  await expect(start).toContainText("Replay the expedition", { timeout: 20_000 });
  if (await start.isDisabled()) {
    await expect(start).toHaveAttribute("title", "preparing");
  }
  await expect(page.getByTestId("film-style-raw")).toHaveText("Raw");
  const edited = page.getByTestId("film-style-written");
  await expect(edited).toHaveText("Edited");
  if (await edited.isDisabled()) {
    await expect(edited).toHaveAttribute("title", "not yet written for this duration");
  }

  if (!apiUp) return;

  const warm = await page.request.get("/ici/warm/status", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (warm && warm.llm && Object.prototype.hasOwnProperty.call(warm.llm, "lastSourceByTier")) {
    expect(warm.llm.lastSourceByTier).toEqual(expect.any(Object));
  }
});
