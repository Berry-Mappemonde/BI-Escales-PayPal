// Plus jamais de prompt (fiche d'escale, journal), même depuis le cache.
// Sans API : titre de fiche, drapeau, journal tiennent seuls. Le paragraphe
// et la réponse du chat sont sondés via GET /voyage/official.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LEAK = /Input:\s|^\s*Task:\s|\bTask:\s|What's for the boat|large JSON object|Analyze User Input|Thinking OFF|You are the logbook|Tu es le journal de bord/i;

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

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

async function openPointeAPitreFlag(page) {
  await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Pointe-à-Pitre/i.test(marker._naviguideWaypoint?.name || "")) return true;
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
      if (!/Pointe-à-Pitre/i.test(marker._naviguideWaypoint?.name || "")) continue;
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
  expect(fired, "drapeau Pointe-à-Pitre").toBeTruthy();
}

test("Fiche et journal sans prompt, même depuis le cache", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — paragraphe traduit et réponse du journal non vérifiés",
    });
  }

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

  await openPointeAPitreFlag(page);

  const sheet = page.getByTestId("escale-sheet");
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  await expect(sheet).toContainText("Port of call sheet");
  await expect(sheet).toContainText(/Pointe-à-Pitre/i);
  await expect(sheet).not.toContainText(LEAK);

  if (apiUp) {
    await expect(sheet).not.toContainText(/Gathering what we know|On rassemble/i, { timeout: 20_000 });
    const sheetText = await sheet.innerText();
    expect(sheetText, "fiche : pas de prompt").not.toMatch(LEAK);
    expect(sheetText, "fiche : pas le mot JSON").not.toMatch(/\bJSON\b/);
    expect(sheetText).toMatch(/[A-Za-zÀ-ÿ]{6,}/);
  }
  await shot(page, "01-fiche");

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
    await expect.poll(async () => {
      if (await page.getByTestId("chat-source").count()) return "ready";
      const t = await list.innerText();
      if (/could not answer|does not hold|n.a pas pu|n.a pas cette/i.test(t)) return "done";
      return "wait";
    }, { timeout: 20_000 }).not.toBe("wait");
    const chatText = await list.innerText();
    expect(chatText, "chat : pas de prompt").not.toMatch(LEAK);
    expect(chatText, "chat : pas le mot JSON").not.toMatch(/\bJSON\b/);
    expect(chatText.length, "chat : une phrase").toBeGreaterThan(10);

    await input.fill("À quelle vitesse va le bateau ?");
    await input.press("Enter");
    await expect.poll(async () => {
      const t = await list.innerText();
      const n = (t.match(/À quelle vitesse va le bateau/g) || []).length;
      return n >= 2 ? "asked-twice" : "wait";
    }, { timeout: 20_000 }).toBe("asked-twice");
    const again = await list.innerText();
    expect(again, "chat (2e fois) : pas de prompt").not.toMatch(LEAK);
    expect(again, "chat (2e fois) : pas le mot JSON").not.toMatch(/\bJSON\b/);
  }
  await expect(chat).not.toContainText(LEAK);
  await showLeftPanel(page);
  await expect(page.getByTestId("logbook-chat")).toBeVisible();
});
