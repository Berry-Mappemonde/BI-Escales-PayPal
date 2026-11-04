// Chat : règles pour le simple, Ultra si le juge est ouvert, jamais Super.
// Sans API : le panneau chat tient seul. GET /voyage/official sondé ;
// s'il manque, annotation + saut des questions — jamais le chat retiré.
// Aucune donnée factice : on lit la réponse du poste, on n'écrit aucun vent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-ch1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FAILED = /n.a pas pu répondre|aucun modèle n.a répondu|could not answer|no model replied/i;
const MISSING = /n.a pas cette information dans ses données|does not hold that information/i;
const RULES_LABEL = "Formulé par les données brutes";
const SUPER = /nemotron 3(?:\.5)? super|nemotron-super/i;

async function askChat(page, question) {
  const chat = page.getByTestId("logbook-chat");
  const input = chat.getByTestId("logbook-chat-input");
  await input.scrollIntoViewIfNeeded();
  await input.fill(question);
  await chat.getByTestId("logbook-chat-send").click();
}

async function waitReply(page, { sourcesBefore = 0 } = {}) {
  const list = page.getByTestId("logbook-chat-list");
  await expect.poll(async () => {
    const n = await page.getByTestId("chat-source").count();
    if (n > sourcesBefore) return "ready";
    const t = await list.innerText();
    if (FAILED.test(t) && n >= sourcesBefore) return "done";
    if (MISSING.test(t) && n > sourcesBefore) return "done";
    return "wait";
  }, { timeout: 60_000 }).not.toBe("wait");
  return list.innerText();
}

test("Chat règles / Ultra, sans case Raisonnement", async ({ page }) => {
  test.setTimeout(180_000);
  const official = await probeOfficial(page);
  const apiUp = Boolean(official);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);

  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 10_000 });
  await expect(chat.getByTestId("logbook-chat-input")).toBeVisible();
  await expect(chat.getByTestId("logbook-chat-send")).toBeVisible();
  await expect(chat.getByTestId("logbook-chat-reason")).toHaveCount(0);
  await expect(chat).not.toContainText(/Raisonnement|Reasoning/);

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — questions au journal sautées ; panneau chat gardé, sans case Raisonnement",
    });
    await shot(page, "01-chat");
    return;
  }

  const factsRes = await page.request.get("/logbook/facts", { timeout: 20_000 }).catch(() => null);
  const factsBody = factsRes && factsRes.ok() ? await factsRes.json().catch(() => null) : null;
  const factsOk = Boolean(factsBody && factsBody.facts);

  let sources = 0;
  await askChat(page, "Quel vent au bateau ?");
  const windText = await waitReply(page, { sourcesBefore: sources });
  sources = await page.getByTestId("chat-source").count();
  expect(windText, "jamais l'échec modèle").not.toMatch(FAILED);
  const hasWind = /\d+(?:[.,]\d+)?\s*kn/i.test(windText);
  expect(hasWind || MISSING.test(windText), "phrase vent (kn) ou pas cette information").toBeTruthy();
  const src0 = page.getByTestId("chat-source").last();
  if (await src0.count()) {
    await expect(src0).toHaveAttribute("data-llm-source", "rules");
    await expect(src0).toContainText(RULES_LABEL);
    await expect(src0).not.toContainText(SUPER);
  }

  await askChat(page, "Arrivée prévue à Madère ?");
  const etaText = await waitReply(page, { sourcesBefore: sources });
  sources = await page.getByTestId("chat-source").count();
  expect(etaText).not.toMatch(FAILED);
  const etaLast = await page.getByTestId("logbook-chat-list").locator(":scope > div").last().innerText();
  const legs = factsOk ? (factsBody.facts?.plan?.legs || []) : [];
  const hasMadere = /mad[eèê]re|madeira/i.test(JSON.stringify(legs));
  if (factsOk && !hasMadere) {
    expect(etaLast, "Madère hors plan → phrase d'absence").toMatch(MISSING);
  }

  await askChat(page, "Pourquoi ralentir ?");
  const hardText = await waitReply(page, { sourcesBefore: sources });
  expect(hardText).not.toMatch(FAILED);
  const srcHard = page.getByTestId("chat-source").last();
  const hardLabel = ((await srcHard.innerText().catch(() => "")) || "").trim();
  expect(hardLabel, "juge à 0 / modèles éteints : règles, jamais Super").not.toMatch(SUPER);
  expect(hardLabel).toMatch(/Formulé par les données brutes|budget|ultra/i);
  await expect(chat.getByTestId("logbook-chat-reason")).toHaveCount(0);

  await page.getByTestId("logbook-chat-list").locator(":scope > div").last().scrollIntoViewIfNeeded();
  await shot(page, "01-chat");
});
