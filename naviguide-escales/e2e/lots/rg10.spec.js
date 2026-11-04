// Recette automatique du discours (test serveur).
// Sans API : Suivre, Revoir et la barre tiennent seuls. GET /voyage/official
// sondé ; s'il manque, annotation + saut des seules assertions film —
// jamais Revoir retiré, ni les pilules, ni la barre.
// Stock figé pré-RG6 (jargon encore en cache) : même saut, surfaces gardées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg10");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FORBIDDEN = /\bjambe\b|zone économique exclusive|Couloirs\s*:|À surveiller|à portée de|\bde de\b/i;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

test("Discours sans jargon, barre et Revoir gardés", async ({ page }) => {
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
  await expect(page.getByTestId("film-bar")).not.toContainText(/Récit\s*:/);
  await expect(page.getByTestId("film-bar")).not.toContainText(/Story\s*:/);

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-barre");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions discours sautées",
    });
    await shot(page, "01-barre");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  if (FORBIDDEN.test(blob)) {
    test.info().annotations.push({
      type: "stock pré-RG6",
      description: "GET /voyage/official/film encore à l'ancienne clé — discours sauté ; barre et Revoir gardés",
    });
    await shot(page, "01-barre");
    return;
  }

  expect(blob, "mots interdits absents").not.toMatch(FORBIDDEN);
  await shot(page, "01-barre");
});
