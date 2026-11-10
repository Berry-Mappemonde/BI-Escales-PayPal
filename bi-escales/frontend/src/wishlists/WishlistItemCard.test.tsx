import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import {
  fixtureCatalogEur,
  fixtureCatalogFunded,
  fixtureCatalogJpy,
  fixtureCatalogUnsupported,
  fixtureCatalogUsd,
} from "./fixtures";
import type { PledgeFormValues } from "../components/PledgeButton";
import { WishlistItemCard } from "./WishlistItemCard";

let capturedPledgeValues: PledgeFormValues | null = null;

vi.mock("../components/PledgeButton", () => ({
  PledgeButton: ({ values }: { values: PledgeFormValues }) => {
    capturedPledgeValues = values;
    return <div data-testid="pledge-button" data-currency={String(values.currency || "")} />;
  },
}));

describe("WishlistItemCard", () => {
  beforeEach(() => {
    capturedPledgeValues = null;
  });

  it("shows the item's picture as a fixed-size, lazy thumbnail named after the item", () => {
    render(<WishlistItemCard item={fixtureCatalogEur} />);
    const photo = screen.getByTestId("wishlist-item-image");
    expect(photo).toHaveAttribute("src", fixtureCatalogEur.image_url);
    expect(photo).toHaveAttribute("alt", fixtureCatalogEur.name);
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(photo).toHaveAttribute("width", "64");
    expect(photo).toHaveAttribute("height", "64");
  });

  it.each([null, "", undefined])("shows no picture when image_url is %j", (image_url) => {
    render(<WishlistItemCard item={{ ...fixtureCatalogEur, image_url }} />);
    expect(screen.getByTestId("wishlist-item-name")).toBeInTheDocument();
    expect(screen.queryByTestId("wishlist-item-image")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("renders funding bar when funded_pct is set", () => {
    render(<WishlistItemCard item={fixtureCatalogEur} />);
    expect(screen.getByTestId("wishlist-funding-bar")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-fund-block")).toBeInTheDocument();
  });

  it("shows fund button for USD and forwards SDK currency", () => {
    render(<WishlistItemCard item={fixtureCatalogUsd} />);
    expect(screen.getByTestId("wishlist-funding-bar")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-fund-block")).toBeInTheDocument();
    expect(screen.getByTestId("pledge-button")).toHaveAttribute("data-currency", "USD");
  });

  it("hides fund button when paypal_currency_supported is false", () => {
    render(<WishlistItemCard item={fixtureCatalogUnsupported} />);
    expect(screen.queryByTestId("wishlist-fund-block")).toBeNull();
  });

  it("formats JPY unit amounts as whole units", () => {
    render(<WishlistItemCard item={fixtureCatalogJpy} />);
    expect(screen.getByTestId("wishlist-item-price")).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-fund-block")).toBeInTheDocument();
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

  it("hides buy link when funded_pct is 99 but fully_funded is false (exact minor units)", () => {
    render(
      <WishlistItemCard
        item={{
          ...fixtureCatalogEur,
          funded_pct: 99,
          fully_funded: false,
          channel3_buy_url: "https://example.test/should-not-show",
          channel3_buy_disclosure: "Disclosure",
        }}
      />,
    );
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

  it("forwards order currency to pledge SDK props only", () => {
    render(<WishlistItemCard item={{ ...fixtureCatalogUsd, target_currency: "USD" }} />);
    expect(capturedPledgeValues?.currency).toBe("USD");
    expect(capturedPledgeValues?.amount_eur).toBe("1.00");
  });
});
