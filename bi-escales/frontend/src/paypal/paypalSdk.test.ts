import { describe, expect, it } from "vitest";
import {
  loadPayPalSdk,
  loadPayPalSubscriptionSdk,
  paypalLocale,
  paypalSdkUrl,
  paypalSubscriptionSdkUrl,
} from "./paypalSdk";

describe("paypalSdkUrl", () => {
  it("loads authorize EUR vault SDK and disables Venmo", () => {
    const url = paypalSdkUrl("test-client-id");
    expect(url).toContain("client-id=test-client-id");
    expect(url).toContain("intent=authorize");
    expect(url).toContain("currency=EUR");
    expect(url).toContain("vault=true");
    expect(url).toContain("disable-funding=venmo");
    expect(url).toContain("enable-funding=paylater");
    expect(url).toContain("locale=fr_FR");
  });

  it("maps English app language to en_US locale", () => {
    const url = paypalSdkUrl("test-client-id", "en");
    expect(url).toContain("locale=en_US");
  });
});

describe("paypalLocale", () => {
  it("defaults to French PayPal locale", () => {
    expect(paypalLocale()).toBe("fr_FR");
    expect(paypalLocale("fr-FR")).toBe("fr_FR");
  });

  it("maps English tags to en_US", () => {
    expect(paypalLocale("en")).toBe("en_US");
    expect(paypalLocale("en-GB")).toBe("en_US");
  });
});

describe("payLaterEligible", () => {
  it("requires at least 30 EUR for messaging", async () => {
    const { payLaterEligible } = await import("./paypalSdk");
    expect(payLaterEligible("29.99")).toBe(false);
    expect(payLaterEligible("30.00")).toBe(true);
    expect(payLaterEligible("80,00")).toBe(true);
  });

  it("only applies to project pledges at the minimum", async () => {
    const { payLaterEligible } = await import("./paypalSdk");
    expect(payLaterEligible("40.00", "project_pledge")).toBe(true);
    expect(payLaterEligible("40.00", "mile")).toBe(false);
    expect(payLaterEligible("40.00", "night")).toBe(false);
  });
});

describe("loadPayPalSubscriptionSdk", () => {
  it("resolves when the subscription script tag is already loaded", async () => {
    const src = paypalSubscriptionSdkUrl("client-sub", "fr");
    const script = document.createElement("script");
    script.src = src;
    script.dataset.paypalSdkSrc = src;
    script.dataset.loaded = "1";
    document.body.appendChild(script);
    await expect(loadPayPalSubscriptionSdk("client-sub", "fr")).resolves.toBeUndefined();
    script.remove();
  });

  it("uses locale in subscription SDK URL", () => {
    expect(paypalSubscriptionSdkUrl("cid", "en")).toContain("locale=en_US");
  });
});

describe("loadPayPalSdk locale cache", () => {
  it("uses different script URLs per locale", () => {
    expect(paypalSdkUrl("locale-client", "fr")).toContain("locale=fr_FR");
    expect(paypalSdkUrl("locale-client", "en")).toContain("locale=en_US");
  });
});
