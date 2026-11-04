// À 390 px, le libellé « Contenu généré par IA (modèle : …) » de la barre du
// film tient en entier, en français comme en anglais (il passe à la ligne).
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

function filmPayload({ written, seconds = 150, lang = "fr" }) {
  return {
    status: "ready",
    lang,
    style: written ? "written" : "raw",
    hasWritten: written,
    source: written ? "nemotron-super-token-factory" : "rules",
    writtenAt: written ? "2026-10-17T10:00:00Z" : undefined,
    targetSeconds: seconds,
    chapters: [{ text: "Le 15 mai, Berry-Mappemonde quitte La Rochelle.", anchors: [{ t: 0, i: 0 }] }],
  };
}

for (const [lang, prefix] of [["fr", "Contenu généré par IA"], ["en", "AI-generated content"]]) {
  test(`390 px, ${lang} : le libellé IA de la barre du film n'est pas tronqué`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
    const cached = new Set();
    await page.route("**/voyage/**/film**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const style = url.searchParams.get("style") || "raw";
      const seconds = Number(url.searchParams.get("seconds") || 0);
      const key = `${url.searchParams.get("lang") || lang}:${seconds}`;
      if (req.method() === "POST") cached.add(key);
      const written = req.method() === "POST" || (style === "written" && cached.has(key));
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(filmPayload({ written, seconds, lang })) });
    });
    const official = await probeOfficial(page);
    await page.goto("/");
    await dismissNotForNav(page);
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
    test.skip(!official, "GET /voyage/official absent : pas de film à rédiger");
    await leaveCinema(page);
    await page.getByTestId("view-suivre").click();
    const written = page.getByTestId("film-style-written");
    await expect(written).toBeEnabled({ timeout: 15_000 });
    await written.click();
    const source = page.getByTestId("film-source");
    await expect(source).toContainText(prefix, { timeout: 8_000 });
    await expect(source).toContainText("Nemotron 3.5 Super VL");
    const label = source.locator("span").first();
    const fit = await label.evaluate((el) => {
      const clip = el.closest(".naviguide-film-bar") || document.documentElement;
      const box = el.getBoundingClientRect();
      const frame = clip.getBoundingClientRect();
      const nodes = [el, el.parentElement, el.closest("[data-testid='film-source']")];
      return {
        text: el.textContent,
        overflow: nodes.map((n) => n.scrollWidth - n.clientWidth),
        inside: box.left >= frame.left - 0.5 && box.right <= frame.right + 0.5
          && box.top >= frame.top - 0.5 && box.bottom <= frame.bottom + 0.5,
        inViewport: box.left >= 0 && box.right <= window.innerWidth,
      };
    });
    expect(fit.text).toContain("Nemotron 3.5 Super VL");
    for (const extra of fit.overflow) expect(extra, `débordement : ${JSON.stringify(fit)}`).toBeLessThanOrEqual(0);
    expect(fit.inside, `boîte coupée par la barre : ${JSON.stringify(fit)}`).toBe(true);
    expect(fit.inViewport).toBe(true);
  });
}
