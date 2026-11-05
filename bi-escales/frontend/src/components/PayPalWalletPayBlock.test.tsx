import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { PayPalWalletPayBlock } from "./PayPalWalletPayBlock";

const values = { amount_eur: "5.00", description: "5 milles", milestone_id: "dep-mayotte" };

describe("PayPalWalletPayBlock", () => {
  afterEach(() => {
    delete window.paypal;
    vi.restoreAllMocks();
  });

  it("affiche les hôtes Google Pay et Apple Pay", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <PayPalWalletPayBlock values={values} appLang="fr" sdkIntent="authorize" sdkReady />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("paypal-wallet-pay")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-google-pay")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-apple-pay")).toBeInTheDocument();
  });

  it("n'appelle pas Googlepay/Applepay tant que le SDK n'est pas prêt", () => {
    const googlepay = vi.fn(() => ({ render: vi.fn(async () => undefined) }));
    const applepay = vi.fn(() => ({ render: vi.fn(async () => undefined) }));
    window.paypal = { Googlepay: googlepay as never, Applepay: applepay as never };

    render(
      <I18nextProvider i18n={i18n}>
        <PayPalWalletPayBlock values={values} appLang="fr" sdkIntent="authorize" sdkReady={false} />
      </I18nextProvider>,
    );

    expect(googlepay).not.toHaveBeenCalled();
    expect(applepay).not.toHaveBeenCalled();
  });

  it("rend Google Pay et Apple Pay une fois sdkReady", async () => {
    const googleRender = vi.fn(async () => undefined);
    const appleRender = vi.fn(async () => undefined);
    const googlepay = vi.fn(() => ({ render: googleRender }));
    const applepay = vi.fn(() => ({ render: appleRender }));
    window.paypal = { Googlepay: googlepay as never, Applepay: applepay as never };

    render(
      <I18nextProvider i18n={i18n}>
        <PayPalWalletPayBlock values={values} appLang="fr" sdkIntent="authorize" sdkReady />
      </I18nextProvider>,
    );

    expect(googlepay).toHaveBeenCalled();
    expect(applepay).toHaveBeenCalled();
    await vi.waitFor(() => {
      expect(googleRender).toHaveBeenCalled();
      expect(appleRender).toHaveBeenCalled();
    });
  });
});
