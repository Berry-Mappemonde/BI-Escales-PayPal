import { describe, expect, it } from "vitest";
import { AG_STUDIO_LOCALE_FR, agStudioLocaleText } from "./agStudioLocale";

describe("agStudioLocaleText", () => {
  it("returns undefined for English (AG defaults)", () => {
    expect(agStudioLocaleText("en")).toBeUndefined();
  });

  it("localizes widget overlays and side panels in French", () => {
    const fr = agStudioLocaleText("fr");
    expect(fr?.widgetOverlayNoData).toBe("Aucune donnée à afficher");
    expect(fr?.widgetOverlayLoading).toBe("Chargement…");
    expect(fr?.panelTitleData).toBe("Données");
    expect(fr?.panelTitleEdit).toBe("Composer");
    expect(AG_STUDIO_LOCALE_FR.widgetOverlayNoData).not.toMatch(/No data to display/i);
    expect(AG_STUDIO_LOCALE_FR.widgetOverlayLoading).not.toMatch(/^Loading/);
  });
});
