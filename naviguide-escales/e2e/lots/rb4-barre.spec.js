// Barre de lecture compacte : un bouton de vitesse, flèches, haut-parleur.
// Sans API : barre, cycle de vitesse, flèches, haut-parleur, absence de scroll tiennent seuls.
// Libellé météo « climatologie + GFS » : seulement si GET /voyage/official répond
// et que le point courant emploie les deux.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb4/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

async function commandsOverflow(page) {
  return page.getByTestId("film-commands").evaluate((el) => {
    const style = getComputedStyle(el);
    return {
      scroll: el.scrollWidth > el.clientWidth + 1,
      overflowX: style.overflowX,
    };
  });
}

test("Barre compacte, vitesse cyclique, flèches, haut-parleur", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — libellé météo du point courant non vérifié",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const bar = page.getByTestId("film-bar");
  await expect(bar.getByTestId("hide-film-bar")).toBeVisible();
  await expect(bar.getByRole("button", { name: /^(cinéma|cinema)$/i })).toBeVisible();
  await expect(bar.getByTestId("stop-auto")).toBeVisible();
  await expect(bar.getByTestId("view-suivre")).toBeVisible();
  await expect(bar.getByTestId("view-tracer")).toBeVisible();

  const speed = bar.getByTestId("film-speed");
  await expect(speed).toBeVisible();
  await expect(speed).toHaveCount(1);

  const keyOf = (s) => {
    const n = s.trim().toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
    if (n === "real" || n === "reel") return "reel";
    if (n === "read" || n === "lecture") return "lecture";
    if (n === "normal" || n === "normale") return "normale";
    if (n === "fast" || n === "acceleree") return "acceleree";
    return n;
  };
  const order = ["reel", "lecture", "normale", "acceleree"];
  const startKey = keyOf(await speed.innerText());
  expect(order, `libellé initial ${startKey}`).toContain(startKey);
  const seen = [startKey];
  for (let i = 0; i < 4; i += 1) {
    await speed.click();
    seen.push(keyOf(await speed.innerText()));
  }
  expect(seen[4], `retour après 4 clics : ${seen.join(" → ")}`).toBe(startKey);
  const i0 = order.indexOf(startKey);
  expect(seen.slice(0, 4), `cycle ${seen.join(" → ")}`).toEqual([
    order[i0],
    order[(i0 + 1) % 4],
    order[(i0 + 2) % 4],
    order[(i0 + 3) % 4],
  ]);

  const prev = bar.getByTestId("prev-stop");
  const next = bar.getByTestId("next-stop");
  await expect(prev).toBeVisible();
  await expect(next).toBeVisible();
  await expect(prev).toHaveAttribute("title", /Escale précédente|Previous stop/);
  await expect(next).toHaveAttribute("title", /Prochaine escale|Go to next stop/);
  await expect(prev).toContainText("‹");
  await expect(next).toContainText("›");

  const listen = bar.getByTestId("listen");
  await expect(listen).toBeVisible();
  await expect(listen).toHaveAttribute("title", /Écouter|Listen/i);
  const listenBox = await listen.boundingBox();
  expect(listenBox, "haut-parleur mesurable").toBeTruthy();
  expect(listenBox.width, `Écouter trop large : ${listenBox.width}`).toBeLessThan(40);

  const ov = await commandsOverflow(page);
  expect(ov.overflowX, `overflow-x=${ov.overflowX}`).not.toBe("auto");
  expect(ov.scroll, "barre de défilement horizontale").toBeFalsy();

  await shot(page, "01-barre");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("listen")).toBeVisible();
  const ovSuivre = await commandsOverflow(page);
  expect(ovSuivre.overflowX).not.toBe("auto");
  expect(ovSuivre.scroll, "scroll en Suivre").toBeFalsy();

  if (apiUp) {
    const regime = page.getByTestId("clock-regime");
    if (await regime.isVisible({ timeout: 8_000 }).catch(() => false)) {
      const text = (await regime.innerText()).replace(/\s+/g, " ");
      expect(text, `libellé météo : ${text}`).not.toMatch(/GFS-Wave|Open-Meteo/i);
      if (/climatolog/i.test(text) && /\bGFS\b/i.test(text)) {
        expect(text).toMatch(/climatologie \+ GFS|climatology \+ GFS/i);
      }
    }
  }
});
