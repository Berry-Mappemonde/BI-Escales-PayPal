import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import i18n from "../i18n";
import ExpeditionCartPanel from "./ExpeditionCartPanel";

describe("ExpeditionCartPanel", () => {
  it("shows a price or label on every cart row", async () => {
    vi.spyOn(escalesApi, "fetchExpeditionCart").mockResolvedValue({
      gear_count: 1,
      marina_count: 1,
      lines: [
        { kind: "gear", id: "g1", description: "Gear A", amount_eur: "10.00", currency: "EUR" },
        { kind: "marina", id: "m1", description: "Marina B", price_label: "prix indisponible" },
      ],
    });
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ExpeditionCartPanel />
      </I18nextProvider>,
    );
    const prices = await screen.findAllByTestId("expedition-cart-price");
    expect(prices).toHaveLength(2);
    expect(prices[0].textContent).toMatch(/10\.00 EUR/);
    expect(prices[1].textContent).toMatch(/prix indisponible/);
    await waitFor(() => {
      expect(screen.getByTestId("expedition-cart-table")).toBeInTheDocument();
    });
  });
});
