import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";

const values = {
  amount_eur: "5.00",
  description: "5 milles",
  milestone_id: "dep-mayotte",
  kind: "mile",
};

describe("PayPalCardFieldsBlock", () => {
  it("affiche le bloc sans SDK CardFields", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <PayPalCardFieldsBlock values={values} appLang="fr" />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("paypal-card-fields")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-card-submit")).toBeDisabled();
  });
});
