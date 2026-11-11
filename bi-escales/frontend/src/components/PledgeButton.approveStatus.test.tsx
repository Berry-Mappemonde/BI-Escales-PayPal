import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { authorizePledge, createPledge, fetchPledgeMode } from "../api/escales";
import { loadPayPalSdk } from "../paypal/paypalSdk";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn(),
  fetchSchedule: vi.fn().mockResolvedValue({ legs: [] }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false, wallet_pay: false }),
  isVaultPledge: () => false,
}));

vi.mock("../paypal/paypalSdk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../paypal/paypalSdk")>();
  return { ...actual, loadPayPalSdk: vi.fn() };
});

const stopValues = { amount_eur: "1.00", description: "Miles", milestone_id: "dep-la-rochelle", kind: "mile", target_id: "dep-la-rochelle" };
const projectValues = { amount_eur: "5.00", description: "Reef survey", milestone_id: "", kind: "project_pledge", target_id: "p-1" };

type SmartConfig = { createOrder?: () => Promise<string>; onApprove?: () => Promise<void> };

/** Renders the button and hands back what it gave the PayPal Buttons factory. */
async function mountSmartButtons(values: typeof stopValues, onAuthorized = vi.fn()) {
  let config: SmartConfig = {};
  const renderButtons = vi.fn(async () => undefined);
  const Buttons = vi.fn((cfg: SmartConfig) => {
    config = cfg;
    return { render: renderButtons, close: vi.fn() };
  });
  vi.mocked(loadPayPalSdk).mockResolvedValue({ Buttons } as never);
  render(
    <I18nextProvider i18n={i18n}>
      <PledgeButton values={values} onAuthorized={onAuthorized} />
    </I18nextProvider>,
  );
  await waitFor(() => expect(renderButtons).toHaveBeenCalledTimes(1));
  return { config: () => config, onAuthorized, Buttons };
}

/** The payer clicks the PayPal button (createOrder), approves in PayPal, and PayPal calls onApprove. */
async function approveInPayPal(config: () => SmartConfig) {
  await act(async () => {
    await config().createOrder!();
  });
  await act(async () => {
    await config().onApprove!();
  });
}

const statusLine = () => document.querySelector(".pledge-button .status");
const STALE = /Approve in PayPal|Approuvez dans PayPal|Preparing your pledge|Préparation de votre promesse/;

describe("PledgeButton status after Smart Buttons approval", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    await i18n.changeLanguage("en");
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
    vi.mocked(createPledge).mockResolvedValue({ id: "p1", order_id: "ORDER-1", status: "created" } as never);
  });

  it("replaces the line with the success state once a stop pledge is authorised", async () => {
    const done = { id: "p1", status: "authorized", amount_eur: "1.00" };
    vi.mocked(authorizePledge).mockResolvedValue(done as never);
    const { config, onAuthorized } = await mountSmartButtons(stopValues);

    await approveInPayPal(config);

    expect(statusLine()).toHaveTextContent("Pledge authorized");
    expect(document.body.textContent).not.toMatch(STALE);
    expect(screen.queryByText(/Pledge error/)).toBeNull();
    // The calls themselves are as before: one order, one authorisation, one callback.
    expect(createPledge).toHaveBeenCalledTimes(1);
    expect(authorizePledge).toHaveBeenCalledTimes(1);
    expect(authorizePledge).toHaveBeenCalledWith("p1");
    expect(onAuthorized).toHaveBeenCalledTimes(1);
    expect(onAuthorized).toHaveBeenCalledWith(done);
  });

  it("shows the line while the payer is still in PayPal, before approval", async () => {
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "authorized" } as never);
    const { config } = await mountSmartButtons(stopValues);
    await act(async () => {
      await config().createOrder!();
    });
    expect(statusLine()).toHaveTextContent("Preparing your pledge…");
    expect(authorizePledge).not.toHaveBeenCalled();
  });

  it("says a project gift was charged, not authorised", async () => {
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "captured" } as never);
    const { config } = await mountSmartButtons(projectValues);

    await approveInPayPal(config);

    expect(statusLine()).toHaveTextContent("Payment received. Thank you.");
    expect(document.body.textContent).not.toMatch(STALE);
  });

  it("uses the server's answer, not the kind: a stop pledge the server captured reads as charged", async () => {
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "captured" } as never);
    const { config } = await mountSmartButtons({ ...stopValues, kind: "common_fund" });
    await approveInPayPal(config);
    expect(statusLine()).toHaveTextContent("Payment received. Thank you.");
  });

  it.each(["pending", "created", undefined])("clears the line when the server answers %j, rather than claim success", async (status) => {
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status } as never);
    const { config, onAuthorized } = await mountSmartButtons(stopValues);

    await approveInPayPal(config);

    expect(statusLine()).toBeNull();
    expect(document.body.textContent).not.toMatch(STALE);
    expect(onAuthorized).toHaveBeenCalledTimes(1);
  });

  it("shows the success state in French", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "authorized" } as never);
    const { config } = await mountSmartButtons(stopValues);
    await approveInPayPal(config);
    expect(statusLine()).toHaveTextContent("Promesse autorisée");

    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "captured" } as never);
    await approveInPayPal(config);
    expect(statusLine()).toHaveTextContent("Paiement reçu. Merci.");
    expect(document.body.textContent).not.toMatch(STALE);
  });

  it("leaves only the error when the authorisation fails", async () => {
    vi.mocked(authorizePledge).mockRejectedValue(new Error("authorization refused"));
    const { config, onAuthorized } = await mountSmartButtons(stopValues);

    await approveInPayPal(config);

    expect(screen.getByText(/authorization refused/)).toBeInTheDocument();
    expect(statusLine()).toBeNull();
    expect(document.body.textContent).not.toMatch(STALE);
    expect(onAuthorized).not.toHaveBeenCalled();
  });

  it("does not redraw the Smart Buttons when the status changes", async () => {
    vi.mocked(authorizePledge).mockResolvedValue({ id: "p1", status: "authorized" } as never);
    const { config, Buttons } = await mountSmartButtons(stopValues);
    await approveInPayPal(config);
    expect(Buttons).toHaveBeenCalledTimes(1);
  });
});
