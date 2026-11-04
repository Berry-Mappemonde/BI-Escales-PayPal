// Idée n° 3 : reçu « Comment ce film a été fait » sous le film Rédigé.
// Les compteurs viennent du serveur (receipt) ; sans reçu servi, rien n'est affiché.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const RECEIPT = {
  llmCalls: 7, cacheHits: 0, ruleFallbacks: 0, webSourceCount: 0,
  models: [
    { model: "nvidia/Nemotron-3.5-Super-VL", source: "nemotron-super", tier: "write", calls: 4, cached: 0 },
    { model: "nvidia/Nemotron-3-Ultra", source: "nemotron-ultra", tier: "deep", calls: 2, cached: 0 },
    { model: "nvidia/Nemotron-3.5-Lightning", source: "nemotron-lightning", tier: "fast", calls: 1, cached: 0 },
  ],
  rewritten: 12, fallen: 1, super: 1, ultra_edit: 1, ultra_judge: 1, reviewed: true,
  reread: "pass", reread_en: "pass", lightning: 1, at: "2026-10-29T13:40:00Z",
};

const WEB_CONTEXT = {
  basis: "tavily",
  port: "La Rochelle",
  fetchedAt: "2026-10-29T13:40:00Z",
  sources: [
    { title: "Source one", domain: "one.example", url: "https://one.example/story" },
    { title: "Duplicate source", domain: "one.example", url: "https://one.example/story" },
    { title: "Source two", domain: "two.example", url: "https://two.example/story" },
    { title: "Source three", domain: "three.example", url: "https://three.example/story" },
  ],
};

function filmPayload({ written, seconds = 150, lang = "fr", receipt, webContext }) {
  return {
    status: "ready",
    lang,
    style: written ? "written" : "raw",
    hasWritten: written,
    source: written ? "nemotron-super" : "rules",
    reviewedBy: written ? "nemotron-ultra" : undefined,
    writtenAt: written ? "2026-10-29T13:40:00Z" : undefined,
    targetSeconds: seconds,
    chapters: [{ text: "Le 15 mai, Berry-Mappemonde quitte La Rochelle.", anchors: [{ t: 0, i: 0 }] }],
    ...(webContext ? { webContext } : {}),
    ...(written && receipt ? { receipt } : {}),
    ...(webContext ? { webContext } : {}),
  };
}

async function openWritten(page, lang, receipt, webContext) {
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
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filmPayload({ written, seconds, lang, receipt, webContext })),
    });
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
  await expect(page.getByTestId("film-source")).toContainText("Nemotron", { timeout: 8_000 });
}

for (const [lang, title, calls, rewritten] of [
  ["fr", "Comment ce film a été fait", "Nemotron 3.5 Super VL · Token Factory : 4 appel(s)", "Phrases réécrites par Nemotron : 12"],
  ["en", "How this film was made", "Nemotron 3.5 Super VL · Token Factory: 4 call(s)", "Sentences rewritten by Nemotron: 12"],
]) {
  test(`${lang} : le reçu du film rédigé montre les compteurs servis`, async ({ page }) => {
    test.setTimeout(90_000);
    await openWritten(page, lang, RECEIPT);
    const receipt = page.getByTestId("film-receipt");
    await expect(receipt).toBeVisible();
    await expect(receipt.locator("summary")).toHaveText(title);
    const bar = page.getByTestId("film-bar");
    const heightBefore = await bar.evaluate((el) => el.getBoundingClientRect().height);
    await receipt.locator("summary").click();
    await expect.poll(() => bar.evaluate((el) => el.getBoundingClientRect().height)).toBe(heightBefore);
    await expect.poll(() => receipt.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
    await expect.poll(() => receipt.evaluate((el) => el.getBoundingClientRect().bottom)).toBeLessThanOrEqual(
      await bar.evaluate((el) => el.getBoundingClientRect().top),
    );
    await expect(page.getByTestId("film-receipt-model")).toHaveCount(3);
    await expect(page.getByTestId("film-receipt-models")).toContainText(calls);
    await expect(page.getByTestId("film-receipt-models")).toContainText("Nemotron 3 Ultra");
    await expect(page.getByTestId("film-receipt-models")).toContainText("Nemotron 3.5 Lightning");
    await expect(page.getByTestId("film-receipt-filmReceiptRewritten")).toContainText(rewritten);
    await expect(page.getByTestId("film-receipt-filmReceiptRereadPass")).toBeVisible();
    // Aucun défaut servi : aucune ligne de défauts inventée.
    await expect(page.getByTestId("film-receipt-filmReceiptFaults")).toHaveCount(0);
  });
}

test("sans reçu servi, aucun reçu affiché", async ({ page }) => {
  test.setTimeout(90_000);
  await openWritten(page, "fr", null);
  await expect(page.getByTestId("film-receipt")).toHaveCount(0);
});

for (const [lang, expected] of [
  ["fr", "Sources web Tavily affichées avec le film : 3"],
  ["en", "Web sources from Tavily shown with the film: 3"],
]) {
  test(`${lang} : le reçu compte les sources Tavily affichées et dédupliquées`, async ({ page }) => {
    test.setTimeout(90_000);
    await openWritten(page, lang, RECEIPT, WEB_CONTEXT);
    const receipt = page.getByTestId("film-receipt");
    await expect(receipt).toBeVisible();
    await receipt.locator("summary").click();
    const tavilyLine = receipt.getByTestId("film-receipt-tavily");
    await expect(tavilyLine).toBeVisible();
    await expect(tavilyLine).toContainText(expected);
    await expect(page.getByTestId("film-web-sources").getByRole("link")).toHaveCount(3);
  });
}

test("sans sources web, le reçu ne montre pas la ligne Tavily", async ({ page }) => {
  test.setTimeout(90_000);
  await openWritten(page, "fr", RECEIPT, null);
  const receipt = page.getByTestId("film-receipt");
  await expect(receipt).toBeVisible();
  await receipt.locator("summary").click();
  await expect(receipt.getByTestId("film-receipt-tavily")).toHaveCount(0);
});

// R45 : le reçu compte les sources AFFICHÉES (dédoublonnées, 3 au plus), jamais un
// webSourceCount serveur. Quatre lignes servies dont deux URL en double → 2 liens, « 2 ».
const WEB_CONTEXT_DUP = {
  basis: "tavily",
  port: "La Rochelle",
  fetchedAt: "2026-10-29T13:40:00Z",
  sources: [
    { title: "La Rochelle — Noonsite", url: "https://www.noonsite.com/place/france/la-rochelle/", domain: "noonsite.com" },
    { title: "doublon", url: "https://noonsite.com/place/france/la-rochelle" },
    { title: "Port de La Rochelle", url: "https://www.larochelle-port.fr/", domain: "larochelle-port.fr" },
    { title: "doublon 2", url: "https://www.larochelle-port.fr/" },
  ],
};

test("R45 : nombre de liens Tavily = nombre du reçu, doublons retirés", async ({ page }) => {
  test.setTimeout(90_000);
  await openWritten(page, "fr", { ...RECEIPT, webSourceCount: 10 }, WEB_CONTEXT_DUP);
  const web = page.getByTestId("film-web-sources");
  await expect(web.getByRole("link")).toHaveCount(2);
  const receipt = page.getByTestId("film-receipt");
  await receipt.locator("summary").click();
  const tavilyLine = page.getByTestId("film-receipt-tavily");
  await expect(tavilyLine).toContainText("Sources web Tavily affichées avec le film : 2");
  await expect(tavilyLine).not.toContainText("10");
});

test("R45 : en mode Brut, ni liste Tavily ni reçu", async ({ page }) => {
  test.setTimeout(90_000);
  await openWritten(page, "fr", RECEIPT, WEB_CONTEXT_DUP);
  await expect(page.getByTestId("film-web-sources")).toBeVisible();
  await page.getByTestId("film-style-raw").click();
  await expect(page.getByTestId("film-web-sources")).toHaveCount(0);
  await expect(page.getByTestId("film-receipt")).toHaveCount(0);
});

test("R45 : film rédigé sans contexte web, aucune liste ni ligne Tavily", async ({ page }) => {
  test.setTimeout(90_000);
  await openWritten(page, "fr", RECEIPT, null);
  await expect(page.getByTestId("film-web-sources")).toHaveCount(0);
  await page.getByTestId("film-receipt").locator("summary").click();
  await expect(page.getByTestId("film-receipt-tavily")).toHaveCount(0);
});
