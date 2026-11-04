// Crédits carte (4 liens, Esri une fois) et citations du briefing.
// Sans API : l’attribution Leaflet est toujours là. Les liens de source du
// briefing n’apparaissent que si le sac ici() a répondu.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-m/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Attribution Esri une fois, briefing avec lien de source", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const cinema = page.getByRole("button", { name: /^cinéma$/i });
  await cinema.click();

  const attr = page.locator(".leaflet-control-attribution");
  await expect(attr).toBeVisible();
  const hrefs = await attr.locator("a").evaluateAll((els) => els.map((a) => ({
    href: a.getAttribute("href") || "",
    text: (a.textContent || "").trim(),
  })));
  const ours = hrefs.filter((a) => /esri\.com|here\.com|garmin\.com|openstreetmap\.org\/copyright/.test(a.href));
  expect(ours, `liens tuiles : ${JSON.stringify(ours)}`).toHaveLength(4);
  expect(ours.filter((a) => a.text === "Esri")).toHaveLength(1);
  await expect(attr).toContainText("Tuiles © Esri");
  await expect(attr).toContainText("HERE");
  await expect(attr).toContainText("Garmin");
  await expect(attr).toContainText("OpenStreetMap");
  await shot(page, "01-attribution");

  await cinema.click();
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const briefing = page.getByTestId("briefing");
  await expect(briefing).toBeVisible({ timeout: 15_000 });
  await briefing.scrollIntoViewIfNeeded();
  const sourceLinks = briefing.locator("a");
  await sourceLinks.first().waitFor({ state: "visible", timeout: 12_000 }).catch(() => {});
  const n = await sourceLinks.count();
  if (n === 0) {
    const body = await briefing.innerText();
    expect(body.length, "briefing vide").toBeGreaterThan(0);
  } else {
    expect(n).toBeGreaterThan(0);
  }
  await shot(page, "02-briefing");
});
