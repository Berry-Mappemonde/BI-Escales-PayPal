import { describe, expect, it } from "vitest";
import { fixtureCatalogEur, fixtureCatalogUsd } from "./fixtures";
import { itemPresentmentCurrency, wishlistItemFundable, wishlistPledgeBody } from "./wishlistPledge";

describe("wishlistPledge", () => {
  it("marks USD, GBP, and EUR as fundable via PayPal list", () => {
    expect(wishlistItemFundable(fixtureCatalogUsd)).toBe(true);
    expect(wishlistItemFundable({ ...fixtureCatalogEur, price_currency: "GBP" })).toBe(true);
    expect(wishlistItemFundable(fixtureCatalogEur)).toBe(true);
  });

  it("passes item currency into pledge POST body", () => {
    const body = wishlistPledgeBody(fixtureCatalogUsd, {
      amountMajor: "25.00",
      description: "Gear",
      contributor: "Pat",
      lang: "en",
    });
    expect(body.currency).toBe("USD");
    expect(body.amount_eur).toBe("25.00");
    expect(body.kind).toBe("project_pledge");
    expect(itemPresentmentCurrency(fixtureCatalogUsd)).toBe("USD");
  });

  it("respects backend funding_supported when present", () => {
    expect(wishlistItemFundable({ ...fixtureCatalogUsd, funding_supported: false })).toBe(false);
  });
});
