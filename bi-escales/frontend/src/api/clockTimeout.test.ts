import { afterEach, describe, expect, it, vi } from "vitest";
import { CLOCK_TIMEOUT_MS, fetchClock } from "./escales";

/** A host that never answers, until the request is aborted. */
function sleepingHost() {
  return vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    });
  });
}

describe("fetchClock", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("gives up on a host that does not answer, instead of waiting for it to wake", async () => {
    const fetchMock = sleepingHost();
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchClock(20)).rejects.toThrow("Clock request timed out after 20 ms");
    expect(fetchMock.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("returns the clock when the host answers in time", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" }))),
    );
    await expect(fetchClock()).resolves.toEqual({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" });
  });

  it("waits well under a minute by default", () => {
    expect(CLOCK_TIMEOUT_MS).toBeGreaterThan(0);
    expect(CLOCK_TIMEOUT_MS).toBeLessThanOrEqual(15000);
  });
});
