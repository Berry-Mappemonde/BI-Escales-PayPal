import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import { fixtureCatalogEur, fixtureCatalogFunded, fixtureCatalogUsd } from "./fixtures";
import { WishlistItemCard } from "./WishlistItemCard";

let capturedPledgeValues: Record<string, unknown> | null = null;

vi.mock("../components/PledgeButton", () => ({
  PledgeButton: ({ values }: { values: Record<string, unknown> }) => {
    capturedPledgeValues = values;
    return <div data-testid="pledge-button" data-currency={String(values.currency || "")} />;
  },
}));

describe("WishlistItemCard", () => {
  it("renders funding bar for EUR items", () => {
    render(<WishlistItemCard item={fixtureCatalogEur} />);
    expect(screen.getByTestId("wishlist-funding-bar")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-fund-block")).toBeInTheDocument();
  });

  it("shows fund button and bar for USD without EUR-only label", () => {
    render(
      <WishlistItemCard
        item={{
          ...fixtureCatalogUsd,
          funded_pct: null,
          target_amount_minor: 9999,
          target_currency: "USD",
          target_display: "99.99",
        }}
      />,
    );
    expect(screen.queryByTestId("wishlist-no-eur-funding")).toBeNull();
    expect(screen.getByTestId("wishlist-funding-bar")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-fund-block")).toBeInTheDocument();
    expect(screen.getByTestId("pledge-button")).toHaveAttribute("data-currency", "USD");
  });

  it("shows buy link and disclosure only when fully funded", () => {
    render(<WishlistItemCard item={fixtureCatalogFunded} />);
    expect(screen.getByTestId("wishlist-buy-link")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-buy-disclosure")).toHaveTextContent(/commission/i);
  });

  it("hides buy link when not fully funded", () => {
    render(<WishlistItemCard item={fixtureCatalogEur} />);
    expect(screen.queryByTestId("wishlist-buy-link")).toBeNull();
  });

  it("shows line quantity and line target from API", () => {
    render(
      <WishlistItemCard
        item={{
          ...fixtureCatalogEur,
          quantity: 3,
          quantity_needed: 99,
          target_amount_minor: 7500,
          target_currency: "EUR",
        }}
      />,
    );
    expect(screen.getByTestId("wishlist-item-qty")).toHaveTextContent(/3/);
    expect(screen.getByTestId("wishlist-line-target")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-item-qty")).not.toHaveTextContent(/99/);
  });

  it("forwards order currency to pledge flow", () => {
    capturedPledgeValues = null;
    render(<WishlistItemCard item={{ ...fixtureCatalogUsd, price_currency: "GBP", target_currency: "GBP" }} />);
    expect(capturedPledgeValues?.currency).toBe("GBP");
  });
});
