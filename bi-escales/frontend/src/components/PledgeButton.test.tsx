import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge } from "../api/escales";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
}));

const values = {
  amount_eur: "20.00",
  description: "20 milles parrainés",
  milestone_id: "dep-mayotte",
  kind: "mile",
  target_id: "dep-mayotte",
};

describe("PledgeButton", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("fr");
  });

  it("ouvre approve_link sans autoriser au clic", async () => {
    vi.mocked(createPledge).mockResolvedValue({
      id: "pledge-1",
      status: "created",
      intent: "AUTHORIZE",
      currency: "EUR",
      amount_eur: "20.00",
      description: values.description,
      milestone_id: values.milestone_id,
      approve_link: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );

    expect(screen.queryByTestId("pledge-authorize")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Créer l’ordre PayPal" }));
    const link = await screen.findByTestId("paypal-approve-link");
    expect(link).toHaveAttribute("href", "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1");
    expect(link).not.toHaveAttribute("target");
    expect(createPledge).toHaveBeenCalledWith(values, expect.any(String));
    fireEvent.click(link);
    expect(screen.queryByTestId("pledge-authorize")).toBeNull();
    expect(screen.getByText(/Au retour, l’autorisation/)).toBeInTheDocument();
  });
});
