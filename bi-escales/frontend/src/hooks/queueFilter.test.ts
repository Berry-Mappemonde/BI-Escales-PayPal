import { describe, expect, it } from "vitest";
import { canCapturePledge, canVoidPledge, isQueuedPledge } from "./queueFilter";

describe("isQueuedPledge", () => {
  it("shows every PayPal status the treasurer should see", () => {
    for (const status of ["created", "authorized", "vaulted", "pending", "captured", "settled", "failed", "voided", "refunded"]) {
      expect(isQueuedPledge(status)).toBe(true);
    }
  });
});

describe("actions", () => {
  it("voids a pending pledge and captures only a hold", () => {
    expect(canVoidPledge("pending")).toBe(true);
    expect(canCapturePledge("pending")).toBe(false);
    expect(canCapturePledge("authorized")).toBe(true);
    expect(canCapturePledge("vaulted")).toBe(true);
  });
});
