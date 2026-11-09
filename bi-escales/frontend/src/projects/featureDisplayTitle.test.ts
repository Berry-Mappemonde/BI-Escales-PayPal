import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { featureDisplayTitle } from "./featureDisplayTitle";

const gearProps = {
  id: "gear-dive-computer-expedition",
  title: "Ordinateur de plongée expedition",
  project_kind: "gear_project",
};

describe("featureDisplayTitle", () => {
  it("keeps French API titles in French UI", async () => {
    await i18n.changeLanguage("fr");
    expect(featureDisplayTitle(gearProps, "fr", i18n.t.bind(i18n))).toBe("Ordinateur de plongée expedition");
  });

  it("uses English copy for sandbox gear seed rows", async () => {
    await i18n.changeLanguage("en");
    const title = featureDisplayTitle(gearProps, "en", i18n.t.bind(i18n));
    expect(title).toBe("Expedition dive computer");
    expect(title).not.toMatch(/Ordinateur|plongée/i);
  });

  it("leaves voyage project titles untouched", async () => {
    await i18n.changeLanguage("en");
    const title = featureDisplayTitle(
      { id: "proj-1", title: "Plastics Initiative", project_kind: "project" },
      "en",
      i18n.t.bind(i18n),
    );
    expect(title).toBe("Plastics Initiative");
  });
});
