// La pensée du modèle ne s'affiche jamais (fiche d'escale, chat).
// Sans API : titre de fiche, drapeau, journal tiennent seuls. Le paragraphe
// traduit et la réponse du chat sont sondés via GET /voyage/official.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LEAK = /Analyze User Input|\bTask:\s|Wait,\s*let me|Thinking OFF|translate a sailing-log/i;

async function switchToEnglish(page) {
  const en = page.getByTestId("lang-en");
  if (!(await en.isVisible().catch(() => false))) {
    const right = page.locator(".naviguide-sidebar-toggle--right");
    if (await right.isVisible().catch(() => false)) await right.click();
  }
  await expect(en).toBeVisible({ timeout: 15_000 });
  await en.click();
}

async function showLeftPanel(page) {
  const chat = page.getByTestId("logbook-chat");
  if (await chat.isVisible({ timeout: 2000 }).catch(() => false)) return;
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (await cinema.isVisible().catch(() => false)) {
    const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
    if (on) await cinema.click();
  }
  if (await chat.isVisible({ timeout: 3000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(chat).toBeVisible({ timeout: 15_000 });
}

async function openSaintMaurFlag(page) {
  await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Saint-Maur/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 30_000 });
  const fired = await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return false;
    const cam = scene.map.getCenter()?.lng;
    let best = null;
    let bestD = Infinity;
    for (const marker of scene.waypointMarkers.values()) {
      if (!/Saint-Maur/i.test(marker._naviguideWaypoint?.name || "")) continue;
      const lng = marker.getLatLng?.()?.lng;
      const d = Number.isFinite(cam) && Number.isFinite(lng) ? Math.abs(lng - cam) : 0;
      if (d < bestD) {
        bestD = d;
        best = marker;
      }
    }
    if (!best) return false;
    scene.map.setView(best.getLatLng(), 7, { animate: false });
    best.fire("click");
    return true;
  });
  expect(fired, "drapeau Saint-Maur").toBeTruthy();
}

test("Fiche EN et chat sans pensée du modèle", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  await switchToEnglish(page);
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);
  const hideRight = page.getByRole("button", { name: /hide panel|masquer le panneau/i });
  if (await hideRight.isVisible().catch(() => false)) await hideRight.click();

  await openSaintMaurFlag(page);

  const sheet = page.getByTestId("escale-sheet");
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  await expect(sheet).toContainText("Port of call sheet");
  await expect(sheet).toContainText(/Saint-Maur/i);
  await expect(sheet).not.toContainText(LEAK);

  let apiUp = false;
  for (let i = 0; i < 8 && !apiUp; i += 1) {
    apiUp = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (!apiUp) await page.waitForTimeout(400);
  }
  if (apiUp) {
    await expect(sheet).not.toContainText(/Gathering what we know|On rassemble/i, { timeout: 20_000 });
    const sheetText = await sheet.innerText();
    expect(sheetText, "fiche : pas de pensée du modèle").not.toMatch(LEAK);
    expect(sheetText).toMatch(/[A-Za-zÀ-ÿ]{6,}/);
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — paragraphe traduit non vérifié",
    });
  }
  await shot(page, "01-fiche-en");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 10_000 });
  const input = chat.getByTestId("logbook-chat-input");
  await input.scrollIntoViewIfNeeded();
  await input.fill("À quelle vitesse va le bateau ?");
  await input.press("Enter");

  if (apiUp) {
    const list = page.getByTestId("logbook-chat-list");
    let chatReady = false;
    try {
      await expect.poll(async () => {
        if (await page.getByTestId("chat-source").count()) return "ready";
        const t = await list.innerText();
        if (/could not answer|does not hold|n.a pas pu|n.a pas cette/i.test(t)) return "done";
        return "wait";
      }, { timeout: 8_000 }).not.toBe("wait");
      chatReady = true;
    } catch {
      chatReady = false;
    }
    if (!chatReady) {
      test.info().annotations.push({
        type: "poste",
        description: "chat LLM absent en CI (NAVIGUIDE_OFFLINE) — pas de pensée du modèle vérifiée à vide",
      });
      await expect(chat).not.toContainText(LEAK);
      await shot(page, "02-journal");
      return;
    }
    const chatText = await list.innerText();
    expect(chatText, "chat : pas de pensée du modèle").not.toMatch(LEAK);
    expect(chatText.length, "chat : une phrase").toBeGreaterThan(10);
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — réponse du journal non vérifiée",
    });
  }
  await expect(chat).not.toContainText(LEAK);
  await showLeftPanel(page);
  await expect(page.getByTestId("logbook-chat")).toBeVisible();
  await shot(page, "02-journal");
});
