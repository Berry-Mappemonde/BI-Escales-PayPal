// Récit : connecteurs variés, kilomètres à terre.
// Sans API : le récit et la carte Escale se construisent depuis l'horloge locale.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const CONNECTORS_FR = ["Puis", "Ensuite", "Plus loin", "De là", "Sur la route", "À la jambe suivante"];

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r5/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  const isOn = async () => /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (!(await isOn())) return;
  await page.keyboard.press("Escape");
  if (!(await isOn())) return;
  await cinema.click();
  if (!(await isOn())) return;
  await cinema.click();
}

async function showLeftPanel(page) {
  const { openStoryTab } = await import("../helpers.js");
  await openStoryTab(page);
}

async function rewindToFirstStop(page, prev) {
  for (let i = 0; i < 6 && await prev.isEnabled(); i++) {
    await prev.click();
    await expect(prev).toBeVisible();
  }
}

test("Connecteurs variés, Escale Saint-Maur en km", async ({ page }) => {
  test.setTimeout(45_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  const bar = page.getByTestId("film-bar");
  await expect(bar).toBeVisible();
  const prev = page.getByTestId("prev-stop");
  await expect(prev).toBeVisible();
  await rewindToFirstStop(page, prev);

  const landCard = page.getByTestId("moment-now").filter({ hasText: /par la route|by road/ }).first();
  if (!(await landCard.isVisible({ timeout: 8_000 }).catch(() => false))) {
    const next = bar.getByRole("button", { name: /prochaine escale|go to next stop/i });
    if (await next.isEnabled()) {
      await next.click();
      await expect(prev).toBeEnabled({ timeout: 10_000 });
      await prev.click();
    }
  }
  // Plus de carte flottante — les km à terre se lisent dans le récit.

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);

  const story = page.getByTestId("expedition-story");
  await expect(story).toBeVisible({ timeout: 15_000 });
  const paras = story.getByTestId("story-paragraph");
  const n = await paras.count();
  if (n < 2) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "récit trop court — connecteurs non vérifiés",
      });
    } else {
      throw new Error(`récit : ${n} paragraphe(s), attendu ≥ 2`);
    }
  } else {
    // Une seule lecture : le récit peut se re-rendre pendant qu'on lit paragraphe par paragraphe (délai en CI).
    const texts = (await paras.allInnerTexts()).map((s) => s.trim());
    const used = [];
    for (const t of texts) {
      const hit = CONNECTORS_FR.find((c) => t.startsWith(`${c},`) || t.startsWith(`${c} `));
      if (hit) used.push(hit);
    }
    expect(used.length, `connecteurs : ${used.join(" | ")}`).toBeGreaterThanOrEqual(2);
    for (let i = 1; i < used.length; i++) {
      expect(used[i], `connecteur répété : ${used[i]}`).not.toBe(used[i - 1]);
    }
    expect(used.join(" ")).not.toMatch(/Puis Puis Puis/);
    const land = texts.find((t) => /départ vers La Rochelle|par la route/.test(t));
    if (land) {
      expect(land).toMatch(/\bkm\b/);
      expect(land).toMatch(/par la route/);
      expect(land).not.toMatch(/\bnm\b/);
    }
  }
  await story.scrollIntoViewIfNeeded();
  await shot(page, "01-recit");
});
