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
});
