import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchCrewSupporterPlan, approveCrewSubscription } from "../api/escales";
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


it("F06 keeps approval pending until the backend verifies ACTIVE", async () => {
  vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "audit-public-client");
  let callbacks: Record<string, any> | undefined;
  vi.mocked(loadPayPalSubscriptionSdk).mockResolvedValue({ Buttons: (config: Record<string, any>) => { callbacks = config; return { render: async () => {}, close: async () => {} }; } });
  let finish!: (value: Record<string, unknown>) => void;
  vi.mocked(approveCrewSubscription).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<CrewSubscribeButton planId="PLAN" />);
  await waitFor(() => expect(callbacks).toBeDefined());
  const completion = callbacks!.onApprove({ subscriptionID: "SUB" });
  expect(completion).toBeInstanceOf(Promise);
  finish({ status: "ACTIVE", plan_id: "PLAN", subscription_id: "SUB" });
  await completion;
  vi.unstubAllEnvs();
});


it.each(["APPROVAL_PENDING", "CANCELLED"])("F06 refuses non-ACTIVE verification %s without an audit write", async status => {
  vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "audit-public-client");
  let callbacks: Record<string, any> | undefined;
  vi.mocked(loadPayPalSubscriptionSdk).mockResolvedValue({ Buttons: (config: Record<string, any>) => { callbacks = config; return { render: async () => {}, close: async () => {} }; } });
  vi.mocked(approveCrewSubscription).mockResolvedValue({ status, plan_id: "PLAN" });
  render(<CrewSubscribeButton planId="PLAN" />);
  await waitFor(() => expect(callbacks).toBeDefined());
  await expect(callbacks!.onApprove({ subscriptionID: `SUB-${status}` })).rejects.toThrow(/not been verified/);
  expect(screen.queryByText(i18n.t("pledge.crewSubscribeSaved"))).toBeNull();
  vi.unstubAllEnvs();
});

it("F06 transient verification failure can retry after remount", async () => {
  vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "audit-public-client");
  let callbacks: Record<string, any> | undefined;
  vi.mocked(loadPayPalSubscriptionSdk).mockResolvedValue({ Buttons: (config: Record<string, any>) => { callbacks = config; return { render: async () => {}, close: async () => {} }; } });
  vi.mocked(approveCrewSubscription).mockReset();
  vi.mocked(approveCrewSubscription).mockRejectedValueOnce(new TypeError("temporary unavailable")).mockResolvedValueOnce({ status: "ACTIVE", plan_id: "RETRY-PLAN" });
  const first = render(<CrewSubscribeButton planId="RETRY-PLAN" />);
  await waitFor(() => expect(callbacks).toBeDefined());
  await expect(callbacks!.onApprove({ subscriptionID: "RETRY-SUB" })).rejects.toThrow(/temporary/);
  first.unmount(); callbacks = undefined;
  render(<CrewSubscribeButton planId="RETRY-PLAN" />);
  await waitFor(() => expect(callbacks).toBeDefined());
  await callbacks!.onApprove({ subscriptionID: "RETRY-SUB" });
  expect(approveCrewSubscription).toHaveBeenCalledTimes(2);
  vi.unstubAllEnvs();
});
