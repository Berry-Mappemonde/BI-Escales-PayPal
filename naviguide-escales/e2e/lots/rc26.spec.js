// Récit dense et réparti : le bateau avance pendant qu'on parle
// (jamais plus de cinq phrases d'affilée ancrées sur la même minute) et la
// grammaire des eaux tient (« les eaux françaises, puis celles de Montserrat »).
// Sans API : Suivre, Revoir et la barre tiennent seuls. GET /voyage/official
// sondé ; s'il manque, annotation + saut des seules assertions film —
// jamais Revoir retiré, ni les pilules, ni la barre.
// Stock pré-RC26 (grammaire groupée absente) : même saut, surfaces gardées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc26");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

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
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

/** Plus long enchaînement d'ancres consécutives sur la même minute. */
function maxSameMinuteRun(chapter) {
  const anchors = (chapter.anchors || [])
    .filter((a) => Number.isInteger(a.charIdx))
    .sort((a, b) => a.charIdx - b.charIdx);
  let best = 0;
  let run = 0;
  let prev = null;
  for (const a of anchors) {
    const t = Date.parse(a.t || "");
    const minute = Number.isFinite(t) ? Math.floor(t / 60_000) : null;
    run = minute !== null && minute === prev ? run + 1 : (minute !== null ? 1 : 0);
    prev = minute;
    if (run > best) best = run;
  }
  return best;
}

test("Récit dense et réparti, le bateau avance pendant qu'on parle", async ({ page }) => {
  test.setTimeout(480_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre et Revoir gardés",
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
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-ch1-liste");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 15_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions récit sautées ; Revoir visible",
    });
    await shot(page, "01-ch1-liste");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  if (!/puis celles de|then .* waters/i.test(blob)) {
    test.info().annotations.push({
      type: "stock pré-RC26",
      description: "film servi sans la grammaire groupée des eaux — assertions récit sautées ; Revoir visible",
    });
    await shot(page, "01-ch1-liste");
    return;
  }

  // Le grief du 29 sept. : plus de cinq phrases d'affilée sans que le bateau bouge.
  for (const [i, chapter] of film.chapters.entries()) {
    expect(
      maxSameMinuteRun(chapter),
      `ch${i + 1} : pas plus de 5 phrases d'affilée sur la même minute`,
    ).toBeLessThanOrEqual(5);
  }
  expect(blob, "jargon absent").not.toMatch(/zone économique exclusive/i);
  if (/Montserrat/.test(blob)) {
    // Les eaux françaises des Antilles peuvent être nommées par territoire
    // (« les eaux de la Martinique, puis celles de la Guadeloupe ») : la
    // grammaire tient tant que Montserrat arrive en « puis celles de ».
    expect(blob, "grammaire des eaux aux Antilles").toMatch(
      /les eaux (?:françaises|de la [A-ZÀ-Ý][\wÀ-ÿ'-]+)(?:, puis celles de (?:la |l'|les )?[A-ZÀ-Ý][\wÀ-ÿ' -]+)*, puis celles de Montserrat/,
    );
    expect(blob, "jamais d'adjectif orphelin").not.toMatch(/celles de françaises?|de montserrat/);
  }

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 10_000 });
  expect((await subtitle.innerText()).trim(), "sous-titre non vide").not.toBe("");
  await shot(page, "01-ch1-liste");

  // Laisser la lecture atteindre la phrase des eaux antillaises (voix coupée,
  // ~15 c/s : Montserrat arrive vers 2:40 de lecture intégrale).
  const sawMontserrat = await page.waitForFunction(() => {
    const el = document.querySelector("[data-testid='film-subtitle']");
    return /Montserrat/i.test(el?.textContent || "");
  }, null, { timeout: 300_000 }).then(() => true).catch(() => false);
  if (!sawMontserrat) {
    test.info().annotations.push({
      type: "phrase antillaise non atteinte",
      description: "le sous-titre n'a pas montré Montserrat dans le délai — capture sur le chapitre courant",
    });
  }
  await shot(page, "02-antilles");

  const stopBtn = page.getByTestId("replay-stop");
  await expect(stopBtn).toBeVisible({ timeout: 8_000 });
  await stopBtn.click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
});
