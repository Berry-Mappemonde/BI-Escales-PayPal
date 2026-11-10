import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPledge } from "../api/escales";
import {
  createPledgeWithTimeout,
  PledgeCreateTimeoutError,
  pledgeCreateErrorMessage,
  PLEDGE_CREATE_TIMEOUT_MS,
} from "./pledgeCreate";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
}));

describe("createPledgeWithTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("rejects with PledgeCreateTimeoutError after the ceiling", async () => {
    vi.mocked(createPledge).mockImplementation(
      () => new Promise(() => {
        /* hang */
      }),
    );
    const pending = createPledgeWithTimeout(
      {
        amount_eur: "1",
        description: "x",
        milestone_id: "m",
      },
      "req-1",
      PLEDGE_CREATE_TIMEOUT_MS,
    );
    const assertion = expect(pending).rejects.toBeInstanceOf(PledgeCreateTimeoutError);
    await vi.advanceTimersByTimeAsync(PLEDGE_CREATE_TIMEOUT_MS);
    await assertion;
  });

  it("maps timeout errors to pledge.createTimeout", () => {
    const msg = pledgeCreateErrorMessage(new PledgeCreateTimeoutError(), (k) =>
      k === "pledge.createTimeout" ? "TIMEOUT_COPY" : k,
    );
    expect(msg).toBe("TIMEOUT_COPY");
  });
});
