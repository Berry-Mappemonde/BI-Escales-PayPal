/**
 * App wiring of features.paypal_js_v6: the page's own features request decides which
 * PayPal SDK its buttons load, and a PayPal return is reconciled through the path
 * that started the checkout.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import { authorizePledge, fetchFeatures, registerVault } from "./api/escales";
import { loadPayPalSubscriptionSdk as loadV5 } from "./paypal/paypalSdk";
import { loadPayPalSubscriptionSdk as loadV6 } from "./paypal/v6/paypalSdkV6";
import { expectPayPalJsFeatures, resetPayPalJsVersionForTests } from "./paypal/paypalJsVersion";
import { rememberAttempt } from "./paypal/v6/checkoutAttempts";

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue(undefined),
    fetchFeatures: vi.fn(),
    fetchSchedule: vi.fn().mockResolvedValue({ milestones: [] }),
    fetchFund: vi.fn(),
    fetchPublicCommonFund: vi.fn().mockResolvedValue(null),
    fetchPrices: vi.fn().mockResolvedValue({}),
    fetchClock: vi.fn().mockResolvedValue({}),
    fetchGearProjects: vi.fn().mockResolvedValue({ features: [] }),
    listMilestones: vi.fn().mockResolvedValue([]),
    fetchCrewSupporterPlan: vi.fn().mockResolvedValue({ plan_id: "PLAN-TEST" }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    recordSpending: vi.fn(),
    settleClock: vi.fn(),
    approveCrewSubscription: vi.fn(),
  };
});
vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));
vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => null }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/escales/EscalesScheduler.jsx", () => ({ default: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/TreasurerQueue", () => ({ TreasurerQueue: () => null }));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));
vi.mock("./paypal/paypalSdk", async (load) => ({ ...(await load<object>()), loadPayPalSubscriptionSdk: vi.fn() }));
vi.mock("./paypal/v6/paypalSdkV6", async (load) => ({ ...(await load<object>()), loadPayPalSubscriptionSdk: vi.fn() }));

import App from "./App";

const sdk = () => ({ Buttons: () => ({ render: async () => {}, close: async () => {} }) });

/** As in main.tsx: the page announces its features request before it renders. */
function start() {
  expectPayPalJsFeatures();
  return render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );
}

describe("App and features.paypal_js_v6", () => {
  const realLocation = window.location;
  beforeEach(async () => {
    vi.clearAllMocks();
    sessionStorage.clear();
    resetPayPalJsVersionForTests();
    await i18n.changeLanguage("en");
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-public-client");
    vi.mocked(loadV5).mockImplementation(async () => sdk() as never);
    vi.mocked(loadV6).mockImplementation(async () => sdk() as never);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    resetPayPalJsVersionForTests();
  });

  it("flag off: the Crew button is today's v5 button, with one features request", async () => {
    vi.mocked(fetchFeatures).mockResolvedValue({ paypal_js_v6: false });
    start();
    await waitFor(() => expect(loadV5).toHaveBeenCalledTimes(1));
    expect(loadV6).not.toHaveBeenCalled();
    expect(await screen.findByTestId("crew-subscribe")).not.toHaveAttribute("data-paypal-js");
    expect(fetchFeatures).toHaveBeenCalledTimes(1);
  });

  it("flag on: the Crew button is the v6 button and the v5 SDK is never loaded", async () => {
    vi.mocked(fetchFeatures).mockResolvedValue({ paypal_js_v6: true });
    start();
    await waitFor(() => expect(loadV6).toHaveBeenCalledTimes(1));
    expect(loadV5).not.toHaveBeenCalled();
    expect(await screen.findByTestId("crew-subscribe")).toHaveAttribute("data-paypal-js", "v6");
    expect(fetchFeatures).toHaveBeenCalledTimes(1);
  });

  it("flag on, features slower than the plan lookup: no SDK is loaded while the page waits", async () => {
    let answer!: (flags: Record<string, unknown>) => void;
    vi.mocked(fetchFeatures).mockReturnValue(new Promise((resolve) => { answer = resolve; }) as never);
    start();
    // The plan is known, the flag is not: neither SDK may load yet.
    await screen.findByTestId("crew-supporter-public");
    expect(screen.queryByTestId("crew-subscribe")).toBeNull();
    expect(loadV5).not.toHaveBeenCalled();
    expect(loadV6).not.toHaveBeenCalled();
    answer({ paypal_js_v6: true });
    await waitFor(() => expect(loadV6).toHaveBeenCalledTimes(1));
    expect(loadV5).not.toHaveBeenCalled();
  });

  it("the features request fails: the Crew button is the v5 button", async () => {
    vi.mocked(fetchFeatures).mockRejectedValue(new Error("offline"));
    start();
    await waitFor(() => expect(loadV5).toHaveBeenCalledTimes(1));
    expect(loadV6).not.toHaveBeenCalled();
  });

  describe("PayPal return", () => {
    function returnFrom(search: string) {
      vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { ...realLocation, search, hash: "", pathname: realLocation.pathname, href: `${realLocation.origin}${realLocation.pathname}${search}` },
      });
    }
    const pledge = { id: "P-1", status: "authorized", intent: "AUTHORIZE", currency: "EUR", amount_eur: "20.00", description: "miles", milestone_id: "dep-mayotte" };

    it("a v5 checkout is authorised exactly as today and nothing is stored", async () => {
      vi.mocked(fetchFeatures).mockResolvedValue({});
      vi.mocked(authorizePledge).mockResolvedValue(pledge as never);
      returnFrom("?paypal=return&pledge_id=P-1");
      start();
      await waitFor(() => expect(authorizePledge).toHaveBeenCalledTimes(1));
      expect(authorizePledge).toHaveBeenCalledWith("P-1");
      expect(sessionStorage.getItem("escales-v6-attempts")).toBeNull();
    });

    it("a v6 checkout is reconciled once and marked verified", async () => {
      vi.mocked(fetchFeatures).mockResolvedValue({ paypal_js_v6: true });
      vi.mocked(authorizePledge).mockResolvedValue(pledge as never);
      rememberAttempt({ key: "attempt-1", pledgeId: "P-1", orderId: "ORDER-1", revision: 1, amount: "20.00", currency: "EUR", milestone: "dep-mayotte", target: "dep-mayotte", mode: "AUTHORIZE", path: realLocation.pathname });
      returnFrom("?paypal=return&pledge_id=P-1");
      start();
      await waitFor(() => expect(authorizePledge).toHaveBeenCalledTimes(1));
      expect(authorizePledge).toHaveBeenCalledWith("P-1");
      await waitFor(() => expect(JSON.parse(sessionStorage.getItem("escales-v6-attempts") || "[]")[0]).toMatchObject({ pledgeId: "P-1", verified: true }));
    });

    it("a v6 vault return passes the approval token to the server, once", async () => {
      vi.mocked(fetchFeatures).mockResolvedValue({ paypal_js_v6: true });
      vi.mocked(registerVault).mockResolvedValue({ ...pledge, id: "V-1", status: "vaulted", intent: "VAULT", payment_mode: "VAULT" } as never);
      rememberAttempt({ key: "attempt-v", pledgeId: "V-1", revision: 1, amount: "80.00", currency: "EUR", milestone: "leg-a-to-b", target: "leg-a-to-b", mode: "VAULT", path: realLocation.pathname });
      returnFrom("?vault=return&pledge_id=V-1&approval_token_id=TOKEN-1");
      start();
      await waitFor(() => expect(registerVault).toHaveBeenCalledTimes(1));
      expect(registerVault).toHaveBeenCalledWith("V-1", "TOKEN-1");
      expect(authorizePledge).not.toHaveBeenCalled();
    });
  });
});
