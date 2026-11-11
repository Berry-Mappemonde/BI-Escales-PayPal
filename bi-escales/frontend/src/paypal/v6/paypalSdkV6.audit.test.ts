import { afterEach, expect, it, vi } from "vitest";
import { buildV6Adapter, loadPayPalSdk } from "./paypalSdkV6";
/** The v6 core global; `Window.paypal` itself is typed for the v5 SDK. */
const v6Window = window as unknown as { paypal?: unknown };

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); delete v6Window.paypal; });
const eligible = { isEligible: () => true };
function subscription(plan = "DISPLAYED") {
  let callbacks: Record<string, any>;
  const start = vi.fn(async (_options: unknown, pending: Promise<unknown>) => { await pending; });
  const onError = vi.fn();
  const button = buildV6Adapter({ createPayPalSubscriptionPaymentSession: (options: Record<string, any>) => { callbacks = options; return { start, destroy: vi.fn() }; } } as never, eligible).Buttons!({
    createSubscription: (_data: unknown, actions: { subscription: { create: (body: unknown) => Promise<string> } }) => actions.subscription.create({ plan_id: plan }), onError,
  });
  return { start, onError, button, callbacks: () => callbacks };
}
it("F01 resumes a correlated returned SDK session once without replacing its callbacks", async () => {
  sessionStorage.setItem("escales-v6-attempts", JSON.stringify([{ pledgeId: "P", orderId: "ORDER", mode: "AUTHORIZE", key: "attempt", revision: 0, amount: "20.00", currency: "EUR", milestone: "stop", target: "stop", path: location.pathname }]));
  const resume = vi.fn().mockResolvedValue(undefined); const hasReturned = vi.fn(() => true);
  const button = buildV6Adapter({ createPayPalOneTimePaymentSession: () => ({ start: vi.fn(), destroy: vi.fn(), hasReturned, resume }) } as never, eligible).Buttons!({ createOrder: () => "ORDER" });
  await button.render(document.createElement("div"));
  expect(hasReturned).toHaveBeenCalled(); expect(resume).toHaveBeenCalledOnce();
});
it("F03 refuses the server-created subscription if its verified plan differs from the displayed selection", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ subscription_id: "SUB", plan_id: "OTHER" }) }));
  const h = subscription(); const host = document.createElement("div"); await h.button.render(host); host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringMatching(/plan.*match/i) })));
});
it("F04 retries an uncertain subscription creation with the original logical attempt key", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("connection lost")).mockResolvedValue({ ok: true, json: async () => ({ subscription_id: "SUB", plan_id: "DISPLAYED" }) });
  vi.stubGlobal("fetch", fetcher);
  const h = subscription(); const host = document.createElement("div"); await h.button.render(host); host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(h.onError).toHaveBeenCalledOnce());
  host.firstElementChild!.dispatchEvent(new MouseEvent("click")); await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(fetcher.mock.calls[0][1].headers["PayPal-Request-Id"]).toBe(fetcher.mock.calls[1][1].headers["PayPal-Request-Id"]);
});
it("F05 includes normalized transaction amount in SDK eligibility and its cache key", async () => {
  const findEligibleMethods = vi.fn().mockResolvedValue(eligible);
  v6Window.paypal = { createInstance: vi.fn().mockResolvedValue({ findEligibleMethods }) };
  const load = loadPayPalSdk as (...args: unknown[]) => Promise<unknown>;
  await load("amount-audit-client", "en", "capture", false, "EUR", "ONE_TIME_PAYMENT", "30.00");
  await load("amount-audit-client", "en", "capture", false, "EUR", "ONE_TIME_PAYMENT", "50.00");
  expect(findEligibleMethods).toHaveBeenNthCalledWith(1, { amount: "30.00", currencyCode: "EUR", paymentFlow: "ONE_TIME_PAYMENT" });
  expect(findEligibleMethods).toHaveBeenNthCalledWith(2, { amount: "50.00", currencyCode: "EUR", paymentFlow: "ONE_TIME_PAYMENT" });
});


it("F04 a verified terminal approval permits a genuinely new consent attempt", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ subscription_id: "NEW-SUB", plan_id: "NEW-PLAN" }) });
  vi.stubGlobal("fetch", fetcher);
  const h = subscription("NEW-PLAN"); const host = document.createElement("div"); await h.button.render(host);
  host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  await h.start.mock.results[0].value;
  await h.callbacks().onApprove({ subscriptionId: "NEW-SUB" });
  host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(fetcher.mock.calls[0][1].headers["PayPal-Request-Id"]).not.toBe(fetcher.mock.calls[1][1].headers["PayPal-Request-Id"]);
});
it("F01 subscription redirect resumes the original callbacks with stored consent correlation", async () => {
  const key = `escales-v6-subscription:${location.pathname}:fr:RESUME-PLAN`;
  sessionStorage.setItem(key, "resume-consent");
  sessionStorage.setItem(key + ":subscriptionId", "RESUME-SUB");
  let callbacks: Record<string, any>;
  const verified = vi.fn().mockResolvedValue(undefined);
  const resume = vi.fn(async () => { await callbacks.onApprove({ subscriptionId: "RESUME-SUB" }); });
  const sdk = { createPayPalSubscriptionPaymentSession: (options: Record<string, any>) => { callbacks = options; return { start: vi.fn(), destroy: vi.fn(), hasReturned: () => true, resume }; } };
  const buttons = buildV6Adapter(sdk as never, eligible).Buttons!({ subscriptionPlanId: "RESUME-PLAN", createSubscription: vi.fn(), onApprove: verified });
  await buttons.render(document.createElement("div"));
  expect(resume).toHaveBeenCalledOnce(); expect(verified).toHaveBeenCalledWith({ subscriptionID: "RESUME-SUB" });
  expect(sessionStorage.getItem(key)).toBeNull();
});
it.each(["0", "-5", "30oops", "NaN"])("F05 rejects malformed eligibility amount %s", async amount => {
  await expect((loadPayPalSdk as (...args: unknown[]) => Promise<unknown>)("invalid-amount", "en", "capture", false, "EUR", "ONE_TIME_PAYMENT", amount)).rejects.toThrow(/amount/);
});

it("F04 a duplicate old approval cannot clear a newer consent attempt", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ subscription_id: "OLD-ID", plan_id: "LATE-PLAN" }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ subscription_id: "NEW-ID", plan_id: "LATE-PLAN" }) });
  vi.stubGlobal("fetch", fetcher);
  const first = subscription("LATE-PLAN"); const host = document.createElement("div"); await first.button.render(host);
  host.firstElementChild!.dispatchEvent(new MouseEvent("click")); await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce()); await first.start.mock.results[0].value;
  await first.callbacks().onApprove({ subscriptionId: "OLD-ID" });
  const next = subscription("LATE-PLAN"); await next.button.render(host); host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2)); await next.start.mock.results[0].value;
  const scope = `escales-v6-subscription:${location.pathname}:fr:LATE-PLAN`;
  const currentKey = sessionStorage.getItem(scope);
  await first.callbacks().onApprove({ subscriptionId: "OLD-ID" });
  expect(sessionStorage.getItem(scope)).toBe(currentKey);
  expect(sessionStorage.getItem(scope + ":subscriptionId")).toBe("NEW-ID");
});

it("F05 unsupported currency/country eligibility falls back without a provider order", async () => {
  const createOrder = vi.fn();
  v6Window.paypal = { createInstance: vi.fn().mockResolvedValue({ findEligibleMethods: async () => ({ isEligible: () => false }), createPayPalOneTimePaymentSession: () => ({ start: vi.fn(), destroy: vi.fn() }) }) };
  const ns = await loadPayPalSdk("ineligible-context", "en", "capture", false, "JPY", "ONE_TIME_PAYMENT", "50.00");
  const buttons = ns.Buttons!({ createOrder, offerPayLater: true });
  await expect(buttons.render(document.createElement("div"))).rejects.toThrow(/eligible/);
  expect(createOrder).not.toHaveBeenCalled();
});
it("F04 a remounted subscription adapter reuses the unresolved consent resource", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ subscription_id: "SAME-SUB", plan_id: "REMOUNT-PLAN" }) });
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); const original = subscription("REMOUNT-PLAN");
  await original.button.render(host); host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce()); await original.start.mock.results[0].value;
  await original.button.close!();
  const next = subscription("REMOUNT-PLAN"); await next.button.render(host); host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  await vi.waitFor(() => expect(next.start).toHaveBeenCalledOnce()); await next.start.mock.results[0].value;
  expect(fetcher).toHaveBeenCalledOnce();
});
