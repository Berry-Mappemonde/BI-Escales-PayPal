import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it } from "vitest";
import i18n from "../../i18n";
import en from "../../i18n/locales/en.json";
import fr from "../../i18n/locales/fr.json";
import { HowItWorks } from "./HowItWorks.jsx";

function show() {
  render(
    <I18nextProvider i18n={i18n}>
      <HowItWorks />
    </I18nextProvider>,
  );
  return screen.getAllByRole("listitem");
}

describe("HowItWorks", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("walks through the steps in order", () => {
    expect(show().map((step) => step.querySelector("strong").textContent)).toEqual([
      "You pledge",
      "Held on PayPal",
      "The boat arrives",
      "The treasurer approves",
      "Captured",
      "Or released, if we don't sail",
    ]);
  });

  it("marks each money state with its own tone", () => {
    expect(show().map((step) => step.dataset.tone ?? null)).toEqual([
      null,
      "held",
      "route",
      null,
      "captured",
      "released",
    ]);
  });

  it("is about stop pledges, and keeps the cabin rule, so it stays true", () => {
    show();
    expect(screen.getByRole("heading", { name: "How a stop pledge works" })).toBeInTheDocument();
    expect(screen.getByText("For cabins, when the leg departs.")).toBeInTheDocument();
  });

  it("still tells the visitor what to do", () => {
    show();
    expect(screen.getByText("Pick a stop on the map for the sheet and the PayPal button.")).toBeInTheDocument();
  });

  it("shows in French", async () => {
    await i18n.changeLanguage("fr");
    show();
    expect(screen.getByText("Retenu sur PayPal")).toBeInTheDocument();
  });

  it("keeps FR and EN in step, with no dates", () => {
    expect(Object.keys(fr.howItWorks)).toEqual(Object.keys(en.howItWorks));
    for (const block of [en.howItWorks, fr.howItWorks]) {
      expect(JSON.stringify(block)).not.toMatch(/20\d\d/);
    }
  });
});
