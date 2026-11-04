import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EscalesScheduler from "./EscalesScheduler.jsx";

vi.mock("../PledgeButton", () => ({
  PledgeButton: ({ values }) => (
    <button type="button" data-kind={values.kind} data-milestone={values.milestone_id}>
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
  it("affiche les jambes et une promesse cabine", () => {
    render(<EscalesScheduler schedule={schedule} />);
    expect(screen.getByTestId("schedule-leg").textContent).toContain("Ajaccio");
    const cabin = screen.getByRole("button", { name: "cabin_leg" });
    expect(cabin.getAttribute("data-kind")).toBe("cabin_leg");
    expect(cabin.getAttribute("data-milestone")).toBe("leg-la-rochelle-to-ajaccio-corse");
  });
});
