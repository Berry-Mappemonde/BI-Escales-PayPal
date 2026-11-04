// Veille Tavily : carte FREE news de fixture (lien + data-kind).
// Sans API / sans clés : on injecte une carte FREE. La recette réelle
// (Suivre, prochaine escale, phrase Tavily) demande TAVILY_API_KEY
// et NEBIUS_API_KEY sur le VPS.
import { expect, test } from "@playwright/test";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l4/${name}.webp`,
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

test("Carte news de fixture : data-kind=news et un lien", async ({ page }) => {
  // 28 sept. : ce n'est PAS une question de clés. Depuis R8c (plus de pop-up sur la carte), les composants qui
  // portaient la carte de veille (moment-free / news) — MomentNowCard / FreeMomentBlock, et leur fixture window.__naviguide*Fixture — ne sont plus
  // rendus nulle part (IciMaintenant utilise CardAlias, sans badge ni fixture). À trancher par le porteur : un changement pour
  // remettre la carte de veille (moment-free / news) dans le panneau, ou la suppression de ce spec. En attendant, ignoré partout, honnêtement.
  test.skip(true, "R8c : la carte de veille (moment-free / news) n'est plus rendu — décision à prendre (remettre, ou supprimer ce spec)");
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  const { showLeftPanel } = await import("../helpers.js");
  await showLeftPanel(page);

  await page.evaluate(() => {
    window.__naviguideNewsFixture = {
      key: "fixture:news-l4",
      kind: "news",
      type: "news",
      severity: "info",
      title: "Nouméa · veille du 20 sept.",
      text: "Travaux annoncés à la marina de Motu Uta (portautonome.nc).",
      entity: {
        kind: "escale",
        name: "Nouméa",
        url: "https://www.portautonome.nc/avis",
        lat: -22.2758,
        lon: 166.4483,
      },
    };
    window.dispatchEvent(new Event("naviguide-news-fixture"));
  });

  const card = page.getByTestId("moment-free");
  await expect(card).toHaveAttribute("data-kind", "news");
  const link = page.getByTestId("moment-link-site");
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", /portautonome\.nc/);
  await expect(card).toContainText(/Nouméa/);
  await expect(card).toContainText(/veille/i);
  await shot(page, "01-veille");
});
