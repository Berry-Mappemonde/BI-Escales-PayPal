import { describe, expect, it } from "vitest";
import { paypalSdkUrl } from "./paypalSdk";

describe("paypalSdkUrl", () => {
  it("loads authorize EUR vault SDK and disables Venmo", () => {
    const url = paypalSdkUrl("test-client-id");
    expect(url).toContain("client-id=test-client-id");
    expect(url).toContain("intent=authorize");
    expect(url).toContain("currency=EUR");
    expect(url).toContain("vault=true");
    expect(url).toContain("disable-funding=venmo");
    expect(url).toContain("enable-funding=paylater");
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
    const { paypalSubscriptionSdkUrl, loadPayPalSubscriptionSdk } = await import("./paypalSdk");
    const src = paypalSubscriptionSdkUrl("client-sub");
    const script = document.createElement("script");
    script.src = src;
    script.dataset.paypalSdkSrc = src;
    script.dataset.loaded = "1";
    document.body.appendChild(script);
    await expect(loadPayPalSubscriptionSdk("client-sub")).resolves.toBeUndefined();
    script.remove();
  });
});
