import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { authorizePledge, createPledge } from "../api/escales";
import { PayPalWalletPayBlockV6 } from "./PayPalWalletPayBlockV6";

vi.mock("../api/escales", () => ({ createPledge: vi.fn(), authorizePledge: vi.fn() }));

type WalletConfig = { amount: string; currencyCode: string; createOrder: () => Promise<string>; onApprove: () => Promise<void>; onError: () => void };
const values = { amount_eur: "20.00", milestone_id: "dep-la-rochelle", kind: "mile", description: "La Rochelle" };

function show(paypal: Record<string, unknown>, onAuthorized = vi.fn()) {
  return render(
    <I18nextProvider i18n={i18n}>
      <PayPalWalletPayBlockV6 values={values} appLang="en" sdkIntent="authorize" sdkReady paypal={paypal as never} onAuthorized={onAuthorized} />
    </I18nextProvider>,
  );
}

describe("Google Pay button artwork", () => {
  const read = (file: string) => readFileSync(resolve(process.cwd(), file), "utf8");

  it("draws the PayPal artwork once instead of tiling it", () => {
    const css = read("src/components/PayPalWalletPayBlockV6.css");
    const stop = read("src/components/stop/stop-panel.css");
    const shell = read("src/styles/naviguide-shell.css");
    expect(css).toMatch(/background-repeat:\s*no-repeat/);
    expect(css).toMatch(/background-size:\s*contain/);
    expect(css).toMatch(/background-position:\s*center/);
    expect(css).toMatch(/background-color:\s*#000/);
    expect(css).not.toMatch(/background-repeat:\s*repeat\b/);
    expect(css).toMatch(/\.escale-sheet \.pledge-form \.paypal-wallet-pay\[data-testid="paypal-wallet-pay"\] \[data-testid="paypal-google-pay"\] button:is\(:hover, :active, :focus, :focus-visible\)/);
    expect(css).toMatch(/\.ng-sidebar \.project-pledge \.paypal-wallet-pay\[data-testid="paypal-wallet-pay"\] \[data-testid="paypal-google-pay"\] button/);
    expect(css).not.toMatch(/\[data-testid="paypal-google-pay"\] > button/);
    const coarse = css.slice(css.indexOf("@media (pointer: coarse)"));
    expect(coarse).toMatch(/paypal-google-pay/);
    expect(coarse).toMatch(/background-repeat:\s*no-repeat/);
    expect(coarse).toMatch(/background-color:\s*#000/);
    for (const selector of [
      ".escale-sheet .pledge-form button:not([data-testid=\"paypal-google-pay\"] button)",
      ".escale-sheet .pledge-form button:active:not(:disabled):not([data-testid=\"paypal-google-pay\"] button)",
      ".escale-sheet .pledge-form button:focus-visible:not([data-testid=\"paypal-google-pay\"] button)",
      ".escale-sheet .pledge-form button:hover:not(:disabled):not([data-testid=\"paypal-google-pay\"] button)",
    ]) {
      expect(stop).toContain(selector);
    }
    expect(shell).toContain(".ng-sidebar .project-pledge button:not([data-testid=\"paypal-google-pay\"] button)");
  });
});

describe("PayPalWalletPayBlockV6", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.mocked(createPledge).mockResolvedValue({ id: "PLEDGE-1", order_id: "ORDER-1" } as never);
    vi.mocked(authorizePledge).mockResolvedValue({ id: "PLEDGE-1", status: "authorized" } as never);
  });

  it("gives each wallet the amount and currency the v6 sessions need", async () => {
    const configs: WalletConfig[] = [];
    const factory = (config: WalletConfig) => {
      configs.push(config);
      return { render: async () => {}, close: async () => {} };
    };
    show({ Googlepay: factory, Applepay: factory });
    await waitFor(() => expect(configs).toHaveLength(2));
    for (const config of configs) expect(config).toMatchObject({ amount: "20.00", currencyCode: "EUR" });
    expect(await screen.findByText(i18n.t("pledge.walletPayHint"))).toBeInTheDocument();
  });

  it("an unavailable Apple Pay does not hide Google Pay", async () => {
    const google = vi.fn(() => ({ render: async () => {}, close: async () => {} }));
    const apple = vi.fn(() => ({ render: async () => { throw new Error("Apple Pay not eligible on this device"); }, close: async () => {} }));
    show({ Googlepay: google, Applepay: apple });
    await waitFor(() => expect(screen.getByTestId("paypal-google-pay")).toHaveAttribute("data-google-pay", "1"));
    expect(screen.getByTestId("paypal-apple-pay")).not.toHaveAttribute("data-apple-pay");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("tells the payer when the wallet payment did not complete", async () => {
    let config!: WalletConfig;
    show({ Googlepay: (c: WalletConfig) => { config = c; return { render: async () => {}, close: async () => {} }; } });
    await waitFor(() => expect(config).toBeDefined());
    act(() => config.onError());
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("pledge.walletPayError"));
  });

  it("authorises the pledge its own order was created for", async () => {
    let config!: WalletConfig;
    const onAuthorized = vi.fn();
    show({ Googlepay: (c: WalletConfig) => { config = c; return { render: async () => {}, close: async () => {} }; } }, onAuthorized);
    await waitFor(() => expect(config).toBeDefined());
    expect(await config.createOrder()).toBe("ORDER-1");
    await config.onApprove();
    expect(authorizePledge).toHaveBeenCalledWith("PLEDGE-1");
    expect(onAuthorized).toHaveBeenCalledWith(expect.objectContaining({ id: "PLEDGE-1" }));
  });

  it("renders nothing to tap when the SDK offers no wallet", () => {
    show({});
    expect(screen.getByTestId("paypal-google-pay")).toBeEmptyDOMElement();
    expect(screen.getByTestId("paypal-apple-pay")).toBeEmptyDOMElement();
  });
});

it("reuses the request id after an uncertain wallet order creation", async () => {
  vi.clearAllMocks();
  vi.mocked(createPledge).mockRejectedValueOnce(new Error("timeout"));
  vi.mocked(createPledge).mockResolvedValueOnce({ id: "RETRY", order_id: "ORDER-RETRY" } as never);
  let config!: WalletConfig;
  show({ Googlepay: (c: WalletConfig) => { config = c; return { render: async () => {}, close: async () => {} }; } });
  await waitFor(() => expect(config).toBeDefined());
  await expect(config.createOrder()).rejects.toThrow("timeout");
  expect(await config.createOrder()).toBe("ORDER-RETRY");
  expect(vi.mocked(createPledge).mock.calls[0][1]).toBe(vi.mocked(createPledge).mock.calls[1][1]);
});

it("passes the donation currency to the native wallet sheet", async () => {
  let config!: WalletConfig;
  render(<PayPalWalletPayBlockV6 values={{ ...values, kind: "project_pledge", currency: "USD" }}
    appLang="en" sdkIntent="capture" sdkReady paypal={{ Googlepay: (c: WalletConfig) => {
      config = c; return { render: async () => {}, close: async () => {} };
    } } as never} />);
  await waitFor(() => expect(config).toBeDefined());
  expect(config.currencyCode).toBe("USD");
});
