import { describe, expect, it, vi } from "vitest";
import { fetchHealthRetrying, healthBanner } from "./escales";

describe("healthBanner", () => {
  it("keeps the failure hidden while the cold start is still retrying", () => {
    expect(healthBanner(null)).toBe("wait");
    expect(healthBanner(true)).toBe("ok");
    expect(healthBanner(false)).toBe("down");
  });
});

describe("fetchHealthRetrying", () => {
  it("waits and tries again before giving up", async () => {
    const attempt = vi.fn()
      .mockRejectedValueOnce(new Error("HTTP 502"))
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce({ status: "ok" });
    const sleep = vi.fn(async () => {});
    const result = await fetchHealthRetrying(attempt, { attempts: 4, waitMs: 3000, sleep });
    expect(result).toEqual({ status: "ok" });
    expect(attempt).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledWith(3000);
  });

  it("throws only after the last attempt", async () => {
    const attempt = vi.fn().mockRejectedValue(new Error("HTTP 502"));
    const sleep = vi.fn(async () => {});
    await expect(fetchHealthRetrying(attempt, { attempts: 3, waitMs: 10, sleep })).rejects.toThrow("HTTP 502");
    expect(attempt).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });
});
