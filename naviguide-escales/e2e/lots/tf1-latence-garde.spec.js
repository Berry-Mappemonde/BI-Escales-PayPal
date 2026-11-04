// TF1 — visite « Qui fait quoi » : latence Token Factory mesurée par palier (C1-a)
// et modèle absent du catalogue annoncé avec son remplaçant (C1-b). Le statut
// /ici/warm/status est simulé : le test ne dépend ni de l'API ni d'un appel payant.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const LLM = {
  configuredModels: {
    nano: "nvidia/Nemotron-3_5-Lightning",
    fast: "nvidia/Nemotron-3_5-Lightning",
    write: "nvidia/Nemotron-3.5-Super-VL",
    deep: "nvidia/Nemotron-3-Ultra-550b-a55b",
    judge: "nvidia/Nemotron-3-Ultra-550b-a55b",
  },
  fast: { tokens: 400, calls: 3, usd: 0.0001 },
  write: { tokens: 900, calls: 2, usd: 0.0005 },
  judge: { tokens: 3000, calls: 1, usd: 0.006 },
  tavily: { credits: 0, calls: 0 },
  latency: {
    fast: { lastMs: 820, medianMs: 870, calls: 3, samples: 3 },
    write: { lastMs: 2200, medianMs: 2140, calls: 2, samples: 2 },
    judge: { lastMs: 6380, medianMs: 6380, calls: 1, samples: 1 },
  },
  modelGuard: {
    enabled: true,
    catalogs: {},
    missing: {
      write: {
        model: "nvidia/Nemotron-3.5-Super-VL",
        substitute: "nvidia/Nemotron-3_5-Lightning",
        substituteTier: "fast",
        count: 1,
      },
    },
  },
};

test("TF1 étape « Qui fait quoi » : médianes Token Factory et modèle remplacé, étiqueté", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/ici/warm/status", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ llm: LLM }) }),
  );
  await page.goto("/?tour=1");
  await dismissNotForNav(page);
  const panel = page.getByTestId("demo-walkthrough-panel");
  await expect(panel).toHaveAttribute("data-step", "welcome", { timeout: 30_000 });
  await page.getByTestId("demo-walkthrough-next").click();
  await expect(panel).toHaveAttribute("data-step", "models");
  const latency = page.getByTestId("demo-models-latency");
  await expect(latency).toContainText("Token Factory", { timeout: 20_000 });
  await expect(latency).toContainText("Nemotron 3.5 Lightning 0,9 s");
  await expect(latency).toContainText("Nemotron 3.5 Super VL 2,1 s");
  await expect(latency).toContainText("Nemotron 3 Ultra 6,4 s");
  await expect(page.getByTestId("demo-models-missing-write")).toContainText(
    "remplacé par Nemotron 3.5 Lightning",
  );
  expect(errors, errors.join("\n")).toEqual([]);
});
