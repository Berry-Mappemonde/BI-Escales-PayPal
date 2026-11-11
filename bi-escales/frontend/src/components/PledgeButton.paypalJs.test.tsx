/**
 * The PayPal JS version switch on PledgeButton: flag off (or unknown) renders today's
 * v5 checkout and never touches the v6 loader; flag on renders the v6 checkout and
 * never touches the v5 loader.
 */
import i18n from "../i18n";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authorizePledge, createPledge, fetchFeatures, registerVault } from "../api/escales";
import { loadPayPalSdk as loadV5 } from "../paypal/paypalSdk";
import { loadPayPalSdk as loadV6 } from "../paypal/v6/paypalSdkV6";
import { expectPayPalJsFeatures, notePayPalJsFeatures, resetPayPalJsVersionForTests } from "../paypal/paypalJsVersion";
import { hasAttempt, reconcileAttempt } from "../paypal/v6/checkoutAttempts";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  authorizePledge: vi.fn(),
  registerVault: vi.fn(),
  fetchFeatures: vi.fn(),
  fetchPledgeMode: vi.fn(async () => ({ payment_mode: "AUTHORIZE" })),
  fetchSchedule: vi.fn(async () => ({})),
  isVaultPledge: (pledge: { payment_mode?: string }) => pledge?.payment_mode === "VAULT",
}));
vi.mock("../paypal/paypalSdk", async (load) => ({ ...(await load<object>()), loadPayPalSdk: vi.fn() }));
vi.mock("../paypal/v6/paypalSdkV6", async (load) => ({ ...(await load<object>()), loadPayPalSdk: vi.fn() }));

type Callbacks = Record<string, (...args: never[]) => unknown> & { style?: unknown; offerPayLater?: boolean };
const seen: { v5: Callbacks[]; v6: Callbacks[] } = { v5: [], v6: [] };
const fakeSdk = (bucket: Callbacks[]) => ({
  Buttons: (config: Callbacks) => {
    bucket.push(config);
    return { render: async () => {}, close: async () => {} };
  },
});

const values = { amount_eur: "20.00", milestone_id: "dep-la-rochelle", kind: "mile", target_id: "dep-la-rochelle", description: "La Rochelle — Sponsored miles" };

describe("PledgeButton and features.paypal_js_v6", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seen.v5.length = 0;
    seen.v6.length = 0;
    sessionStorage.clear();
    resetPayPalJsVersionForTests();
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-public-client");
    vi.mocked(fetchFeatures).mockResolvedValue({});
    vi.mocked(loadV5).mockImplementation(async () => fakeSdk(seen.v5) as never);
    vi.mocked(loadV6).mockImplementation(async () => fakeSdk(seen.v6) as never);
    vi.mocked(createPledge).mockResolvedValue({ id: "PLEDGE-1", order_id: "ORDER-1", amount_eur: "20.00" } as never);
    vi.mocked(authorizePledge).mockResolvedValue({ id: "PLEDGE-1", status: "authorized", amount_eur: "20.00" } as never);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    resetPayPalJsVersionForTests();
  });

  describe("flag off", () => {
    it.each([
      ["no features answer yet", undefined],
      ["paypal_js_v6 false", { paypal_js_v6: false }],
      ["paypal_js_v6 missing", {}],
      ["the features request failed", null],
    ])("renders the v5 checkout when %s", async (_case, features) => {
      if (features !== undefined) notePayPalJsFeatures(features);
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v5).toHaveLength(1));
      expect(loadV6).not.toHaveBeenCalled();
      expect(seen.v6).toHaveLength(0);
      expect(screen.getByTestId("paypal-buttons")).not.toHaveAttribute("data-paypal-js");
      // The v5 loader is called with today's arguments: (client, lang, intent, wallet, currency, vault).
      expect(vi.mocked(loadV5).mock.calls[0]).toEqual(["sandbox-public-client", expect.any(String), "authorize", false, "EUR", false]);
    });

    it("approves through the v5 path and writes no v6 attempt", async () => {
      notePayPalJsFeatures({ paypal_js_v6: false });
      const onAuthorized = vi.fn();
      render(<PledgeButton values={values} onAuthorized={onAuthorized} />);
      await waitFor(() => expect(seen.v5).toHaveLength(1));
      await act(async () => {
        await seen.v5[0].createOrder();
      });
      await act(async () => {
        await seen.v5[0].onApprove();
      });
      expect(authorizePledge).toHaveBeenCalledWith("PLEDGE-1");
      expect(onAuthorized).toHaveBeenCalledTimes(1);
      expect(sessionStorage.getItem("escales-v6-attempts")).toBeNull();
      expect(hasAttempt("PLEDGE-1")).toBe(false);
    });
  });

  describe("the page is still waiting for its features answer", () => {
    it("renders no checkout and loads no SDK until the answer", async () => {
      expectPayPalJsFeatures();
      render(<PledgeButton values={values} />);
      expect(screen.queryByTestId("paypal-buttons")).toBeNull();
      await act(async () => {});
      expect(loadV5).not.toHaveBeenCalled();
      expect(loadV6).not.toHaveBeenCalled();
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      expect(loadV5).not.toHaveBeenCalled();
    });
  });

  describe("flag on", () => {
    beforeEach(() => notePayPalJsFeatures({ paypal_js_v6: true }));

    it("renders the v6 checkout and never loads the v5 SDK", async () => {
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      expect(loadV5).not.toHaveBeenCalled();
      expect(seen.v5).toHaveLength(0);
      expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-paypal-js", "v6");
      // v6 asks eligibility for a payment flow and the amount.
      expect(vi.mocked(loadV6).mock.calls.at(-1)).toEqual([
        "sandbox-public-client", expect.any(String), "authorize", false, "EUR", "ONE_TIME_PAYMENT", "20.00",
      ]);
    });

    it("keeps the same markup and test ids as the v5 checkout", async () => {
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      for (const id of ["paypal-buttons", "paypal-smart-buttons", "paypal-sdk-host"]) {
        expect(screen.getByTestId(id)).toBeInTheDocument();
      }
      expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-kind", "mile");
    });

    it("switches a v5 button that mounted before the answer, before it has loaded the v5 SDK", async () => {
      resetPayPalJsVersionForTests();
      let answer!: (flags: Record<string, unknown>) => void;
      vi.mocked(fetchFeatures).mockReturnValue(new Promise((resolve) => { answer = resolve; }) as never);
      render(<PledgeButton values={values} />);
      expect(screen.getByTestId("paypal-buttons")).not.toHaveAttribute("data-paypal-js");
      expect(loadV5).not.toHaveBeenCalled(); // v5 waits for its own features answer
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-paypal-js", "v6");
      await act(async () => {
        answer({ paypal_js_v6: true });
      });
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      expect(loadV5).not.toHaveBeenCalled();
    });

    it("shows the charged or held status after approval, not \"Approve in PayPal…\" (#215 kept)", async () => {
      const onAuthorized = vi.fn();
      render(<PledgeButton values={values} onAuthorized={onAuthorized} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await seen.v6[0].createOrder();
      });
      await act(async () => {
        await (seen.v6[0].onApprove as (data: unknown) => Promise<void>)({ orderId: "ORDER-1" });
      });
      expect(screen.getByText(i18n.t("pledge.authorized"))).toBeInTheDocument();
      expect(screen.queryByText(i18n.t("pledge.returnPending"))).toBeNull();
      expect(onAuthorized).toHaveBeenCalledWith(expect.objectContaining({ id: "PLEDGE-1" }));
      expect(hasAttempt("PLEDGE-1")).toBe(true);
    });

    it("does not tear the buttons down while its own order is being created (#192 kept)", async () => {
      let finish!: (pledge: unknown) => void;
      vi.mocked(createPledge).mockReturnValue(new Promise((resolve) => { finish = resolve; }) as never);
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      let order!: Promise<unknown>;
      act(() => {
        order = seen.v6[0].createOrder() as Promise<unknown>;
      });
      await screen.findByText(i18n.t("pledge.creating"));
      expect(seen.v6).toHaveLength(1); // busy did not re-render the buttons
      await act(async () => {
        finish({ id: "PLEDGE-1", order_id: "ORDER-1", amount_eur: "20.00" });
        await order;
      });
      expect(seen.v6).toHaveLength(1);
    });

    it("F02: an older PayPal window approved after the form changed credits the older pledge, not the new form", async () => {
      const onAuthorized = vi.fn();
      const view = render(<PledgeButton values={values} onAuthorized={onAuthorized} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      const original = seen.v6[0];
      await act(async () => {
        await original.createOrder();
      });
      view.rerender(<PledgeButton values={{ ...values, amount_eur: "50.00", target_id: "dep-ajaccio-corse", milestone_id: "dep-ajaccio-corse" }} onAuthorized={onAuthorized} />);
      await act(async () => {
        await (original.onApprove as (data: unknown) => Promise<void>)({ orderId: "ORDER-1" });
      });
      // The pledge PayPal approved is reconciled with the server…
      expect(authorizePledge).toHaveBeenCalledTimes(1);
      expect(authorizePledge).toHaveBeenCalledWith("PLEDGE-1");
      // …the edited form is not credited, and the payer is told which pledge was.
      expect(onAuthorized).not.toHaveBeenCalled();
      const receipt = screen.getByTestId("pledge-original-receipt");
      expect(receipt).toHaveTextContent("20.00 EUR");
      expect(receipt).toHaveTextContent("La Rochelle — Sponsored miles");
      expect(receipt).toHaveTextContent("PLEDGE-1");
      expect(receipt).not.toHaveTextContent("50.00");
      expect(screen.queryByText(i18n.t("pledge.authorized"))).toBeNull();
    });

    it("F02: an approval whose order id is not the one this window created is refused", async () => {
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await seen.v6[0].createOrder();
      });
      await expect((seen.v6[0].onApprove as (data: unknown) => Promise<void>)({ orderId: "SOMEONE-ELSES-ORDER" })).rejects.toThrow(/correlated/);
      expect(authorizePledge).not.toHaveBeenCalled();
    });

    it("F01: a redirect return is reconciled once, shared by the PayPal session and the App handler", async () => {
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await seen.v6[0].createOrder();
      });
      // The page comes back from PayPal: the App return handler and the resumed session both reconcile.
      let fromSession!: Promise<unknown>;
      let fromApp!: Promise<unknown>;
      await act(async () => {
        fromApp = reconcileAttempt("PLEDGE-1");
        fromSession = (seen.v6[0].onApprove as (data: unknown) => Promise<void>)({ orderId: "ORDER-1" });
        await Promise.all([fromApp, fromSession]);
      });
      expect(authorizePledge).toHaveBeenCalledTimes(1);
    });

    it("F01: after a full page reload, a resumed approval is matched to its stored attempt", async () => {
      // First page load: the order is created, then the browser leaves for PayPal.
      const first = render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await act(async () => {
        await seen.v6[0].createOrder();
      });
      first.unmount();
      // Second page load: a new component, no memory of the first one except session storage.
      const onAuthorized = vi.fn();
      render(<PledgeButton values={values} onAuthorized={onAuthorized} />);
      await waitFor(() => expect(seen.v6).toHaveLength(2));
      await act(async () => {
        await (seen.v6[1].onApprove as (data: unknown) => Promise<void>)({ orderId: "ORDER-1" });
      });
      expect(authorizePledge).toHaveBeenCalledWith("PLEDGE-1");
      expect(createPledge).toHaveBeenCalledTimes(1);
    });

    it("F01: a return that matches no attempt of this page is refused, nothing is authorised", async () => {
      render(<PledgeButton values={values} />);
      await waitFor(() => expect(seen.v6).toHaveLength(1));
      await expect((seen.v6[0].onApprove as (data: unknown) => Promise<void>)({ orderId: "FORGED" })).rejects.toThrow(/correlated/);
      expect(authorizePledge).not.toHaveBeenCalled();
      expect(registerVault).not.toHaveBeenCalled();
    });
  });
});
