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
  });
});
