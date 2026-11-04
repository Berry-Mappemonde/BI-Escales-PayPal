import { fireEvent, render, screen, act } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge } from "../api/escales";
import { emitPledgeReturn } from "../paypal/pledgeReturnEvents";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  isVaultPledge: (pledge: { payment_mode?: string; intent?: string }) =>
    pledge.payment_mode === "VAULT" || pledge.intent === "VAULT",
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

  it("affiche le bouton d’enregistrement Vault", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { assign }, writable: true });

    vi.mocked(createPledge).mockResolvedValue({
      id: "vault-1",
      status: "created",
      intent: "VAULT",
      payment_mode: "VAULT",
      currency: "EUR",
      amount_eur: "20.00",
      description: values.description,
      milestone_id: values.milestone_id,
      approve_link: "https://www.sandbox.paypal.com/vault/setup",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Créer l’ordre PayPal" }));
    expect(await screen.findByTestId("pledge-authorize")).toBeInTheDocument();
    expect(screen.getByText(/Redirection vers PayPal/)).toBeInTheDocument();
  });

  it("clears in-progress status after PayPal return authorization", async () => {
    vi.mocked(createPledge).mockResolvedValue({
      id: "pledge-return-1",
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

    fireEvent.click(screen.getByRole("button", { name: "Créer l’ordre PayPal" }));
    expect(await screen.findByText(/Au retour, l’autorisation/)).toBeInTheDocument();

    await act(async () => {
      emitPledgeReturn({ pledgeId: "pledge-return-1", outcome: "authorized" });
    });
    expect(screen.queryByText(/Au retour, l’autorisation/)).toBeNull();
    expect(screen.queryByText(/Création de la promesse/)).toBeNull();
    expect(screen.queryByTestId("paypal-approve-link")).toBeNull();
  });

  it("clears in-progress status when PayPal return authorization fails", async () => {
    vi.mocked(createPledge).mockResolvedValue({
      id: "pledge-return-2",
      status: "created",
      intent: "AUTHORIZE",
      currency: "EUR",
      amount_eur: "20.00",
      description: values.description,
      milestone_id: values.milestone_id,
      approve_link: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER2",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Créer l’ordre PayPal" }));
    expect(await screen.findByTestId("paypal-approve-link")).toBeInTheDocument();

    await act(async () => {
      emitPledgeReturn({ pledgeId: "pledge-return-2", outcome: "error", message: "order not approved" });
    });
    expect(screen.queryByTestId("paypal-approve-link")).toBeNull();
    expect(screen.queryByText(/Au retour, l’autorisation/)).toBeNull();
    expect(screen.getByText(/order not approved/)).toBeInTheDocument();
  });
});
