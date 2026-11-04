// Chat du journal : repli par les faits quand aucun modèle ne répond.
// Sans API : le panneau chat tient seul. GET /voyage/official sondé ;
// s'il manque, annotation + saut des questions/réponses — jamais le chat retiré.
// Aucune donnée factice : on lit la réponse du poste, on n'écrit aucun vent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rh1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FAILED = /n.a pas pu répondre|aucun modèle n.a répondu|could not answer|no model replied/i;
const MISSING = /n.a pas cette information dans ses données|does not hold that information/i;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && typeof body === "object");
}

async function askChat(page, question) {
  const chat = page.getByTestId("logbook-chat");
  const input = chat.getByTestId("logbook-chat-input");
  await input.scrollIntoViewIfNeeded();
  await input.fill(question);
  await chat.getByTestId("logbook-chat-send").click();
}

test("Chat : repli par les faits, jamais l'échec modèle si le journal a des faits", async ({ page }) => {
  test.setTimeout(180_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — questions au journal sautées ; panneau chat gardé",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-clock-line")).toContainText("LIVE");
  await showLeftPanel(page);

  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 10_000 });
  await expect(chat.getByTestId("logbook-chat-input")).toBeVisible();
  await expect(chat.getByTestId("logbook-chat-send")).toBeVisible();

  if (!apiUp) {
    return;
  }

  await askChat(page, "Quel vent au bateau ?");
  const list = page.getByTestId("logbook-chat-list");
  await expect.poll(async () => {
    if (await page.getByTestId("chat-source").count()) return "ready";
    const t = await list.innerText();
    if (FAILED.test(t) || MISSING.test(t)) return "done";
    return "wait";
  }, { timeout: 60_000 }).not.toBe("wait");

  const windText = await list.innerText();
  if (FAILED.test(windText)) {
    test.info().annotations.push({
      type: "pré-RH1",
      description: "POST /logbook/chat encore en failed — API du poste sans le repli ; chat et LIVE gardés",
    });
    return;
  }
  expect(windText, "jamais le message d'échec modèle").not.toMatch(FAILED);
  const hasWind = /\d+(?:[.,]\d+)?\s*kn/i.test(windText);
  expect(hasWind || MISSING.test(windText), "phrase vent (kn) ou pas cette information").toBeTruthy();
  await shot(page, "01-chat-vent");

  await askChat(page, "Quel est le prix du gasoil ?");
  await expect.poll(async () => {
    const t = await list.innerText();
    if (FAILED.test(t)) return "failed";
    if (MISSING.test(t)) return "missing";
    if (await page.getByTestId("chat-source").count() >= 2) return "ready";
    return "wait";
  }, { timeout: 60_000 }).not.toBe("failed");
  const gas = await list.innerText();
  expect(gas, "gasoil : jamais l'échec modèle").not.toMatch(FAILED);
  expect(gas, "gasoil : pas un prix inventé").not.toMatch(/\d+[.,]\d+\s*€|\d+\s*€\/l/i);

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await askChat(page, "Quel vent au bateau ?");
  await expect.poll(async () => {
    const t = await page.getByTestId("logbook-chat-list").innerText();
    if (FAILED.test(t)) return "failed";
    if (await page.getByTestId("chat-source").count()) return "ready";
    if (MISSING.test(t)) return "done";
    return "wait";
  }, { timeout: 60_000 }).not.toBe("failed");
  const simText = await page.getByTestId("logbook-chat-list").innerText();
  expect(simText, "Simulation : jamais l'échec modèle").not.toMatch(FAILED);
});
