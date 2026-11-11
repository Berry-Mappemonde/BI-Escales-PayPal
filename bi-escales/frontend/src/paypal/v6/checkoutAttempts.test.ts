import { afterEach, expect, it, vi } from "vitest";
import { rememberAttempt, resumeCheckout, reconcileAttempt, returnedAttempt } from "./checkoutAttempts";
import { authorizePledge } from "../../api/escales";
vi.mock("../../api/escales", () => ({ authorizePledge: vi.fn(async (id: string) => ({ id, status: "authorized" })), registerVault: vi.fn() }));
afterEach(() => { sessionStorage.clear(); vi.clearAllMocks(); });
function remember(id: string, path = location.pathname) {
  return rememberAttempt({ key: id, pledgeId: id, orderId: `ORDER-${id}`, revision: 1, amount: "20.00", currency: "EUR", milestone: "stop", target: "target", mode: "AUTHORIZE", path });
}
it("F01 duplicate renders/resume callbacks reconcile one server-authoritative receipt", async () => {
  remember("resume-receipt"); const receipt = vi.fn(async () => { await reconcileAttempt("resume-receipt"); });
  await Promise.all([resumeCheckout({ hasReturned: () => true, resume: receipt }, false), resumeCheckout({ hasReturned: () => true, resume: receipt }, false)]);
  await reconcileAttempt("resume-receipt");
  expect(receipt).toHaveBeenCalledOnce(); expect(authorizePledge).toHaveBeenCalledOnce();
});
it("F01 forged and cross-page returns cannot resume without unique local correlation", async () => {
  const resume = vi.fn();
  await resumeCheckout({ hasReturned: () => true, resume }, false);
  remember("another-page", "/another-checkout");
  await resumeCheckout({ hasReturned: () => true, resume }, false);
  expect(resume).not.toHaveBeenCalled(); expect(authorizePledge).not.toHaveBeenCalled();
});
it("F01 cancelled/not-returned sessions and ambiguous saved attempts fail closed", async () => {
  remember("cancel-a"); const resume = vi.fn();
  await resumeCheckout({ hasReturned: () => false, resume }, false);
  remember("cancel-b"); expect(returnedAttempt()).toBeUndefined();
  await resumeCheckout({ hasReturned: () => true, resume }, false);
  expect(resume).not.toHaveBeenCalled();
});
it("F01 verified receipts do not block a later pending return or erase another page", async () => {
  remember("old-completed"); await reconcileAttempt("old-completed");
  remember("pending-new"); expect(returnedAttempt()?.pledgeId).toBe("pending-new");
  remember("other-page-pending", "/other-page");
  expect(returnedAttempt()?.pledgeId).toBe("pending-new");
  expect(JSON.parse(sessionStorage.getItem("escales-v6-attempts") || "[]")).toHaveLength(3);
});
