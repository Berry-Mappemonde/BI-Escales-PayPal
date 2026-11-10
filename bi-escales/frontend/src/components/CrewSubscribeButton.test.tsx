import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchCrewSupporterPlan } from "../api/escales";
import { CrewSubscribeButton, CrewSupporterPublicSection } from "./CrewSubscribeButton";
import { loadPayPalSubscriptionSdk } from "../paypal/paypalSdk";

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    fetchCrewSupporterPlan: vi.fn(),
    approveCrewSubscription: vi.fn(),
    recordSubscription: vi.fn(),
  };
});

vi.mock("../paypal/paypalSdk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../paypal/paypalSdk")>();
  return { ...actual, loadPayPalSubscriptionSdk: vi.fn() };
});

let sdkNamespace: { Buttons?: unknown } = {};

describe("CrewSubscribeButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sdkNamespace = {
      Buttons: vi.fn(() => ({
        render: vi.fn().mockResolvedValue(undefined),
        close: vi.fn().mockResolvedValue(undefined),
      })),
    };
    vi.mocked(loadPayPalSubscriptionSdk).mockImplementation(async () => sdkNamespace as never);
  });

  it("closes the previous PayPal Buttons instance when language changes", async () => {
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: "PLAN-PUBLIC" });
    const closeFn = vi.fn().mockResolvedValue(undefined);
    const buttonsFactory = vi.fn(() => ({
      render: vi.fn().mockResolvedValue(undefined),
      close: closeFn,
    }));
    sdkNamespace = { Buttons: buttonsFactory };

    const { rerender } = render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN-PUBLIC" />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(buttonsFactory).toHaveBeenCalledTimes(1);
    });

    await i18n.changeLanguage("fr");
    rerender(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN-PUBLIC" />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(closeFn).toHaveBeenCalled();
      expect(buttonsFactory).toHaveBeenCalledTimes(2);
    });
  });

  it("asks PayPal for its quietest button and follows the theme", async () => {
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: "PLAN-PUBLIC" });
    const closeFn = vi.fn().mockResolvedValue(undefined);
    const buttonsFactory = vi.fn((_config: { style?: Record<string, unknown>; createSubscription?: unknown; onApprove?: unknown }) => ({
      render: vi.fn().mockResolvedValue(undefined),
      close: closeFn,
    }));
    sdkNamespace = { Buttons: buttonsFactory };
    document.documentElement.dataset.theme = "dark";

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN-PUBLIC" />
      </I18nextProvider>,
    );

    await waitFor(() => expect(buttonsFactory).toHaveBeenCalledTimes(1));
    const config = buttonsFactory.mock.calls[0][0];
    // One 32px row: no stacked card button, no tagline, PayPal's black on the dark rail.
    expect(config.style).toEqual({
      label: "subscribe",
      layout: "horizontal",
      tagline: false,
      height: 32,
      shape: "rect",
      color: "black",
    });
    // The subscription flow itself is still wired.
    expect(typeof config.createSubscription).toBe("function");
    expect(typeof config.onApprove).toBe("function");

    // Switching to the light theme redraws the button in silver and closes the old one.
    document.documentElement.dataset.theme = "light";
    await waitFor(() => expect(buttonsFactory).toHaveBeenCalledTimes(2));
    expect(buttonsFactory.mock.calls[1][0].style).toMatchObject({ color: "silver", height: 32, layout: "horizontal" });
    expect(closeFn).toHaveBeenCalled();
    delete document.documentElement.dataset.theme;
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
        <CrewSupporterPublicSection adminKey="sandbox-admin" />
      </I18nextProvider>,
    );

    expect(screen.getByText(/Loading Crew supporter plan/i)).toBeInTheDocument();
  });

  it("survives a PayPal Buttons component without render (no app crash)", async () => {
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    const buttonsFactory = vi.fn(() => ({}));
    sdkNamespace = { Buttons: buttonsFactory };
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN-PUBLIC" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(buttonsFactory).toHaveBeenCalled());
    expect(screen.getByTestId("crew-subscribe-host")).toBeInTheDocument();
    expect(screen.queryByTestId("crew-subscribe-error")).toBeNull();
  });

  it("hides the crew block for visitors when the plan id is missing", async () => {
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: null });

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSupporterPublicSection />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(fetchCrewSupporterPlan).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("crew-supporter-public")).toBeNull();
    expect(screen.queryByText(/Ask the treasurer/i)).toBeNull();
    expect(document.querySelector(".notice.error")).toBeNull();
  });

  it("hides the crew button for visitors when the plan id is missing", async () => {
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: null });

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(fetchCrewSupporterPlan).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("crew-subscribe")).toBeNull();
    expect(document.querySelector(".notice.error")).toBeNull();
  });

  it("shows a neutral treasurer hint when the plan id is missing and admin key is set", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: null });

    render(
      <I18nextProvider i18n={i18n}>
        <CrewSupporterPublicSection adminKey="sandbox-admin" />
      </I18nextProvider>,
    );

    const hint = await screen.findByTestId("crew-subscribe-treasurer-hint");
    expect(hint).toHaveClass("hint");
    expect(hint).not.toHaveClass("error");
    expect(hint.textContent).toMatch(/Ensure Crew supporter plan \(sandbox\)/i);
    expect(document.querySelector(".notice.error")).toBeNull();
  });

  it("does not read window.paypal (a stopover SDK there cannot break the Crew button)", async () => {
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-client-id");
    const stopoverButtons = vi.fn(() => ({ render: vi.fn().mockResolvedValue(undefined) }));
    window.paypal = { Buttons: stopoverButtons };
    const crewButtons = vi.fn(() => ({ render: vi.fn().mockResolvedValue(undefined) }));
    sdkNamespace = { Buttons: crewButtons };
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN-PUBLIC" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(crewButtons).toHaveBeenCalled());
    expect(stopoverButtons).not.toHaveBeenCalled();
    delete window.paypal;
  });
});
