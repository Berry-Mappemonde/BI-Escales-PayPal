// Pendant Revoir, le bateau est au lieu que la phrase nomme.
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions phrase/bateau — barre et Revoir gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart, waitFilmReady } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc52");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FDF = { lat: 14.59, lon: -61.07 };
const PAPEETE = { lat: -17.54, lon: -149.57 };

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

function near(a, b, deg = 2.5) {
  if (!a || !b) return false;
  if (![a.lat, a.lon, b.lat, b.lon].every(Number.isFinite)) return false;
  let dLon = a.lon - b.lon;
  while (dLon > 180) dLon -= 360;
  while (dLon < -180) dLon += 360;
  return Math.hypot(a.lat - b.lat, dLon) < deg;
}

test("Au sous-titre Cape Verde / Coiba le bateau n'est pas à l'arrivée", async ({ page }) => {
  test.setTimeout(120_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions phrase/bateau sautées ; barre et Revoir gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("replay-departure")).toBeVisible();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await shot(page, "01-phrase-et-bateau");
    return;
  }

  const canPlay = await waitFilmReady(page, 45_000).then(() => true).catch(() => waitFilmCanStart(page, 10_000));
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-phrase-et-bateau");
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 10_000 });
  const pill150 = page.getByTestId("film-duration").locator("[data-seconds='150']");
  if (await pill150.isVisible().catch(() => false)) {
    if (await pill150.getAttribute("aria-pressed") !== "true") await pill150.click();
  }

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 20_000 });

  const sought = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const find = (placeRe, fromRe, toRe) => {
      const blob = (c) => `${c.fromName || ""} ${c.toName || ""} ${c.text || ""}`;
      let i = list.findIndex((c) => fromRe.test(`${c.fromName || ""}`)
        && toRe.test(`${c.toName || ""}`)
        && placeRe.test(`${c.text || ""}`));
      if (i < 0) i = list.findIndex((c) => placeRe.test(blob(c)));
      if (i < 0) {
        i = list.findIndex((c) => fromRe.test(`${c.fromName || ""}`) && toRe.test(`${c.toName || ""}`));
      }
      if (i < 0) return null;
      const text = String(list[i].text || "");
      const place = text.match(placeRe);
      const at = place ? text.indexOf(place[0]) : Math.max(1, Math.floor(text.length / 2));
      return { i, at: at >= 0 ? at + (place ? 1 : 0) : Math.floor(text.length / 2), text };
    };
    return {
      cape: find(/Cape Verde|Cap-Vert|Cabo Verde/i, /Ajaccio/i, /Fort-de-France|Martinique/i),
      coiba: find(/Coiba|Cordillera/i, /Cayenne/i, /Papeete|Polynésie/i),
    };
  });

  if (!sought.cape) {
    test.info().annotations.push({
      type: "chapitre absent",
      description: "Ajaccio → Fort-de-France / Cape Verde absent — phrase/bateau non mesuré",
    });
    await shot(page, "01-phrase-et-bateau");
    return;
  }

  await page.evaluate(({ i, at }) => window.__naviguideFilm?.seekChapter?.(i, at), sought.cape);
  await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
    sought.cape.i, { timeout: 10_000 });
  await expect.poll(async () => page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    return Number.isFinite(Number(f.lat)) && Number.isFinite(Number(f.lon));
  }), { timeout: 8_000 }).toBe(true);

  const capeFilm = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    return {
      lat: Number(f.lat),
      lon: Number(f.lon),
      subtitle: String(f.subtitle || ""),
      charIdx: Number(f.charIdx) || 0,
      ended: Boolean(f.ended),
    };
  });
  expect(capeFilm.ended, "le film ne doit pas être fini au milieu du chapitre").toBe(false);
  expect(Number.isFinite(capeFilm.lat) && Number.isFinite(capeFilm.lon), "position publiée").toBe(true);
  expect(
    near({ lat: capeFilm.lat, lon: capeFilm.lon }, FDF),
    `Cape Verde : bateau déjà à Fort-de-France (${capeFilm.lat}, ${capeFilm.lon})`,
  ).toBe(false);
  expect(capeFilm.lon, "Cape Verde : plus à l'est que la Martinique").toBeGreaterThan(-50);
  await expect(page.getByTestId("film-subtitle")).toBeVisible();

  if (sought.coiba) {
    await page.evaluate(({ i, at }) => window.__naviguideFilm?.seekChapter?.(i, at), sought.coiba);
    await page.waitForFunction((idx) => Number(window.__naviguideFilm?.chapterIdx) === idx,
      sought.coiba.i, { timeout: 10_000 });
    await page.waitForTimeout(400);
    const coibaFilm = await page.evaluate(() => {
      const f = window.__naviguideFilm || {};
      return { lat: Number(f.lat), lon: Number(f.lon), ended: Boolean(f.ended) };
    });
    expect(coibaFilm.ended).toBe(false);
    expect(Number.isFinite(coibaFilm.lat) && Number.isFinite(coibaFilm.lon)).toBe(true);
    expect(
      near({ lat: coibaFilm.lat, lon: coibaFilm.lon }, PAPEETE, 3),
      `Coiba : bateau déjà à Papeete (${coibaFilm.lat}, ${coibaFilm.lon})`,
    ).toBe(false);
    expect(coibaFilm.lon, "Coiba : pas déjà à Tahiti").toBeGreaterThan(-130);
    await page.evaluate(({ i, at }) => window.__naviguideFilm?.seekChapter?.(i, at), sought.cape);
    await page.waitForTimeout(300);
  }

  await shot(page, "01-phrase-et-bateau");
});
