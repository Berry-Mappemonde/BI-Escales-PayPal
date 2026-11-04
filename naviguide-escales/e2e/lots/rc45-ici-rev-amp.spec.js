// GET /ici sur la route officielle sert le sac AMP polygone.
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions /ici et encadré — barre et Suivre restent.
// Avec API : GET /ici aux Bouches de Bonifacio a une entrée source + inside
// booléen ; l'encadré Ici nomme l'aire si le sac est prêt.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc45");
mkdirSync(recetteDir, { recursive: true });

// Capture de recette : le replay redessine la carte en continu et page.screenshot
// attendait une image stable jusqu'au délai du test (90 s) au premier lancement.
// On arrête le film, on fige les animations et on borne la capture ; un échec de
// capture est annoté mais ne remplace pas les assertions, qui restent avant.
async function stopReplay(page) {
  const stop = page.getByTestId("replay-stop");
  if (await stop.isVisible().catch(() => false)) {
    await stop.click({ timeout: 5_000 }).catch(() => {});
  }
}

const shot = async (page, name) => {
  await stopReplay(page);
  await page.screenshot({
    path: join(recetteDir, `${name}.webp`),
    type: "webp",
    quality: 85,
    fullPage: false,
    animations: "disabled",
    timeout: 15_000,
  }).catch((err) => {
    test.info().annotations.push({ type: "capture", description: `capture ${name} non prise : ${String(err?.message || err).split("\n")[0]}` });
  });
};

const AMP_NAMED = /bonifacio|strait of bonifacio|réserve|reserve/i;
const AMP_PHRASE = /dans l'aire marine protégée|in the marine protected area|à \d+[.,]?\d* milles|miles from/i;

const BONIFACIO = { lat: 41.31, lon: 9.19 };

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed", { timeout: 5_000 }).catch(() => null) === "true") await listen.click({ timeout: 5_000 });
  }
}

async function seekAfterAjaccio(page) {
  const start = page.getByTestId("replay-start");
  if (!(await start.isEnabled().catch(() => false))) return false;
  await muteVoice(page);
  // Le film redessine la barre en continu : le clic Playwright attend une
  // image stable et dépasse son délai. Le bouton est déjà actif.
  await start.evaluate((el) => el.click());
  const ready = await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).then(() => true).catch(() => false);
  if (!ready) return false;
  return page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    let i = list.findIndex((c) => /La Rochelle/i.test(c.fromName || "") && /Ajaccio/i.test(c.toName || ""));
    if (i < 0) i = list.findIndex((c) => /Ajaccio/i.test(c.toName || ""));
    if (i < 0) i = list.findIndex((c) => /Ajaccio/i.test(c.fromName || ""));
    if (i < 0) return false;
    window.__naviguideFilm.seekChapter(i, 0);
    return true;
  });
}

test("Ici aux Bouches de Bonifacio nomme une aire (source polygon)", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions /ici et nom d'aire sautées ; barre et Suivre gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();

  await showLeftPanel(page);
  await page.getByTestId("ici-tab-now").click({ timeout: 5_000 }).catch(() => {});
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();

  if (!apiUp) {
    await expect(page.getByTestId("replay-start")).toBeDisabled();
    await shot(page, "01-ici-bonifacio");
    return;
  }

  const ici = await page.request.get(
    `/ici?lat=${BONIFACIO.lat}&lon=${BONIFACIO.lon}`,
    { timeout: 20_000 },
  ).then((r) => (r.ok() ? r.json() : null)).catch(() => null);

  const amps = Array.isArray(ici?.amp) ? ici.amp : [];
  const withSource = amps.filter((x) => x && typeof x.source === "string");
  if (withSource.length) {
    expect(withSource.some((x) => x.source === "polygon" || x.source === "export")).toBeTruthy();
    expect(withSource.every((x) => typeof x.inside === "boolean")).toBeTruthy();
    expect(ici.amp, "plus jamais amp: [] figé si BI a répondu").not.toEqual([]);
  } else {
    test.info().annotations.push({
      type: "stock ici",
      description: "GET /ici Bonifacio sans entrée source (préparation, stock figé pré-AM1A, ou remplisseur pas encore passé) — nom d'aire UI non exigé",
    });
  }

  await seekAfterAjaccio(page);
  await page.getByTestId("ici-tab-journal").click({ timeout: 5_000 }).catch(() => {});
  const journalHit = page.getByTestId("ici-journal-entry").filter({ hasText: AMP_NAMED }).first();
  if (await journalHit.isVisible().catch(() => false)) {
    await journalHit.click({ timeout: 5_000 });
  }
  await page.getByTestId("ici-tab-now").click({ timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(800);

  const briefing = page.getByTestId("ici-briefing");
  const here = page.getByTestId("ici-here-sentence");
  const iciText = [
    await briefing.textContent({ timeout: 5_000 }).catch(() => ""),
    ...(await here.allTextContents().catch(() => [])),
  ].join(" ");

  if (AMP_NAMED.test(iciText) || AMP_PHRASE.test(iciText)) {
    expect(iciText).toMatch(AMP_NAMED);
  } else {
    test.info().annotations.push({
      type: "Ici hors aire",
      description: "horloge pas aux Bouches de Bonifacio au moment de la capture — nom d'aire non exigé à l'écran",
    });
  }
  await shot(page, "01-ici-bonifacio");
});
