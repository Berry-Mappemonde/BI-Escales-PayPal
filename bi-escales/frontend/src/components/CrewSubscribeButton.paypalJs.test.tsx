/**
 * The PayPal JS version switch on the Crew subscription button: flag off (or unknown)
 * renders today's v5 button and never touches the v6 loader; flag on renders the v6
 * button and never touches the v5 loader.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { approveCrewSubscription, recordSubscription } from "../api/escales";
import { loadPayPalSubscriptionSdk as loadV5 } from "../paypal/paypalSdk";
import { loadPayPalSubscriptionSdk as loadV6 } from "../paypal/v6/paypalSdkV6";
import {
  PAYPAL_JS_FEATURES_TIMEOUT_MS,
  expectPayPalJsFeatures,
  notePayPalJsFeatures,
  resetPayPalJsVersionForTests,
} from "../paypal/paypalJsVersion";
import { CrewSubscribeButton, crewButtonStyle } from "./CrewSubscribeButton";

vi.mock("../api/escales", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/escales")>()),
  fetchCrewSupporterPlan: vi.fn(),
  approveCrewSubscription: vi.fn(),
  recordSubscription: vi.fn(),
  fetchFeatures: vi.fn(),
}));
vi.mock("../paypal/paypalSdk", async (load) => ({ ...(await load<object>()), loadPayPalSubscriptionSdk: vi.fn() }));
vi.mock("../paypal/v6/paypalSdkV6", async (load) => ({ ...(await load<object>()), loadPayPalSubscriptionSdk: vi.fn() }));

type Config = {
  style?: unknown;
  subscriptionPlanId?: string;
  createSubscription?: (data: unknown, actions: { subscription: { create: (body: unknown) => Promise<string> } }) => Promise<string>;
  onApprove: (data: { subscriptionID?: string }) => unknown;
};
const seen: { v5: Config[]; v6: Config[] } = { v5: [], v6: [] };
const fakeSdk = (bucket: Config[]) => ({
  Buttons: (config: Config) => {
    bucket.push(config);
    return { render: async () => {}, close: async () => {} };
  },
});

function show(props: Partial<React.ComponentProps<typeof CrewSubscribeButton>> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <CrewSubscribeButton planId="PLAN" {...props} />
    </I18nextProvider>,
  );
}

describe("CrewSubscribeButton and features.paypal_js_v6", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seen.v5.length = 0;
    seen.v6.length = 0;
    resetPayPalJsVersionForTests();
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-public-client");
    vi.mocked(loadV5).mockImplementation(async () => fakeSdk(seen.v5) as never);
    vi.mocked(loadV6).mockImplementation(async () => fakeSdk(seen.v6) as never);
    vi.mocked(recordSubscription).mockResolvedValue({} as never);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    resetPayPalJsVersionForTests();
  });

  describe("flag off", () => {
    it.each([
      ["no features answer yet", undefined],
      ["paypal_js_v6 false", { paypal_js_v6: false }],
      ["the features request failed", null],
    ])("renders the v5 button when %s", async (_case, features) => {
      if (features !== undefined) notePayPalJsFeatures(features);
      show();
      await waitFor(() => expect(seen.v5).toHaveLength(1));
      expect(loadV6).not.toHaveBeenCalled();
      expect(screen.getByTestId("crew-subscribe")).not.toHaveAttribute("data-paypal-js");
      // Today's quiet button style (#210) and no v6-only option.
      expect(seen.v5[0].style).toEqual(crewButtonStyle("dark"));
      expect(seen.v5[0]).not.toHaveProperty("subscriptionPlanId");
    });

    it("keeps the v5 approval behaviour: it does not wait for the server", async () => {
      notePayPalJsFeatures({ paypal_js_v6: false });
      vi.mocked(approveCrewSubscription).mockReturnValue(new Promise(() => {}) as never);
      show();
      await waitFor(() => expect(seen.v5).toHaveLength(1));
      expect(seen.v5[0].onApprove({ subscriptionID: "SUB" })).toBeUndefined();
      expect(approveCrewSubscription).toHaveBeenCalledWith({ subscription_id: "SUB", plan_id: "PLAN" });
    });
  });

  describe("the page is still waiting for its features answer", () => {
    it("loads no SDK until the answer, then v6 when the flag is on", async () => {
      expectPayPalJsFeatures();
      show();
      expect(screen.queryByTestId("crew-subscribe")).toBeNull();
      await act(async () => {});
      expect(loadV5).not.toHaveBeenCalled();
      expect(loadV6).not.toHaveBeenCalled();
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      expect(loadV5).not.toHaveBeenCalled();
    });

    it("then v5 when the flag is off", async () => {
      expectPayPalJsFeatures();
      show();
      act(() => notePayPalJsFeatures({ paypal_js_v6: false }));
      await waitFor(() => expect(seen.v5).toHaveLength(1));
      expect(loadV6).not.toHaveBeenCalled();
    });

    it("uses v5 when the answer never comes", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        expectPayPalJsFeatures();
        show();
        expect(screen.queryByTestId("crew-subscribe")).toBeNull();
        act(() => vi.advanceTimersByTime(PAYPAL_JS_FEATURES_TIMEOUT_MS));
        await waitFor(() => expect(seen.v5).toHaveLength(1));
        expect(loadV6).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe("flag on", () => {
    beforeEach(() => notePayPalJsFeatures({ paypal_js_v6: true }));

    it("renders the v6 button and never loads the v5 SDK", async () => {
      show();
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      expect(loadV5).not.toHaveBeenCalled();
      expect(screen.getByTestId("crew-subscribe")).toHaveAttribute("data-paypal-js", "v6");
      expect(screen.getByTestId("crew-subscribe-host")).toBeInTheDocument();
      // The plan on screen is sent as a constraint, and the #210 style is still passed.
      expect(seen.v6[0].subscriptionPlanId).toBe("PLAN");
      expect(seen.v6[0].style).toEqual(crewButtonStyle("dark"));
    });

    it("asks the server to create the subscription for the plan on screen", async () => {
      show();
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      const create = vi.fn().mockResolvedValue("SUB");
      await seen.v6[0].createSubscription!({}, { subscription: { create } });
      expect(create).toHaveBeenCalledWith({ plan_id: "PLAN" });
    });

    it("F06: the approval stays pending until the server has verified ACTIVE", async () => {
      let finish!: (value: Record<string, unknown>) => void;
      vi.mocked(approveCrewSubscription).mockReturnValue(new Promise((resolve) => { finish = resolve; }) as never);
      show();
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      let completion!: Promise<unknown>;
      act(() => {
        completion = seen.v6[0].onApprove({ subscriptionID: "SUB" }) as Promise<unknown>;
      });
      expect(completion).toBeInstanceOf(Promise);
      expect(screen.queryByText(i18n.t("pledge.crewSubscribeSaved"))).toBeNull();
      await act(async () => {
        finish({ status: "ACTIVE", plan_id: "PLAN", subscription_id: "SUB" });
        await completion;
      });
      expect(screen.getByText(i18n.t("pledge.crewSubscribeSaved"))).toBeInTheDocument();
    });

    it.each(["APPROVAL_PENDING", "CANCELLED"])("F06: a %s subscription is not shown as saved", async (status) => {
      vi.mocked(approveCrewSubscription).mockResolvedValue({ status, plan_id: "PLAN" } as never);
      show({ adminKey: "treasurer" });
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await expect(seen.v6[0].onApprove({ subscriptionID: `SUB-${status}` })).rejects.toThrow(/not been verified/);
      });
      expect(screen.queryByText(i18n.t("pledge.crewSubscribeSaved"))).toBeNull();
      expect(recordSubscription).not.toHaveBeenCalled();
    });

    it("F03: an ACTIVE subscription on another plan than the one on screen is refused", async () => {
      vi.mocked(approveCrewSubscription).mockResolvedValue({ status: "ACTIVE", plan_id: "OTHER-PLAN" } as never);
      show();
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await expect(seen.v6[0].onApprove({ subscriptionID: "SUB-OTHER" })).rejects.toThrow(/not been verified/);
      });
      expect(screen.queryByText(i18n.t("pledge.crewSubscribeSaved"))).toBeNull();
    });

    it("F06: a failed verification can be retried after a remount", async () => {
      vi.mocked(approveCrewSubscription)
        .mockRejectedValueOnce(new TypeError("temporary unavailable"))
        .mockResolvedValueOnce({ status: "ACTIVE", plan_id: "RETRY-PLAN" } as never);
      const first = show({ planId: "RETRY-PLAN" });
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await expect(seen.v6[0].onApprove({ subscriptionID: "RETRY-SUB" })).rejects.toThrow(/temporary/);
      });
      first.unmount();
      show({ planId: "RETRY-PLAN" });
      await waitFor(() => expect(seen.v6).toHaveLength(2));
      await act(async () => {
        await seen.v6[1].onApprove({ subscriptionID: "RETRY-SUB" });
      });
      expect(approveCrewSubscription).toHaveBeenCalledTimes(2);
    });

    it("a missing subscription id is an error, not a silent success", async () => {
      show();
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await expect(seen.v6[0].onApprove({})).rejects.toThrow(/Subscription ID missing/);
      expect(approveCrewSubscription).not.toHaveBeenCalled();
    });
  });
});
