import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { PayPalWalletPayBlock } from "./PayPalWalletPayBlock";

describe("PayPalWalletPayBlock", () => {
  it("affiche les hôtes Google Pay et Apple Pay", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <PayPalWalletPayBlock
          values={{ amount_eur: "5.00", description: "5 milles", milestone_id: "dep-mayotte" }}
          appLang="fr"
          sdkIntent="authorize"
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("paypal-wallet-pay")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-google-pay")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-apple-pay")).toBeInTheDocument();
  });
});
