import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import i18n from "../i18n";
import ExpeditionCartPanel from "./ExpeditionCartPanel";

describe("ExpeditionCartPanel", () => {
  it("shows simulated label next to marina berth prices (FR)", async () => {
    vi.spyOn(escalesApi, "fetchExpeditionCart").mockResolvedValue({
      gear_count: 0,
      marina_count: 1,
      lines: [
        {
          kind: "marina",
          id: "m1",
          description: "Marina B",
          amount_eur: "30.00",
          currency: "EUR",
          simulated: true,
          price_label: "prix simulé",
        },
      ],
    });
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ExpeditionCartPanel />
      </I18nextProvider>,
    );
    const price = await screen.findByTestId("expedition-cart-price");
    expect(price.textContent).toMatch(/30\.00 EUR/);
    expect(price.textContent).toMatch(/prix simulé/);
  });

  it("shows simulated label next to marina berth prices (EN)", async () => {
    vi.spyOn(escalesApi, "fetchExpeditionCart").mockResolvedValue({
      gear_count: 0,
      marina_count: 1,
      lines: [
        {
          kind: "marina",
          id: "m1",
          description: "Marina B",
          amount_eur: "30.00",
          currency: "EUR",
          simulated: true,
          price_label: "simulated price",
        },
      ],
    });
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ExpeditionCartPanel />
      </I18nextProvider>,
    );
    const price = await screen.findByTestId("expedition-cart-price");
    expect(price.textContent).toMatch(/30\.00 EUR/);
    expect(price.textContent).toMatch(/simulated price/i);
  });

  it("shows cart.priceUnavailable when the API row has no amount", async () => {
    vi.spyOn(escalesApi, "fetchExpeditionCart").mockResolvedValue({
      gear_count: 1,
      marina_count: 0,
      lines: [
        { kind: "gear", id: "g-missing", description: "Gear missing price", amount_eur: null, currency: "EUR" },
      ],
    });
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ExpeditionCartPanel />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("expedition-cart-price")).toHaveTextContent("prix indisponible");
    await i18n.changeLanguage("en");
    await waitFor(() => {
      expect(screen.getByTestId("expedition-cart-price")).toHaveTextContent("price unavailable");
    });
  });
});
