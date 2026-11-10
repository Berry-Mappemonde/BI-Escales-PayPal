import { render, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge, fetchPledgeMode } from "../api/escales";
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

const stopValues = {
  amount_eur: "1.00",
  description: "Miles",
  milestone_id: "dep-la-rochelle",
  kind: "miles",
  target_id: "",
};

describe("PledgeButton Smart Buttons while an order is being created", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    await i18n.changeLanguage("en");
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
  });

  it("keeps the same Smart Buttons open while createOrder is pending", async () => {
    const close = vi.fn();
    const renderButtons = vi.fn(async () => undefined);
    let config: { createOrder?: () => Promise<string> } = {};
    const Buttons = vi.fn((cfg) => {
      config = cfg;
      return { render: renderButtons, close };
    });
    vi.mocked(loadPayPalSdk).mockResolvedValue({ Buttons } as never);
    let resolvePledge: (value: unknown) => void = () => undefined;
    vi.mocked(createPledge).mockImplementation(
      () => new Promise((resolve) => { resolvePledge = resolve; }) as never,
    );

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={stopValues} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(renderButtons).toHaveBeenCalledTimes(1));

    const pending = config.createOrder!();
    await waitFor(() => expect(createPledge).toHaveBeenCalledTimes(1));
    // busy is now true: the buttons (and the PayPal window they own) must survive it.
    expect(close).not.toHaveBeenCalled();
    expect(Buttons).toHaveBeenCalledTimes(1);

    resolvePledge({ id: "p1", order_id: "ORDER-1", approve_link: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1" });
    await expect(pending).resolves.toBe("ORDER-1");
    expect(close).not.toHaveBeenCalled();
  });
});
