import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import fr from "./locales/fr.json";
import en from "./locales/en.json";
import i18n, { applyDocumentMeta, setLanguage } from "./index";
import { AG_STUDIO_LOCALE_FR } from "../studio/agStudioLocale";

const GEAR_FR = [/Ordinateur de plongée/i, /Sacs étanches/i, /Jumelles marines/i];

function seedDocumentMeta() {
  document.head.insertAdjacentHTML(
    "beforeend",
    `<meta name="description" content="" />
     <meta property="og:title" content="" />
     <meta property="og:description" content="" />
     <meta property="og:locale" content="" />
     <meta name="twitter:title" content="" />
     <meta name="twitter:description" content="" />`,
  );
}

describe("I18N-LEAKS-2 guards", () => {
  beforeEach(() => {
    document.head.querySelectorAll("meta").forEach((node) => node.remove());
    seedDocumentMeta();
  });

  afterEach(async () => {
    await i18n.changeLanguage("fr");
    applyDocumentMeta();
  });

  it("updates document title when the language changes", async () => {
    await act(async () => {
      setLanguage("fr");
    });
    expect(document.title).toBe(fr.app.title);
    expect(document.title).not.toMatch(/Pay Only If We Sail/i);

    await act(async () => {
      setLanguage("en");
    });
    expect(document.title).toBe(en.app.title);
    expect(document.querySelector('meta[property="og:title"]')?.getAttribute("content")).toBe(en.app.title);
  });

  it("syncs meta description and og:locale with UI language (Hamid QA)", async () => {
    await act(async () => {
      setLanguage("en");
    });
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")).toBe(en.app.metaDescription);
    expect(document.querySelector('meta[property="og:locale"]')?.getAttribute("content")).toBe("en_US");

    await act(async () => {
      setLanguage("fr");
    });
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")).toBe(fr.app.metaDescription);
    expect(document.querySelector('meta[property="og:locale"]')?.getAttribute("content")).toBe("fr_FR");
  });

  it("does not ship hard-coded English AG Studio overlay strings in French locale map", () => {
    expect(AG_STUDIO_LOCALE_FR.widgetOverlayNoData).toBe("Aucune donnée à afficher");
    expect(AG_STUDIO_LOCALE_FR.widgetOverlayLoading).toBe("Chargement…");
    expect(JSON.stringify(AG_STUDIO_LOCALE_FR)).not.toMatch(/No data to display|"Loading\.\.\."/);
  });

  it.each(GEAR_FR)("English gear dictionary avoids French leak %s", (pattern) => {
    const blob = JSON.stringify(en.gear.seedTitles);
    expect(blob).not.toMatch(pattern);
  });
});
