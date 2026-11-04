import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchCrewSupporterPlan } from "../api/escales";
import { CrewSubscribeButton } from "./CrewSubscribeButton";

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    fetchCrewSupporterPlan: vi.fn(),
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

  it("loads plan id from the read-only plan route", async () => {
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: "PLAN-PUBLIC" });

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(fetchCrewSupporterPlan).toHaveBeenCalled();
    });
    expect(await screen.findByTestId("crew-subscribe-host")).toBeInTheDocument();
  });

  it("shows a dedicated loading label while the plan loads", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchCrewSupporterPlan).mockReturnValue(new Promise(() => {}));

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton />
      </I18nextProvider>,
    );

    expect(screen.getByText(/Loading Crew supporter plan/i)).toBeInTheDocument();
  });
});
