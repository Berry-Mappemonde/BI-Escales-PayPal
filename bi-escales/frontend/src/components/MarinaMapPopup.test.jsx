import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { MarinaMapPopup } from "./MarinaMapPopup.jsx";

describe("MarinaMapPopup", () => {
  it("shows PayPal berth reservation block", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <MarinaMapPopup
          properties={{ name: "Test Marina", maps_url: "https://example.com/maps" }}
          milestoneId="dep-test"
          onAuthorized={() => {}}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("marina-map-reserve")).toHaveAttribute("data-kind", "berth");
    expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-kind", "berth");
    expect(screen.getByText(/30\.00 EUR/)).toBeInTheDocument();
  });
});
