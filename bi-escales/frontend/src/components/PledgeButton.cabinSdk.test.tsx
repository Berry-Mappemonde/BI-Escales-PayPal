import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge, fetchPledgeMode, fetchSchedule, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { loadPayPalSdk } from "../paypal/paypalSdk";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn(),
  fetchSchedule: vi.fn(),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false, wallet_pay: false }),
  isVaultPledge: (pledge: { payment_mode?: string; intent?: string; setup_token_id?: string; order_id?: string }) =>
    pledge.payment_mode === "VAULT"
    || pledge.intent === "VAULT"
    || Boolean(pledge.setup_token_id && !pledge.order_id),
}));

vi.mock("../paypal/paypalSdk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../paypal/paypalSdk")>();
  return { ...actual, loadPayPalSdk: vi.fn() };
});

const legs = [
  {
    id: "leg-la-rochelle-to-ajaccio-corse",
    from_name: "La Rochelle",
    to_name: "Ajaccio (Corse)",
  },
];

const cabinValues = {
  amount_eur: "80.00",
  description: "Cabin",
  milestone_id: "",
  kind: "cabin_leg",
  target_id: "",
};

describe("PledgeButton flow C (cabin_leg VAULT)", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    await i18n.changeLanguage("en");
    vi.mocked(fetchSchedule).mockResolvedValue({ legs });
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "VAULT" });
  });

  it("disables checkout until a leg is chosen and renders vault Smart Buttons", async () => {
    const renderButtons = vi.fn(async () => undefined);
    let buttonConfig: Record<string, unknown> = {};
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn((config) => {
        buttonConfig = config;
        return { render: renderButtons };
      }),
    } as never);

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={cabinValues} />
      </I18nextProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("cabin-leg-picker")).toBeInTheDocument());
    const createBtn = screen.getByRole("button", { name: i18n.t("pledge.create") });
    expect(createBtn).toBeDisabled();
    expect(fetchPledgeMode).not.toHaveBeenCalled();

    const option = screen.getAllByTestId("cabin-leg-option")[0];
    fireEvent.click(option);

    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalledWith(legs[0].id, "cabin_leg"));
    await waitFor(() => expect(renderButtons).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: i18n.t("pledge.create") })).toBeNull(),
    );
    expect(buttonConfig).toHaveProperty("createVaultSetupToken");
    expect(buttonConfig).not.toHaveProperty("createOrder");
  });

  it("keeps redirect fallback when the SDK does not render Smart Buttons", async () => {
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn(() => ({ render: vi.fn().mockRejectedValue(new Error("sdk down")) })),
    } as never);

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...cabinValues, milestone_id: legs[0].id, target_id: legs[0].id }} />
      </I18nextProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("cabin-leg-picker")).toBeInTheDocument());
    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalled());
    const createBtn = await screen.findByRole("button", { name: i18n.t("pledge.create") });
    expect(createBtn).not.toBeDisabled();
  });

  it("locks fallback creation while the pledge request is in flight", async () => {
    let resolvePledge: (value: PublicPledge) => void = () => {};
    vi.mocked(createPledge).mockImplementation(
      () =>
        new Promise<PublicPledge>((resolve) => {
          resolvePledge = resolve;
        }),
    );
    vi.mocked(loadPayPalSdk).mockResolvedValue({ Buttons: vi.fn(() => ({ render: vi.fn().mockRejectedValue(new Error("SDK unavailable")) })) } as never);

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...cabinValues, milestone_id: legs[0].id, target_id: legs[0].id }} />
      </I18nextProvider>,
    );

    const createBtn = await screen.findByRole("button", { name: i18n.t("pledge.create") });
    await waitFor(() => expect(createBtn).not.toBeDisabled());
    createBtn.click();
    await waitFor(() => expect(createBtn).toBeDisabled());
    resolvePledge({
      id: "v1",
      status: "created",
      payment_mode: "VAULT",
      intent: "VAULT",
      currency: "EUR",
      amount_eur: "80.00",
      description: "Cabin",
      milestone_id: legs[0].id,
      approve_link: "https://www.sandbox.paypal.com/vault/setup",
    });
    await waitFor(() => expect(createBtn).not.toBeDisabled());
    expect(registerVault).not.toHaveBeenCalled();
  });
});
