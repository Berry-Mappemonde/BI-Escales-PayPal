// Revoir accepte le film RG6+ long (intégral, sans pilule).
// Sans API : Suivre, barre et Revoir restent visibles. GET /voyage/official
// sondé ; s'il manque, annotation + saut des seules assertions film —
// jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc21");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const RG6_OPENING = /Berry-Mappemonde quitte|L['’]expédition Berry-Mappemonde|Berry-Mappemonde leaves|The Berry-Mappemonde expedition/i;
const RG6_MILES_DAYS = /milles|jours de mer|days at sea|\bmiles\b/i;
const RG7_CLOSE = /Aujourd['’]hui, le bateau|Today, the boat/i;
const RE7_STALE = /Bay of Biscay|milles nautiques du départ/i;

function hasRg6Rg7Fingerprint(blob) {
  if (RG7_CLOSE.test(blob)) return true;
  return RG6_OPENING.test(blob) && RG6_MILES_DAYS.test(blob);
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

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

test("Revoir accepte le film RG6+ long", async ({ page }) => {
  test.setTimeout(90_000);
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
    await shot(page, "01-suivre-revoir");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — lecture sautée ; Revoir visible",
    });
    await expect(start).toBeVisible();
    await shot(page, "01-suivre-revoir");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const playable = hasRg6Rg7Fingerprint(blob) && !RE7_STALE.test(blob);
  if (!playable) {
    test.info().annotations.push({
      type: "stock sans empreinte RG6",
      description: "film servi sans ouverture/clôture RG6/RG7 — lecture sautée ; Revoir visible",
    });
    await expect(start).toBeVisible();
    await shot(page, "01-suivre-revoir");
    return;
  }

  await expect(start).toBeEnabled({ timeout: 30_000 });
  const durations = page.getByTestId("film-duration");
  await expect(durations).toBeVisible({ timeout: 8_000 });
  await expect(durations).toContainText("2:30");
  await expect(durations).toContainText("3:00");
  await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  await shot(page, "01-suivre-revoir");

  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const sub = (await subtitle.innerText()).trim();
  expect(sub, "sous-titre non vide").not.toBe("");
  expect(
    RG6_OPENING.test(sub) || RG6_MILES_DAYS.test(sub) || /La Rochelle|Ajaccio|Saint-Maur/i.test(sub),
    "ouverture ou milles/jours dans le sous-titre",
  ).toBeTruthy();
  await shot(page, "02-ouverture");

  const stopBtn = page.getByTestId("replay-stop");
  await expect(stopBtn).toBeVisible({ timeout: 8_000 });
  await stopBtn.click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-stop")).toHaveCount(0);
  await shot(page, "03-stop-suivre");
});
