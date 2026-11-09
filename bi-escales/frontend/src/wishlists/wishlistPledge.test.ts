import { describe, expect, it } from "vitest";
import { fixtureCatalogEur, fixtureCatalogJpy, fixtureCatalogUnsupported, fixtureCatalogUsd } from "./fixtures";
import { itemPresentmentCurrency, wishlistItemFundable, wishlistPledgeBody } from "./wishlistPledge";

describe("wishlistPledge", () => {
  it("uses paypal_currency_supported from API", () => {
    expect(wishlistItemFundable(fixtureCatalogUsd)).toBe(true);
    expect(wishlistItemFundable(fixtureCatalogEur)).toBe(true);
    expect(wishlistItemFundable(fixtureCatalogJpy)).toBe(true);
    expect(wishlistItemFundable(fixtureCatalogUnsupported)).toBe(false);
  });

  it("builds pledge body with native amount_eur and SDK currency", () => {
    const body = wishlistPledgeBody(fixtureCatalogUsd, {
      amountMajor: "25.00",
      description: "Gear",
      contributor: "Pat",
      lang: "en",
    });
    expect(body.currency).toBe("USD");
    expect(body.amount_eur).toBe("25.00");
    expect(body.kind).toBe("project_pledge");
    expect("currency" in body).toBe(true);
    expect(itemPresentmentCurrency(fixtureCatalogUsd)).toBe("USD");
  });
});
