import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import EscalesScheduler, { LocalScheduleList } from "./EscalesScheduler.jsx";

vi.mock("../PledgeButton", () => ({
  PledgeButton: ({ values }) => (
    <button
      type="button"
      data-kind={values.kind}
      data-milestone={values.milestone_id}
      data-amount={values.amount_eur}
    >
      {values.kind}
    </button>
  ),
}));

const schedule = {
  escales: [
    { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" },
  ],
  legs: [
    {
      id: "leg-la-rochelle-to-ajaccio-corse",
      from_name: "La Rochelle",
      to_name: "Ajaccio (Corse)",
      departure_iso: "2026-11-12T12:00:00Z",
      arrival_iso: "2026-12-02T02:02:54Z",
      capture_on: "departure",
    },
  ],
  prices: { simulated: true, label: "simulated price", prices: [{ kind: "cabin_leg", amount_eur: "80.00", currency: "EUR" }] },
};

describe("EscalesScheduler", () => {
  it("shows localized empty schedule copy", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <LocalScheduleList events={[]} />
      </I18nextProvider>,
    );
    expect(screen.getByText("No stopovers scheduled.")).toBeInTheDocument();

    cleanup();
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <LocalScheduleList events={[]} />
      </I18nextProvider>,
    );
    expect(screen.getByText("Aucune escale planifiée.")).toBeInTheDocument();
  });

  it("affiche les jambes et une promesse cabine", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesScheduler schedule={schedule} planningEnabled onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    // The cabin checkouts are mounted when the visitor opens "Book a cabin on a leg".
    expect(screen.queryByTestId("schedule-leg")).toBeNull();
    const cabins = screen.getByTestId("schedule-cabins");
    cabins.open = true;
    fireEvent(cabins, new Event("toggle"));
    expect(screen.getByTestId("schedule-leg").textContent).toContain("Ajaccio");
    const cabin = screen.getByRole("button", { name: "cabin_leg" });
    expect(cabin.getAttribute("data-kind")).toBe("cabin_leg");
    expect(cabin.getAttribute("data-milestone")).toBe("leg-la-rochelle-to-ajaccio-corse");
    expect(cabin.getAttribute("data-amount")).toBe("80.00");
    expect(screen.getByTestId("cabin-price")).toHaveTextContent("80.00 EUR");
    expect(screen.queryByText("Pay Only If We Sail")).toBeNull();
    expect(screen.queryByText(/Horloge du voyage/)).toBeNull();
    expect(screen.queryByText("simulated price")).toBeNull();
    expect(screen.queryByText("Advisory")).toBeNull();
    expect(screen.queryByText(/Bryntum/)).toBeNull();
  });
});
