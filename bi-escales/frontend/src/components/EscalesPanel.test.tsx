import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { captainChat } from "../api/escales";
import i18n from "../i18n";
import { EscalesPanel } from "./EscalesPanel";

vi.mock("../api/escales", () => ({
  captainChat: vi.fn(),
  createPledge: vi.fn(),
  authorizePledge: vi.fn(),
  fetchFeatures: vi.fn().mockResolvedValue({ vault: true }),
}));

describe("EscalesPanel cart", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("fr");
  });

  it("affiche chaque ligne et son objet pledge", async () => {
    vi.mocked(captainChat).mockResolvedValue({
      reply: "Promesse calculée.",
      suggested_pledge: {
        amount_eur: "20.00",
        currency: "EUR",
        description: "20 milles parrainés",
        milestone_id: "dep-mayotte",
        intent: "AUTHORIZE",
      },
      cart: {
        currency: "EUR",
        lines: [
          {
            kind: "mile",
            description: "20 milles parrainés",
            amount_eur: "20.00",
            price_label: "simulation",
            pledge: {
              amount_eur: "20.00",
              description: "20 milles parrainés",
              milestone_id: "dep-mayotte",
              kind: "mile",
              target_id: "dep-mayotte",
            },
          },
        ],
      },
    });

    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Demander une formulation" }));
    expect(captainChat).toHaveBeenCalledWith("20 milles près de Mayotte", "fr", undefined);
    const line = await screen.findByTestId("cart-line");
    expect(line).toHaveTextContent("20 milles parrainés — 20.00 EUR");
    expect(line).toHaveTextContent("prix simulé");
    expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-kind", "mile");
    expect(screen.queryByTestId("pledge-authorize")).toBeNull();
    expect(screen.queryByRole("button", { name: /preuve/i })).toBeNull();
  });
});
