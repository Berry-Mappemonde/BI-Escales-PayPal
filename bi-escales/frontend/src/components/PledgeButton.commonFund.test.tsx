import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { PledgeButton } from "./PledgeButton";
import { loadPayPalSdk as v5 } from "../paypal/paypalSdk";
import { loadPayPalSdk as v6 } from "../paypal/v6/paypalSdkV6";
import { notePayPalJsFeatures, resetPayPalJsVersionForTests } from "../paypal/paypalJsVersion";

vi.mock("../api/escales", () => ({
  fetchFeatures: vi.fn(async () => ({ card_fields: true, wallet_pay: true })),
  fetchPledgeMode: vi.fn(async () => ({ payment_mode: "CAPTURE" })),
  fetchSchedule: vi.fn(async () => ({})),
  isVaultPledge: () => false,
}));
vi.mock("../paypal/paypalSdk", async load => ({ ...(await load<object>()), loadPayPalSdk: vi.fn() }));
vi.mock("../paypal/v6/paypalSdkV6", async load => ({ ...(await load<object>()), loadPayPalSdk: vi.fn() }));
vi.mock("./PayPalCardFieldsBlock", () => ({ PayPalCardFieldsBlock: () => <div data-testid="common-card" /> }));
vi.mock("./PayPalWalletPayBlock", () => ({ PayPalWalletPayBlock: () => <div data-testid="common-wallets" /> }));
vi.mock("./PayPalWalletPayBlockV6", () => ({ PayPalWalletPayBlockV6: () => <div data-testid="common-wallets" /> }));

beforeEach(() => {
  vi.clearAllMocks(); resetPayPalJsVersionForTests();
  vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "sandbox-test");
  const sdk = { Buttons: () => ({ render: async () => {}, close: async () => {} }) };
  vi.mocked(v5).mockResolvedValue(sdk as never); vi.mocked(v6).mockResolvedValue(sdk as never);
});
afterEach(() => { vi.unstubAllEnvs(); resetPayPalJsVersionForTests(); });

it.each([[false, "en"], [true, "en"], [false, "fr"], [true, "fr"]] as const)(
  "preserves common-fund cards and wallets with dedicated %s/%s copy", async (on, lang) => {
    await i18n.changeLanguage(lang);
    notePayPalJsFeatures({ paypal_js_v6: on });
    render(<PledgeButton values={{ amount_eur: "10.00", kind: "common_fund", milestone_id: "", description: "Common fund" }} />);
    expect(await screen.findByTestId("common-card")).toBeInTheDocument();
    expect(await screen.findByTestId("common-wallets")).toBeInTheDocument();
    expect(screen.getByText(lang === "en" ? /Common fund donation/ : /Don au fonds commun/)).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("pledge.intentProject"))).toBeNull();
    const loader = on ? v6 : v5;
    await waitFor(() => expect(loader).toHaveBeenCalled());
    expect(vi.mocked(loader).mock.calls[0][2]).toBe("capture");
  },
);
