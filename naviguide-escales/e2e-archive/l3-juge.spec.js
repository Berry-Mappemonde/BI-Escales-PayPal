// Juge de vérité : badge + texte barré (carte de fixture).
// Sans API / sans clés : on injecte une carte NOW avec truth.unsupported.
// La recette réelle (Simulation, ZEE Martinique) demande TAVILY_API_KEY
// et NEBIUS_API_KEY sur le VPS.
import { expect, test } from "@playwright/test";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function dismissNotForNav(page) {
  const ok = page.getByRole("button", { name: /compris|j.ai compris|ok|continuer|accepter/i }).first();
  if (await ok.isVisible({ timeout: 3000 }).catch(() => false)) {
    const ack = page.getByTestId("not-for-nav-ack");
    if (await ack.isVisible().catch(() => false)) await ack.check();
    await ok.click();
  }
}

async function hideSidebarForFloatingCard(page) {
  const cinema = page.getByRole("button", { name: /^cinéma$/i });
  const chat = page.getByTestId("logbook-chat");
  if (await chat.isVisible().catch(() => false) && await cinema.isVisible().catch(() => false)) {
    await cinema.click();
  }
}

test("Truth-badge et texte barré sur une carte de fixture", async ({ page }) => {
  // 28 sept. : ce n'est PAS une question de clés. Depuis R8c (plus de pop-up sur la carte), les composants qui
  // portaient le badge du juge (truth-badge) — MomentNowCard / FreeMomentBlock, et leur fixture window.__naviguide*Fixture — ne sont plus
  // rendus nulle part (IciMaintenant utilise CardAlias, sans badge ni fixture). À trancher par le porteur : un changement pour
  // remettre le badge du juge (truth-badge) dans le panneau, ou la suppression de ce spec. En attendant, ignoré partout, honnêtement.
  test.skip(true, "R8c : le badge du juge (truth-badge) n'est plus rendu — décision à prendre (remettre, ou supprimer ce spec)");
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  const { showLeftPanel } = await import("../helpers.js");
  await showLeftPanel(page);

  await page.evaluate(() => {
    window.__naviguideTruthFixture = {
      key: "fixture:truth-l3",
      kind: "poe",
      type: "poe-ahead",
      severity: "info",
      title: "Port d’entrée Fort-de-France (Gold)",
      text: "Port d'entrée Fort-de-France (Gold). Visa 90 jours.",
      truth: {
        status: "verified",
        checkedAt: "2026-09-20T12:00:00Z",
        unsupported: ["Visa 90 jours"],
      },
      entity: null,
    };
    window.dispatchEvent(new Event("naviguide-truth-fixture"));
  });

  const badge = page.getByTestId("truth-badge");
  await expect(badge).toContainText(/Tavily|Nemotron|Vérifié|Checked/i);
  const struck = page.locator("s, .line-through");
  await expect(struck.first()).toBeVisible();
  await expect(struck.first()).toContainText(/Visa 90 jours/);
  await shot(page, "01-badge");
});
