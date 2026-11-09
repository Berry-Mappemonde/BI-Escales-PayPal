import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchPledgeMode } from "../api/escales";
import { loadPayPalSdk } from "../paypal/paypalSdk";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "AUTHORIZE" }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: true, wallet_pay: true }),
  isVaultPledge: () => false,
}));

vi.mock("../paypal/paypalSdk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../paypal/paypalSdk")>();
  return { ...actual, loadPayPalSdk: vi.fn() };
});

const values = {
  amount_eur: "40.00",
  description: "40 milles",
  milestone_id: "dep-mayotte",
  kind: "mile",
  target_id: "dep-mayotte",
};

describe("PledgeButton with a broken PayPal SDK (stopover crash regression)", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    await i18n.changeLanguage("en");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders the stopover sheet when Buttons/Messages/Googlepay lack render or throw", async () => {
    const ns = {
      Buttons: vi.fn(() => {
        throw new Error("Can not register multiple components with the same tag: paypal-buttons");
      }),
      Messages: vi.fn(() => ({})),
      Googlepay: vi.fn(() => ({ config: vi.fn() })),
      Applepay: vi.fn(() => ({ config: vi.fn() })),
      CardFields: vi.fn(() => ({ isEligible: () => true, NumberField: () => ({}) })),
    };
    vi.mocked(loadPayPalSdk).mockResolvedValue(ns as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(ns.Buttons).toHaveBeenCalled());
    await waitFor(() => expect(ns.Googlepay).toHaveBeenCalled());
    expect(screen.getByTestId("paypal-buttons")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).toBeInTheDocument();
    expect(screen.queryByTestId("paypal-buttons-error")).toBeNull();
  });

  it("loads the checkout SDK once, after feature flags are known", async () => {
    const render1 = vi.fn(async () => undefined);
    vi.mocked(loadPayPalSdk).mockResolvedValue({ Buttons: vi.fn(() => ({ render: render1 })) } as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(render1).toHaveBeenCalled());
    expect(loadPayPalSdk).toHaveBeenCalledTimes(1);
    expect(vi.mocked(loadPayPalSdk).mock.calls[0]).toEqual(["sandbox-client-id", "en", "authorize", true]);
  });

  it("hides the redirect fallback after Smart Buttons render successfully", async () => {
    const renderButtons = vi.fn(async () => undefined);
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn(() => ({ render: renderButtons })),
    } as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).toBeInTheDocument();
    await waitFor(() => expect(renderButtons).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: i18n.t("pledge.create") })).toBeNull(),
    );
    expect(screen.getByTestId("paypal-smart-buttons")).toHaveAttribute("data-smart-buttons", "1");
    expect(fetchPledgeMode).toHaveBeenCalledWith(values.milestone_id, values.kind);
  });

  it("renders project Smart Buttons without fetching payment mode", async () => {
    const renderButtons = vi.fn(async () => undefined);
    const createButtons = vi.fn(() => ({ render: renderButtons }));
    vi.mocked(loadPayPalSdk).mockResolvedValue({ Buttons: createButtons } as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...values, kind: "project_pledge" }} />
      </I18nextProvider>,
    );

    await waitFor(() => expect(renderButtons).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: i18n.t("pledge.create") })).toBeNull(),
    );
    expect(fetchPledgeMode).not.toHaveBeenCalled();
    expect(loadPayPalSdk).toHaveBeenCalledWith("sandbox-client-id", "en", "capture", true);
    const calls = vi.mocked(createButtons).mock.calls as unknown as Array<
      [{ style?: { layout?: string; label?: string } }]
    >;
    expect(calls[0]?.[0]).toMatchObject({
      style: { layout: "vertical", label: "donate" },
    });
  });

  it("keeps the redirect fallback and skips Smart Buttons for VAULT mode", async () => {
    const renderButtons = vi.fn(async () => undefined);
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "VAULT" });
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn(() => ({ render: renderButtons })),
    } as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalledWith(values.milestone_id, values.kind));
    expect(renderButtons).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).toBeInTheDocument();
  });

  it("keeps the redirect fallback when payment mode cannot be fetched", async () => {
    const renderButtons = vi.fn(async () => undefined);
    vi.mocked(fetchPledgeMode).mockRejectedValue(new Error("Mode unavailable"));
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn(() => ({ render: renderButtons })),
    } as never);
    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalledWith(values.milestone_id, values.kind));
    await waitFor(() => expect(loadPayPalSdk).toHaveBeenCalled());
    expect(renderButtons).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).toBeInTheDocument();
  });

  it("rechecks payment mode when the milestone or kind changes", async () => {
    const renderButtons = vi.fn(async () => undefined);
    vi.mocked(loadPayPalSdk).mockResolvedValue({
      Buttons: vi.fn(() => ({ render: renderButtons })),
    } as never);
    const view = render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalledWith(values.milestone_id, values.kind));

    const updatedValues = { ...values, milestone_id: "dep-autre", kind: "cabin_leg" };
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "VAULT" });
    view.rerender(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={updatedValues} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(fetchPledgeMode).toHaveBeenCalledWith(updatedValues.milestone_id, updatedValues.kind));
    await waitFor(() => expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).toBeInTheDocument());
  });
});
