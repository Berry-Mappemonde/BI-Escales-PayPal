import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createCrewSubscriptionCheckout } from "../api/escales";
import { CrewSubscribeButton } from "./CrewSubscribeButton";

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    createCrewSubscriptionCheckout: vi.fn(),
    approveCrewSubscription: vi.fn(),
    recordSubscription: vi.fn(),
  };
});

vi.mock("../paypal/paypalSdk", () => ({
  loadPayPalSubscriptionSdk: vi.fn().mockResolvedValue(undefined),
}));

describe("CrewSubscribeButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.paypal = {
      Buttons: vi.fn(() => ({ render: vi.fn().mockResolvedValue(undefined) })),
    };
  });

  it("loads checkout from the public create-subscription route", async () => {
    vi.mocked(createCrewSubscriptionCheckout).mockResolvedValue({
      plan_id: "PLAN-PUBLIC",
      subscription_id: "I-PUBLIC",
      approve_link: "https://paypal.test/approve",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(createCrewSubscriptionCheckout).toHaveBeenCalled();
    });
    expect(await screen.findByTestId("crew-subscribe-host")).toBeInTheDocument();
  });
});
