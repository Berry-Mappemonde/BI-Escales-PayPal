import { act, fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
    expect(screen.getByRole("heading", { name: /^Back a stop\.\s+Pay only if we arrive\.$/ })).toBeInTheDocument();
    expect(screen.getByText(en.howItWorks.credit)).toBeInTheDocument();
    expect(screen.getByText(/Your pledge is authorised now/)).toBeInTheDocument();
    expect(screen.getByText("Cancelled stop? The authorisation is voided. No charge.")).toBeInTheDocument();
    expect(screen.getByText("Cabins are captured when their leg departs, not on arrival.")).toBeInTheDocument();
  });

  it("still tells the visitor what to do", () => {
    show();
    expect(screen.getByText("Select a stop on the map to see its details and make a pledge.")).toBeInTheDocument();
    expect(screen.getByTestId("how-it-works").querySelector("svg")).toBeInTheDocument();
  });

  it("offers backing the next stop as the one action, by name, in EN and FR", async () => {
    const onBackNextStop = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <HowItWorks nextStopName="La Rochelle" onBackNextStop={onBackNextStop} />
      </I18nextProvider>,
    );
    const cta = screen.getByTestId("back-next-stop");
    expect(cta).toHaveAccessibleName("Back the next stop: La Rochelle");
    expect(cta).toHaveTextContent("Back the next stop");
    expect(cta).toHaveTextContent("La Rochelle");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(cta);
    expect(onBackNextStop).toHaveBeenCalledTimes(1);
    await act(async () => { await i18n.changeLanguage("fr"); });
    expect(cta).toHaveAccessibleName("Soutenir la prochaine escale : La Rochelle");
  });

  it("leaves the action out until a stop is known", () => {
    show();
    expect(screen.queryByTestId("back-next-stop")).toBeNull();
  });

  it("shows in French", async () => {
    await i18n.changeLanguage("fr");
    show();
    expect(screen.getByRole("heading", { name: /^Soutenez une escale\.\s+Vous ne payez que si nous arrivons\.$/ })).toBeInTheDocument();
    expect(screen.getByText(fr.howItWorks.credit)).toBeInTheDocument();
    expect(screen.getByText("Autorisation de votre promesse")).toBeInTheDocument();
  });

  it("keeps FR and EN in step, with no dates", () => {
    expect(Object.keys(fr.howItWorks)).toEqual(Object.keys(en.howItWorks));
    for (const block of [en.howItWorks, fr.howItWorks]) {
      expect(JSON.stringify(block)).not.toMatch(/20\d\d/);
    }
  });

  it("shows the main button as not yet usable while the next stop is unknown", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <HowItWorks nextStopPending />
      </I18nextProvider>,
    );
    const pending = screen.getByTestId("back-next-stop-pending");
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(pending).toHaveTextContent(en.howItWorks.backNext);
    expect(pending).toHaveTextContent(en.howItWorks.backNextLoading);
    expect(screen.queryByTestId("back-next-stop")).toBeNull();
  });

  it("prefers the named button over the waiting one", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <HowItWorks nextStopName="La Rochelle" onBackNextStop={() => undefined} nextStopPending />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("back-next-stop")).toBeEnabled();
    expect(screen.queryByTestId("back-next-stop-pending")).toBeNull();
  });

  it("has the waiting label in French too", () => {
    expect(fr.howItWorks.backNextLoading).toBe("Recherche de la prochaine escale…");
  });
});
