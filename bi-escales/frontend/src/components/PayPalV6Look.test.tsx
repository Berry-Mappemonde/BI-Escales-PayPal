/**
 * Flag on (features.paypal_js_v6): the v6 buttons, drawn by the real v6 adapter over
 * a stand-in SDK, look like today's v5 ones. The Crew button is the quiet #210 button
 * and follows the theme switch; the stop sheet's pay button is full width.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { loadPayPalSdk as loadV5, loadPayPalSubscriptionSdk as loadV5Subscription } from "../paypal/paypalSdk";
import { buildV6Adapter, loadPayPalSdk as loadV6, loadPayPalSubscriptionSdk as loadV6Subscription } from "../paypal/v6/paypalSdkV6";
import { notePayPalJsFeatures, resetPayPalJsVersionForTests } from "../paypal/paypalJsVersion";
import { CrewSubscribeButton } from "./CrewSubscribeButton";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  authorizePledge: vi.fn(),
  registerVault: vi.fn(),
  fetchFeatures: vi.fn(async () => ({})),
  fetchPledgeMode: vi.fn(async () => ({ payment_mode: "AUTHORIZE" })),
  fetchSchedule: vi.fn(async () => ({})),
  fetchCrewSupporterPlan: vi.fn(),
  approveCrewSubscription: vi.fn(),
  recordSubscription: vi.fn(),
  isVaultPledge: (pledge: { payment_mode?: string }) => pledge?.payment_mode === "VAULT",
}));
vi.mock("../paypal/paypalSdk", async (load) => ({
  ...(await load<object>()),
  loadPayPalSdk: vi.fn(),
  loadPayPalSubscriptionSdk: vi.fn(),
}));
vi.mock("../paypal/v6/paypalSdkV6", async (load) => ({
  ...(await load<object>()),
  loadPayPalSdk: vi.fn(),
  loadPayPalSubscriptionSdk: vi.fn(),
}));

const session = () => ({ start: vi.fn(), destroy: vi.fn(), hasReturned: () => false, resume: vi.fn() });
const standInSdk = {
  createPayPalOneTimePaymentSession: () => session(),
  createPayPalSavePaymentSession: () => session(),
  createPayPalSubscriptionPaymentSession: () => session(),
  createPayLaterOneTimePaymentSession: () => session(),
};
const eligible = { isEligible: (method: string) => method === "paypal" };
const realAdapter = async () => buildV6Adapter(standInSdk as never, eligible as never) as never;

const values = { amount_eur: "20.00", milestone_id: "dep-la-rochelle", kind: "mile", target_id: "dep-la-rochelle", description: "La Rochelle — Sponsored miles" };

function setTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
}

describe("v6 buttons look like the v5 ones (flag on)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    resetPayPalJsVersionForTests();
    setTheme("dark");
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-public-client");
    vi.mocked(loadV6).mockImplementation(realAdapter);
    vi.mocked(loadV6Subscription).mockImplementation(realAdapter);
    notePayPalJsFeatures({ paypal_js_v6: true });
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    resetPayPalJsVersionForTests();
    delete document.documentElement.dataset.theme;
  });

  const crewButton = () => screen.getByTestId("crew-subscribe-host").querySelector("paypal-button") as HTMLElement | null;

  it("Crew: the quiet button, 32 px tall and black on the dark theme", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(crewButton()).not.toBeNull());
    const button = crewButton()!;
    expect(screen.getByTestId("crew-subscribe")).toHaveAttribute("data-paypal-js", "v6");
    expect(button.getAttribute("type")).toBe("subscribe");
    expect(button).toHaveClass("paypal-black");
    expect(button).not.toHaveClass("paypal-gold");
    expect(button.style.height).toBe("32px");
    expect(button.style.width).toBe("100%");
    // One element: no second, vertical or tagline row in v6.
    expect(screen.getByTestId("crew-subscribe-host").children).toHaveLength(1);
    expect(loadV5Subscription).not.toHaveBeenCalled();
  });

  it("Crew: white (v6's stand-in for silver) on the light theme", async () => {
    setTheme("light");
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(crewButton()).not.toBeNull());
    expect(crewButton()).toHaveClass("paypal-white");
    expect(crewButton()!.style.height).toBe("32px");
  });

  it("Crew: follows the theme switch without a reload", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <CrewSubscribeButton planId="PLAN" />
      </I18nextProvider>,
    );
    await waitFor(() => expect(crewButton()).toHaveClass("paypal-black"));
    const first = crewButton();

    await act(async () => setTheme("light"));
    await waitFor(() => expect(crewButton()).toHaveClass("paypal-white"));
    expect(crewButton()).not.toBe(first); // redrawn, like the v5 button
    expect(crewButton()!.style.height).toBe("32px");
    expect(screen.getByTestId("crew-subscribe-host").children).toHaveLength(1);

    await act(async () => setTheme("dark"));
    await waitFor(() => expect(crewButton()).toHaveClass("paypal-black"));
  });

  it("Stop sheet: \"Pay with PayPal\" is gold and takes the full width, at PayPal's own height", async () => {
    render(<PledgeButton values={values} />);
    const host = await screen.findByTestId("paypal-smart-buttons");
    await waitFor(() => expect(host.querySelector("paypal-button")).not.toBeNull());
    const button = host.querySelector("paypal-button") as HTMLElement;
    expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-paypal-js", "v6");
    expect(button.getAttribute("type")).toBe("pay");
    expect(button).toHaveClass("paypal-gold");
    expect(button.style.width).toBe("100%");
    expect(button.style.display).toBe("block");
    expect(button.style.height).toBe("");
    expect(loadV5).not.toHaveBeenCalled();
  });

  it("Stop sheet: the pay button stays gold on the light theme, as in v5", async () => {
    setTheme("light");
    render(<PledgeButton values={values} />);
    const host = await screen.findByTestId("paypal-smart-buttons");
    await waitFor(() => expect(host.querySelector("paypal-button")).not.toBeNull());
    expect(host.querySelector("paypal-button")).toHaveClass("paypal-gold");
  });
});
