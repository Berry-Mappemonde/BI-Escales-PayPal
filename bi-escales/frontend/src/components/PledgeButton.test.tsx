import { fireEvent, render, screen, act } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge, fetchPledgeMode } from "../api/escales";
import { emitPledgeReturn } from "../paypal/pledgeReturnEvents";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "AUTHORIZE" }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false }),
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
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
    await i18n.changeLanguage("fr");
  });

  it.each([
    ["en", "VAULT", "PayPal sandbox: no real money moves. PayPal saves your payment method; nothing is charged now."],
    ["fr", "VAULT", "Mode test PayPal : aucun argent réel ne circule. PayPal enregistre votre moyen de paiement ; rien n’est débité maintenant."],
    ["en", "AUTHORIZE", "PayPal sandbox: no real money moves."],
    ["fr", "AUTHORIZE", "Mode test PayPal : aucun argent réel ne circule."],
  ] as const)("shows %s %s checkout copy from the fetched mode", async (lang, payment_mode, expected) => {
    await i18n.changeLanguage(lang);
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode });
    render(<PledgeButton values={values} />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(fetchPledgeMode).toHaveBeenCalledTimes(1);
    expect(fetchPledgeMode).toHaveBeenCalledWith(values.milestone_id, values.kind);
    expect(createPledge).not.toHaveBeenCalled();
    if (payment_mode === "VAULT") {
      expect(screen.queryByText(/AUTHORIZE/)).toBeNull();
    }
  });

  it("hides an unresolved mode and ignores a response for the previous stop", async () => {
    await i18n.changeLanguage("en");
    let finishOld: (mode: { payment_mode: "AUTHORIZE" }) => void = () => {};
    vi.mocked(fetchPledgeMode)
      .mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce({ payment_mode: "VAULT" });
    const { rerender } = render(<PledgeButton values={{ ...values, milestone_id: "dep-ajaccio-corse" }} />);
    expect(screen.queryByText(/AUTHORIZE|PayPal saves your payment method/)).toBeNull();
    rerender(<PledgeButton values={values} />);
    expect(await screen.findByText("PayPal sandbox: no real money moves. PayPal saves your payment method; nothing is charged now.")).toBeInTheDocument();
    await act(async () => { finishOld({ payment_mode: "AUTHORIZE" }); });
    expect(screen.queryByText(/AUTHORIZE/)).toBeNull();
    expect(screen.getByText("PayPal sandbox: no real money moves. PayPal saves your payment method; nothing is charged now.")).toBeInTheDocument();
  });

  it("clears the mode label when the kind changes and the lookup fails", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchPledgeMode)
      .mockResolvedValueOnce({ payment_mode: "VAULT" })
      .mockRejectedValueOnce(new Error("offline"));
    const { rerender } = render(<PledgeButton values={values} />);
    await screen.findByText("PayPal sandbox: no real money moves. PayPal saves your payment method; nothing is charged now.");
    await act(async () => { rerender(<PledgeButton values={{ ...values, kind: "cabin" }} />); });
    expect(screen.queryByText(/AUTHORIZE|PayPal saves your payment method/)).toBeNull();
    expect(createPledge).not.toHaveBeenCalled();
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
    fireEvent.click(screen.getByRole("button", { name: "Continuer avec PayPal" }));
    const link = await screen.findByTestId("paypal-approve-link");
    expect(link).toHaveAttribute("href", "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1");
    expect(link).not.toHaveAttribute("target");
    expect(createPledge).toHaveBeenCalledWith({ ...values, lang: "fr" }, expect.any(String));
    fireEvent.click(link);
    expect(screen.queryByTestId("pledge-authorize")).toBeNull();
    expect(screen.getByText(/Votre promesse est confirmée à votre retour/)).toBeInTheDocument();
  });

  it("affiche le bouton d’enregistrement Vault", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { assign }, writable: true });
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "VAULT" });

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

    fireEvent.click(screen.getByRole("button", { name: "Continuer avec PayPal" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Continuer avec PayPal" }));
    expect(await screen.findByText(/Votre promesse est confirmée à votre retour/)).toBeInTheDocument();

    await act(async () => {
      emitPledgeReturn({ pledgeId: "pledge-return-1", outcome: "authorized" });
    });
    expect(screen.queryByText(/Votre promesse est confirmée à votre retour/)).toBeNull();
    expect(screen.queryByText(/Préparation de votre promesse/)).toBeNull();
    expect(screen.queryByTestId("paypal-approve-link")).toBeNull();
  });

  it("shows project CAPTURE copy without boat arrival wording", async () => {
    vi.mocked(createPledge).mockResolvedValue({
      id: "proj-1",
      status: "created",
      intent: "CAPTURE",
      payment_mode: "CAPTURE",
      currency: "EUR",
      amount_eur: "15.00",
      description: "École",
      milestone_id: "",
      approve_link: "https://www.sandbox.paypal.com/checkoutnow?token=ORDERP",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...values, kind: "project_pledge", milestone_id: "", target_id: "projet-ecole" }} />
      </I18nextProvider>,
    );

    expect(screen.getByText(/Débité immédiatement/)).toBeInTheDocument();
    expect(screen.queryByText(/Autorisation PayPal/)).toBeNull();
    expect(screen.queryByText(/arrivée/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continuer avec PayPal" }));
    expect(await screen.findByText(/contribution projet est débitée au retour/)).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Continuer avec PayPal" }));
    expect(await screen.findByTestId("paypal-approve-link")).toBeInTheDocument();

    await act(async () => {
      emitPledgeReturn({ pledgeId: "pledge-return-2", outcome: "error", message: "order not approved" });
    });
    expect(screen.queryByTestId("paypal-approve-link")).toBeNull();
    expect(screen.queryByText(/Votre promesse est confirmée à votre retour/)).toBeNull();
    expect(screen.getByText(/order not approved/)).toBeInTheDocument();
  });
});
