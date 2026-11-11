/**
 * How the App return handlers tell a v6 checkout from a v5 one: `hasAttempt`.
 * With the flag off nothing is ever stored, so every return keeps today's path.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { authorizePledge, registerVault } from "../../api/escales";
import { hasAttempt, reconcileAttempt, rememberAttempt } from "./checkoutAttempts";

vi.mock("../../api/escales", () => ({
  authorizePledge: vi.fn(async (id: string) => ({ id, status: "authorized" })),
  registerVault: vi.fn(async (id: string) => ({ id, status: "vaulted" })),
}));

afterEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});

function remember(pledgeId: string, mode: "AUTHORIZE" | "VAULT" = "AUTHORIZE", path = location.pathname) {
  return rememberAttempt({ key: `key-${pledgeId}`, pledgeId, orderId: `ORDER-${pledgeId}`, revision: 1, amount: "20.00", currency: "EUR", milestone: "dep-la-rochelle", target: "dep-la-rochelle", mode, path });
}

describe("hasAttempt", () => {
  it("is false when nothing was ever stored (flag off)", () => {
    expect(hasAttempt("PLEDGE-1")).toBe(false);
    expect(hasAttempt("")).toBe(false);
    expect(hasAttempt(null)).toBe(false);
    expect(hasAttempt(undefined)).toBe(false);
    expect(sessionStorage.length).toBe(0);
  });

  it("is true only for a pledge the v6 path started on this page", () => {
    remember("PLEDGE-1");
    remember("ELSEWHERE", "AUTHORIZE", "/another-page");
    expect(hasAttempt("PLEDGE-1")).toBe(true);
    expect(hasAttempt("PLEDGE-2")).toBe(false);
    expect(hasAttempt("ELSEWHERE")).toBe(false);
  });

  it("stays true once the attempt is verified, so a repeated return is still deduplicated", async () => {
    remember("PLEDGE-1");
    await reconcileAttempt("PLEDGE-1");
    expect(hasAttempt("PLEDGE-1")).toBe(true);
    await reconcileAttempt("PLEDGE-1");
    expect(authorizePledge).toHaveBeenCalledTimes(1);
  });

  it("survives unreadable storage", () => {
    sessionStorage.setItem("escales-v6-attempts", "{not json");
    expect(hasAttempt("PLEDGE-1")).toBe(false);
  });
});

describe("reconcileAttempt from the App return handler", () => {
  it("passes the vault approval token through, once", async () => {
    remember("VAULT-1", "VAULT");
    await Promise.all([reconcileAttempt("VAULT-1", true, "TOKEN"), reconcileAttempt("VAULT-1", true, "TOKEN")]);
    expect(registerVault).toHaveBeenCalledTimes(1);
    expect(registerVault).toHaveBeenCalledWith("VAULT-1", "TOKEN");
    expect(authorizePledge).not.toHaveBeenCalled();
  });

  it("can be retried after a failure", async () => {
    // Receipts are remembered per attempt for the page's lifetime, so this test uses its own pledge.
    remember("RETRY-1");
    vi.mocked(authorizePledge).mockRejectedValueOnce(new Error("temporary"));
    await expect(reconcileAttempt("RETRY-1")).rejects.toThrow("temporary");
    await expect(reconcileAttempt("RETRY-1")).resolves.toMatchObject({ id: "RETRY-1" });
    expect(authorizePledge).toHaveBeenCalledTimes(2);
  });
});
