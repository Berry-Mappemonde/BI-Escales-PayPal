import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { stopMarkerIconHtml } from "./stopMarkerIcon.js";

describe("stopMarkerIconHtml", () => {
  it("exposes role=button and localized aria-label on flag markers (EN)", async () => {
    await i18n.changeLanguage("en");
    const label = i18n.t("map.stopMarker", { name: "Ajaccio (Corse)" });
    const html = stopMarkerIconHtml(
      {
        name: "Ajaccio (Corse)",
        flags: ["/flags/fr.svg"],
      },
      label,
    );
    expect(html).toContain('role="button"');
    expect(html).toContain('aria-label="Voyage stop: Ajaccio (Corse)"');
    expect(html).toContain('data-stop-marker="true"');
  });

  it("exposes localized aria-label on flag markers (FR)", async () => {
    await i18n.changeLanguage("fr");
    const label = i18n.t("map.stopMarker", { name: "La Rochelle" });
    const html = stopMarkerIconHtml({ name: "La Rochelle", flags: ["/flags/fr.svg"] }, label);
    expect(html).toContain('aria-label="Escale : La Rochelle"');
  });

  it("adds an accessible button on drawing-pin markers without flags", async () => {
    await i18n.changeLanguage("en");
    const label = i18n.t("map.stopMarker", { name: "La Rochelle" });
    const html = stopMarkerIconHtml({ name: "La Rochelle" }, label);
    expect(html).toContain('role="button"');
    expect(html).toContain('aria-label="Voyage stop: La Rochelle"');
  });
});
