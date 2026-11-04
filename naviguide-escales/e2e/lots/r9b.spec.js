// Vue Journal (date · position · changement), clic → curseur.
// Sans API : l'onglet Journal et la liste tiennent seuls (repli local).
// GET /voyage/official : sondé ; s'il manque, on annote et on saute seulement
// les assertions d'entrées officielles (15 mai → aujourd'hui).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r9b/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function localJournalSeed() {
  const t0 = new Date();
  t0.setUTCHours(8, 0, 0, 0);
  const later = new Date(t0.getTime() + 14 * 86400000);
  return [
    {
      voyageId: "local",
      seq: 0,
      t: t0.toISOString(),
      pos: { lat: 46.81, lon: 1.64 },
      signature: "r9b-seed-0",
      changes: [],
    },
    {
      voyageId: "local",
      seq: 1,
      t: later.toISOString(),
      pos: { lat: 41.92, lon: 8.74 },
      signature: "r9b-seed-1",
      changes: [{ kind: "escale", score: 3, title: "Ajaccio", fact: "" }],
    },
  ];
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible().catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

test("Journal : liste, clic place le curseur", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — entrées officielles 15 mai → aujourd'hui non exigées",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.addInitScript(({ key, seed }) => {
    try {
      localStorage.setItem(key, JSON.stringify(seed));
    } catch {
      /* ignore */
    }
  }, { key: "naviguide.moment-journal.v1.simulation:official", seed: localJournalSeed() });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await showLeftPanel(page);

  const box = page.getByTestId("ici-maintenant");
  await expect(box).toBeVisible({ timeout: 15_000 });
  const { openJournalTab } = await import("../helpers.js");
  await openJournalTab(page);
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();
  await expect(page.getByTestId("ici-journal-list")).toBeAttached();
  await expect(box.getByText(/Le journal commence|Écrit par le serveur|cliquez pour/i)).toHaveCount(0);

  const simEntries = page.getByTestId("ici-journal-entry");
  const keepJournalOpen = async () => {
    const tab = page.getByTestId("ici-tab-journal");
    if ((await tab.getAttribute("aria-selected")) !== "true") {
      await tab.evaluate((el) => el.click());
    }
  };
  if (apiUp) {
    // L'horloge live à quai ouvre la fiche d'escale → onglet Maintenant.
    // On refrappe Journal tant que la liste n'a pas de lignes.
    await expect(page.getByTestId("film-clock-line")).not.toHaveText(/\bj0\b/, { timeout: 25_000 }).catch(() => {});
    await expect.poll(async () => {
      await keepJournalOpen();
      return simEntries.count();
    }, { timeout: 20_000 }).toBeGreaterThan(0);
  }
  const hasEntry = await simEntries.first().isVisible({ timeout: 5_000 }).catch(() => false)
    || (await simEntries.count()) > 0;
  if (!hasEntry && !apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "journal local vide — clic curseur sauté",
    });
    await shot(page, "01-journal");
    return;
  }
  expect(hasEntry, "journal listable (stock figé / seed local)").toBeTruthy();
  const simCount = await simEntries.count();
  expect(simCount).toBeGreaterThanOrEqual(1);
  const firstSim = (await simEntries.first().innerText()).trim();
  const lastSim = (await simEntries.nth(simCount - 1).innerText()).trim();
  expect(firstSim.length).toBeGreaterThan(0);
  expect(lastSim.length).toBeGreaterThan(0);

  await keepJournalOpen();
  const clockBefore = (await page.getByTestId("film-clock-line").innerText().catch(() => "")) || "";
  const nmBefore = await page.evaluate(() => window.__naviguideScene?.playback?.state?.nm ?? null);
  const seekTarget = page.getByTestId("ici-journal-entry").filter({ hasText: /Ajaccio/i }).first();
  if (await seekTarget.isVisible().catch(() => false)) {
    await seekTarget.click();
  } else {
    await simEntries.nth(Math.min(simCount - 1, 1)).click();
  }
  if (clockBefore.trim()) {
    await expect(page.getByTestId("film-clock-line")).not.toHaveText(clockBefore, { timeout: 8_000 });
  } else if (nmBefore != null) {
    await expect.poll(async () => page.evaluate(() => window.__naviguideScene?.playback?.state?.nm ?? null), { timeout: 8_000 })
      .not.toBe(nmBefore);
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await page.getByTestId("ici-tab-journal").evaluate((el) => el.click());
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();

  if (apiUp) {
    const official = await page.request.get("/voyage/official/moments", { timeout: 8_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(official && Array.isArray(official.moments) && official.moments.length, "moments du stock figé listables").toBeTruthy();
    const officialEntries = page.getByTestId("ici-journal-entry");
    await expect(officialEntries.first()).toBeAttached({ timeout: 20_000 });
    await expect(officialEntries.first()).not.toContainText("Marina Bas-du-Fort", { timeout: 15_000 });
    const n = await officialEntries.count();
    expect(n).toBeGreaterThanOrEqual(1);
    const firstText = await officialEntries.first().innerText();
    expect(firstText).toMatch(/\d+ (janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i);
    const mid = officialEntries.nth(Math.min(Math.max(n - 1, 0), 3));
    const clock0 = (await page.getByTestId("film-clock-line").innerText().catch(() => "")) || "";
    await mid.click();
    if (clock0.trim()) {
      await expect(page.getByTestId("film-clock-line")).not.toHaveText(clock0, { timeout: 10_000 });
    }
  }

  if (!apiUp) {
    await page.getByTestId("view-tracer").click();
    await showLeftPanel(page);
    await page.getByTestId("ici-tab-journal").evaluate((el) => el.click());
    await expect(page.getByTestId("ici-journal-entry").first()).toBeAttached({ timeout: 10_000 });
  }
  await shot(page, "01-journal");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
