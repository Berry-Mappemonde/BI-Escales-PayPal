import { describe, expect, it } from "vitest";
import { isQueuedPledge } from "./queueFilter";

describe("isQueuedPledge", () => {
  it("includes authorized, vaulted and pending pledges", () => {
    expect(isQueuedPledge("authorized")).toBe(true);
    expect(isQueuedPledge("vaulted")).toBe(true);
    expect(isQueuedPledge("pending")).toBe(true);
    expect(isQueuedPledge("created")).toBe(false);
    expect(isQueuedPledge("captured")).toBe(false);
  });
});
