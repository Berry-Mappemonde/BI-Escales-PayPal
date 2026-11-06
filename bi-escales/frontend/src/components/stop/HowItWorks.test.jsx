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
      "Authorise your pledge",
      "Arrival and approval",
      "Payment captured",
    ]);
  });

  it("marks each money state with its own tone", () => {
    expect(show().map((step) => step.dataset.tone ?? null)).toEqual([
      "held",
      null,
      "captured",
    ]);
  });

  it("explains the pledge, cancellation, and cabin rules", () => {
    show();
    expect(screen.getByText("STOP PLEDGES")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Back a stop. Pay only if we arrive." })).toBeInTheDocument();
    expect(screen.getByText(/Your pledge is authorised now/)).toBeInTheDocument();
    expect(screen.getByText("Cancelled stop? The authorisation is voided. No charge.")).toBeInTheDocument();
    expect(screen.getByText("Cabins are captured when their leg departs, not on arrival.")).toBeInTheDocument();
  });

  it("still tells the visitor what to do", () => {
    show();
    expect(screen.getByText("Select a stop on the map to see its details and make a pledge.")).toBeInTheDocument();
    expect(screen.getByTestId("how-it-works").querySelector("svg")).toBeInTheDocument();
  });

  it("shows in French", async () => {
    await i18n.changeLanguage("fr");
    show();
    expect(screen.getByRole("heading", { name: "Soutenez une escale. Vous ne payez que si nous arrivons." })).toBeInTheDocument();
    expect(screen.getByText("Autorisation de votre promesse")).toBeInTheDocument();
  });

  it("keeps FR and EN in step, with no dates", () => {
    expect(Object.keys(fr.howItWorks)).toEqual(Object.keys(en.howItWorks));
    for (const block of [en.howItWorks, fr.howItWorks]) {
      expect(JSON.stringify(block)).not.toMatch(/20\d\d/);
    }
  });
});
