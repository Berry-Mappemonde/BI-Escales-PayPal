import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { authorizePledge, createPledge } from "../api/escales";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  authorizePledge: vi.fn(),
  registerVault: vi.fn(),
  isVaultPledge: (pledge: { payment_mode?: string }) => pledge.payment_mode === "VAULT",
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

  it("ouvre approve_link avant d'appeler authorize", async () => {
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
    vi.mocked(authorizePledge).mockResolvedValue({
      id: "pledge-1",
      status: "authorized",
      intent: "AUTHORIZE",
      currency: "EUR",
      amount_eur: "20.00",
      description: values.description,
      milestone_id: values.milestone_id,
    });

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );

    expect(screen.getByTestId("pledge-authorize")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Créer l’ordre PayPal" }));
    const link = await screen.findByTestId("paypal-approve-link");
    expect(link).toHaveAttribute("href", "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1");
    expect(createPledge).toHaveBeenCalledWith(values, expect.any(String));
    expect(authorizePledge).not.toHaveBeenCalled();
    expect(screen.getByTestId("pledge-authorize")).toBeDisabled();

    fireEvent.click(link);
    expect(screen.getByTestId("pledge-authorize")).toBeEnabled();
    fireEvent.click(screen.getByTestId("pledge-authorize"));
    await screen.findByText("Promesse autorisée");
    expect(authorizePledge).toHaveBeenCalledWith("pledge-1");
  });
});
