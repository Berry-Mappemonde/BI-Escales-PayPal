import { describe, expect, it } from "vitest";
import { isCaptainRateLimitMessage } from "./captainRateLimit";

describe("isCaptainRateLimitMessage", () => {
  it("detects FR and EN captain 429 bodies", () => {
    expect(isCaptainRateLimitMessage("Trop de requêtes. Le capitaine accepte 2 par minute.")).toBe(true);
    expect(isCaptainRateLimitMessage("Too many requests. The captain accepts 2 per minute.")).toBe(true);
    expect(isCaptainRateLimitMessage("PayPal error")).toBe(false);
  });
});
