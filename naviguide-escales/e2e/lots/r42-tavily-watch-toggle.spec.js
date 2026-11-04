// R42 : interrupteur « Veille Tavily » des réglages de la barre de droite.
// Effet réel : le drapeau watch_enabled du serveur change, et survit au rechargement.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showRightPanel } from "../helpers.js";

const API = `http://127.0.0.1:${process.env.PW_API_PORT || 8010}`;

// Les deux langues modifient le même réglage persistant côté serveur.
test.describe.configure({ mode: "serial" });

for (const [lang, label] of [["fr", "Veille Tavily"], ["en", "Tavily watch"]]) {
  test(`R42 ${lang} : l'interrupteur change la veille sur le serveur et reste après rechargement`, async ({ page, request }) => {
    test.setTimeout(90_000);
    const api = await request.get(`${API}/escale/watch/settings`).catch(() => null);
    test.skip(!api?.ok(), "API hors ligne absente");
    const initial = await api.json();
    const before = initial.enabled;
    const adminSecret = (process.env.NAVIGUIDE_ADMIN_SECRET || "").trim();
    if (adminSecret) await page.setExtraHTTPHeaders({ "X-Naviguide-Admin": adminSecret });
    try {
      await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
      await page.goto("/");
      await dismissNotForNav(page);
      await showRightPanel(page);
      const sw = page.getByRole("switch", { name: label });
      await sw.scrollIntoViewIfNeeded();
      await expect(sw).toHaveAttribute("data-testid", "tavily-watch-toggle");
      await expect(sw).toHaveAttribute("aria-checked", String(before));
      const saved = page.waitForResponse((response) =>
        response.request().method() === "POST" && response.url().includes("/escale/watch/settings"),
      );
      await sw.click();
      const saveResponse = await saved;
      expect(saveResponse.ok()).toBeTruthy();
      await expect(sw).toHaveAttribute("aria-checked", String(!before));
      const after = await (await request.get(`${API}/escale/watch/settings`)).json();
      expect(after).toMatchObject({ enabled: !before, source: "setting" });
      await page.reload();
      await dismissNotForNav(page);
      await showRightPanel(page);
      await expect(page.getByTestId("tavily-watch-toggle")).toHaveAttribute("aria-checked", String(!before));
    } finally {
      // Remet le réglage serveur dans son état de départ, sans masquer l'erreur d'origine.
      const headers = adminSecret ? { "X-Naviguide-Admin": adminSecret } : {};
      const restore = initial.source === "setting" ? before : null;
      const res = await request.post(`${API}/escale/watch/settings`, { data: { enabled: restore }, headers })
        .catch((err) => ({ ok: () => false, status: () => String(err) }));
      if (!res.ok()) console.warn(`R42 : restauration de la veille impossible (HTTP ${res.status()})`);
    }
  });
}
