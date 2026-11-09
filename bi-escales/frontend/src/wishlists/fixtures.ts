import type { Channel3CatalogItem, PublicWishlist, TreasurerWishlistDoc } from "../api/types";

/** Test-only catalogue rows — ids are fictional, not the live seed. */
export function mockCatalogItem(overrides: Partial<Channel3CatalogItem> & Pick<Channel3CatalogItem, "channel3_product_id" | "project_id" | "name">): Channel3CatalogItem {
  return {
    category: "accastillage",
    catalog_optional: false,
    core_catalogue: true,
    quantity_needed: 2,
    merchant: "Mock Marine",
    merchant_country: "FR",
    image_url: "https://example.test/gear.png",
    price_amount_minor: 2500,
    price_currency: "EUR",
    price_display: "25.00",
    target_amount_minor: 5000,
    target_currency: "EUR",
    target_display: "50.00",
    funded_amount_minor: 2000,
    funded_currency: "EUR",
    funded_display: "20.00",
    funded_pct: 40,
    fully_funded: false,
    eur_funding_supported: true,
    indicative_target_eur: null,
    fx_source: null,
    fx_date: null,
    ...overrides,
  };
}

export const fixtureCatalogEur = mockCatalogItem({
  channel3_product_id: "mock-prod-eur-01",
  project_id: "gear-c3-mock-eur-01",
  name: "Mock EUR block",
  eur_funding_supported: true,
  funded_pct: 55,
});

export const fixtureCatalogUsd = mockCatalogItem({
  channel3_product_id: "mock-prod-usd-01",
  project_id: "gear-c3-mock-usd-01",
  name: "Mock USD line",
  price_currency: "USD",
  price_display: "19.99",
  target_currency: "USD",
  funded_pct: null,
  eur_funding_supported: false,
});

export const fixtureCatalogFunded = mockCatalogItem({
  channel3_product_id: "mock-prod-funded-01",
  project_id: "gear-c3-mock-funded-01",
  name: "Mock funded item",
  funded_pct: 100,
  fully_funded: true,
  channel3_buy_url: "https://example.test/channel3-buy",
  channel3_buy_disclosure:
    "If you follow this Channel3 link and complete a purchase, the association may receive a referral commission.",
});

export function buildPublicWishlist(itemCount: number): PublicWishlist {
  const items: Channel3CatalogItem[] = [];
  for (let i = 0; i < itemCount; i += 1) {
    items.push(
      mockCatalogItem({
        channel3_product_id: `mock-list-item-${i}`,
        project_id: `gear-c3-mock-list-${i}`,
        name: `List item ${i}`,
        quantity: (i % 5) + 1,
        price_currency: i % 3 === 0 ? "USD" : "EUR",
        target_currency: i % 3 === 0 ? "USD" : "EUR",
        target_amount_minor: (i + 1) * 1000,
        funded_pct: (i * 11) % 100,
      }),
    );
  }
  return {
    wishlist_id: "mock-wishlist-01",
    slug: "mock-deck",
    title: "Mock published list",
    published: true,
    items,
  };
}

export const fixtureTreasurerWishlist: TreasurerWishlistDoc = {
  _id: "mock-wid-01",
  title: "Treasurer draft",
  slug: "treasurer-mock",
  published: false,
  items: [
    { channel3_product_id: fixtureCatalogEur.channel3_product_id, quantity: 3 },
    { channel3_product_id: "mock-orphan-missing", quantity: 1 },
  ],
};
