import { afterEach, describe, expect, it, vi } from "vitest";
import { currentPayPalJsVersion, notePayPalJsFeatures, resetPayPalJsVersionForTests } from "../paypalJsVersion";
import {
  buildV6Adapter,
  loadPayPalSdk,
  loadPayPalSubscriptionSdk,
  paypalLocale,
  paypalSdkUrl,
  safePayPalClose,
  safePayPalRender,
  payLaterEligible,
} from "./paypalSdkV6";

/** The v6 core global; `Window.paypal` itself is typed for the v5 SDK. */
const v6Window = window as unknown as { paypal?: unknown };

describe("PayPal Web SDK v6 core", () => {
  afterEach(() => {
    document.querySelectorAll('script[data-paypal-web-sdk="v6"]').forEach((element) => element.remove());
    document.querySelectorAll("paypal-button").forEach((element) => element.remove());
    delete v6Window.paypal;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses the sandbox v6 core without a client ID or legacy script URL", () => {
    const url = paypalSdkUrl("browser-safe-id", "en", "authorize", true);
    expect(url).toBe("https://www.sandbox.paypal.com/web-sdk/v6/core");
    expect(url).not.toContain("client-id=");
    expect(url).not.toContain("sdk/js?");
  });

  it("passes locale to createInstance rather than the script URL", async () => {
    const findEligibleMethods = vi.fn().mockResolvedValue({ isEligible: () => true });
    const createInstance = vi.fn().mockResolvedValue({
      findEligibleMethods,
      createPayPalOneTimePaymentSession: vi.fn().mockReturnValue({ start: vi.fn() }),
    });
    v6Window.paypal = { createInstance };
    const ns = await loadPayPalSdk("safe-client", "en", "authorize", false, "EUR");
    expect(ns.Buttons).toEqual(expect.any(Function));
    expect(createInstance).toHaveBeenCalledWith(expect.objectContaining({
      clientId: "safe-client",
      locale: "en-US",
      components: expect.arrayContaining(["paypal-payments", "paypal-subscriptions", "card-fields"]),
    }));
    expect(findEligibleMethods).toHaveBeenCalledWith({ currencyCode: "EUR", paymentFlow: "ONE_TIME_PAYMENT" });
    expect(document.querySelectorAll('script[data-paypal-web-sdk="v6"]')).toHaveLength(0);
  });

  it("reuses a single v6 core for checkout and subscriptions", async () => {
    const { loadPayPalSdk: loadNew, loadPayPalSubscriptionSdk: loadSub } = await import("./paypalSdkV6");
    const sdk = {
      findEligibleMethods: vi.fn().mockResolvedValue({ isEligible: () => true }),
    };
    const createInstance = vi.fn().mockResolvedValue(sdk);
    const first = loadNew("new-client", "fr", "authorize", false, "EUR");
    const script = document.querySelector<HTMLScriptElement>('script[data-paypal-web-sdk="v6"]');
    expect(script).toBeTruthy();
    expect(script?.src).toContain("/web-sdk/v6/core");
    v6Window.paypal = { createInstance };
    script!.dispatchEvent(new Event("load"));
    await first;
    await loadSub("new-client", "fr");
    expect(document.querySelectorAll('script[data-paypal-web-sdk="v6"]')).toHaveLength(1);
    expect(createInstance).toHaveBeenCalledTimes(2);
    expect(sdk.findEligibleMethods).toHaveBeenLastCalledWith({ currencyCode: "EUR", paymentFlow: "RECURRING_PAYMENT" });
  });

  it("refuses a legacy script loaded on the page", async () => {
    const script = document.createElement("script");
    script.src = "https://www.paypal.com/sdk/js?client-id=legacy";
    document.body.appendChild(script);
    try {
      await expect(loadPayPalSdk("no-v5-collision", "fr")).rejects.toThrow(/coexist/);
    } finally {
      script.remove();
    }
  });

  it("uses v5 only when the v6 core fails to load", async () => {
    resetPayPalJsVersionForTests();
    notePayPalJsFeatures({ paypal_js_v6: true });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    v6Window.paypal = { createInstance: vi.fn().mockRejectedValue(new Error("createInstance down")) };
    await expect(loadPayPalSdk("load-fail-client", "en")).rejects.toThrow(/createInstance down/);
    expect(currentPayPalJsVersion()).toBe("v5");
    expect(warn).toHaveBeenCalledOnce();
    resetPayPalJsVersionForTests();
  });

  it("stays on v6 when eligibility fails", async () => {
    resetPayPalJsVersionForTests();
    notePayPalJsFeatures({ paypal_js_v6: true });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    v6Window.paypal = {
      createInstance: vi.fn().mockResolvedValue({
        findEligibleMethods: vi.fn().mockRejectedValue(new Error("eligibility down")),
      }),
    };
    await expect(loadPayPalSdk("eligibility-client", "en", "capture", false, "EUR")).rejects.toThrow(/eligibility down/);
    expect(currentPayPalJsVersion()).toBe("v6");
    expect(warn).not.toHaveBeenCalled();
    resetPayPalJsVersionForTests();
  });

  it("requires a client ID", async () => {
    await expect(loadPayPalSubscriptionSdk("  ")).rejects.toThrow(/client id/);
    await expect(loadPayPalSdk("")).rejects.toThrow(/client id/);
  });
});

describe("v6 payment session adapters", () => {
  afterEach(() => {
    document.querySelectorAll("paypal-button").forEach((element) => element.remove());
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  const eligible = { isEligible: (kind: string) => ["paypal", "advanced_cards"].includes(kind) };

  it("starts one-time checkout using a Promise<{orderId}> and calls server approval", async () => {
    let sessionCallbacks: Record<string, any> = {};
    const start = vi.fn().mockResolvedValue(undefined);
    const destroy = vi.fn();
    const sdk = {
      createPayPalOneTimePaymentSession: vi.fn((opts) => {
        sessionCallbacks = opts;
        return { start, destroy };
      }),
    };
    const adapter = buildV6Adapter(sdk as never, eligible);
    const onApprove = vi.fn();
    const createOrder = vi.fn().mockResolvedValue("TEST-ORDER");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const result = await safePayPalRender(adapter.Buttons, { createOrder, onApprove }, host);
    expect(result.ok).toBe(true);
    expect(host.querySelector("paypal-button")).toBeTruthy();
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(start).toHaveBeenCalledOnce());
    expect(start.mock.calls[0][0]).toEqual({ presentationMode: "auto" });
    await expect(start.mock.calls[0][1]).resolves.toEqual({ orderId: "TEST-ORDER" });
    await sessionCallbacks.onApprove({ orderId: "TEST-ORDER" });
    expect(onApprove).toHaveBeenCalledOnce();
    safePayPalClose(result.instance);
    expect(destroy).toHaveBeenCalledOnce();
    host.remove();
  });

  it("falls back from app switch to popup on a phone, and stops when the buyer cancels", async () => {
    const agent = vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)");
    const start = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("switch unavailable"), { isRecoverable: true, code: "APP_SWITCH_FAILED" }))
      .mockResolvedValueOnce(undefined);
    const sdk = { createPayPalOneTimePaymentSession: vi.fn(() => ({ start, destroy: vi.fn() })) };
    const adapter = buildV6Adapter(sdk as never, eligible);
    const host = document.createElement("div");
    const result = await safePayPalRender(adapter.Buttons, { createOrder: vi.fn().mockResolvedValue("TEST-ORDER") }, host);
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(start).toHaveBeenCalledTimes(2));
    expect(start.mock.calls[0][0]).toEqual({ presentationMode: "direct-app-switch", autoRedirect: { enabled: true } });
    expect(start.mock.calls[1][0]).toEqual({ presentationMode: "popup" });
    await expect(start.mock.calls[1][1]).resolves.toEqual({ orderId: "TEST-ORDER" });
    safePayPalClose(result.instance);

    const cancelled = vi.fn().mockRejectedValueOnce(Object.assign(new Error("cancelled"), { name: "CheckoutCancelled", isRecoverable: true }));
    const onError = vi.fn();
    const again = buildV6Adapter({ createPayPalOneTimePaymentSession: () => ({ start: cancelled, destroy: vi.fn() }) } as never, eligible);
    const second = await safePayPalRender(again.Buttons, { createOrder: () => "TEST-ORDER", onError }, host);
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(cancelled).toHaveBeenCalledOnce();
    safePayPalClose(second.instance);
    agent.mockRestore();
    host.remove();
  });

  it("uses save-payment session and keeps vault setup token out of URLs", async () => {
    const start = vi.fn().mockResolvedValue(undefined);
    const sdk = {
      createPayPalSavePaymentSession: vi.fn(() => ({ start })),
    };
    const adapter = buildV6Adapter(sdk as never, eligible);
    const host = document.createElement("div");
    const result = await safePayPalRender(adapter.Buttons, {
      createVaultSetupToken: vi.fn().mockResolvedValue("SETUP-TOKEN"),
    }, host);
    expect(result.ok).toBe(true);
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await expect(start.mock.calls[0][1]).resolves.toEqual({ vaultSetupToken: "SETUP-TOKEN" });
    safePayPalClose(result.instance);
  });

  it("creates subscriptions on the server and maps approval to membership callback", async () => {
    const start = vi.fn().mockResolvedValue(undefined);
    let subscriptionCallbacks: Record<string, any> = {};
    const sdk = {
      createPayPalSubscriptionPaymentSession: vi.fn((callbacks) => {
        subscriptionCallbacks = callbacks;
        return { start };
      }),
    };
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ subscription_id: "SUB-TEST-1", plan_id: "PLAN" }),
    });
    vi.stubGlobal("fetch", fetchStub);
    const adapter = buildV6Adapter(sdk as never, eligible);
    const host = document.createElement("div");
    const onApprove = vi.fn();
    const result = await safePayPalRender(adapter.Buttons, { createSubscription: vi.fn((_data, actions) => actions.subscription.create({ plan_id: "PLAN" })), onApprove }, host);
    expect(result.ok).toBe(true);
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await expect(start.mock.calls[0][1]).resolves.toEqual({ subscriptionId: "SUB-TEST-1" });
    expect(fetchStub).toHaveBeenCalledWith(
      expect.stringContaining("/api/escales/paypal/subscriptions/create"),
      expect.objectContaining({ method: "POST" }),
    );
    await subscriptionCallbacks.onApprove({ subscriptionId: "SUB-TEST-1" });
    expect(onApprove).toHaveBeenCalledWith({ subscriptionID: "SUB-TEST-1" });
    safePayPalClose(result.instance);
  });

  it("renders hosted card fields and only reports success after submit", async () => {
    const submit = vi.fn().mockResolvedValue({ state: "succeeded", data: { orderId: "C-ORDER" } });
    const sdk = {
      createCardFieldsOneTimePaymentSession: () => ({
        createCardFieldsComponent: ({ type }: { type: string }) => {
          const node = Object.assign(document.createElement("div"), { destroy: vi.fn() });
          node.dataset.field = type;
          return node;
        },
        submit,
      }),
    };
    const adapter = buildV6Adapter(sdk as never, eligible);
    const makeOrder = vi.fn().mockResolvedValue("C-ORDER");
    const cards = adapter.CardFields!({ createOrder: makeOrder, onApprove: vi.fn() }) as Record<string, any>;
    expect(cards.isEligible()).toBe(true);
    const host = document.createElement("div");
    const number = cards.NumberField();
    await number.render(host);
    await cards.ExpiryField().render(host);
    await cards.CVVField().render(host);
    await cards.NameField().render(host);
    expect([...host.querySelectorAll("[data-field]")].map((node) => (node as HTMLElement).dataset.field))
      .toEqual(["number", "expiry", "cvv", "name"]);
    const field = host.firstElementChild as HTMLElement & { destroy: ReturnType<typeof vi.fn> };
    await number.close();
    expect(field.destroy).toHaveBeenCalledOnce();
    await cards.submit();
    expect(submit).toHaveBeenCalledWith("C-ORDER");
  });

  it("sends billing address and lets a dismissed card challenge be retried", async () => {
    const submit = vi.fn()
      .mockResolvedValueOnce({ state: "canceled", data: {} })
      .mockResolvedValueOnce({ state: "succeeded", data: { orderId: "C-ORDER" } });
    const adapter = buildV6Adapter({
      createCardFieldsOneTimePaymentSession: () => ({ createCardFieldsComponent: vi.fn(), submit, destroy: vi.fn() }),
    } as never, eligible);
    const onApprove = vi.fn();
    const onCancel = vi.fn();
    const cards = adapter.CardFields!({
      createOrder: async () => "C-ORDER",
      onApprove,
      onCancel,
      billingAddress: () => ({ countryCode: "FR", postalCode: "17000", addressLine1: "" }),
    }) as Record<string, any>;
    await cards.submit();
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onApprove).not.toHaveBeenCalled();
    expect(submit).toHaveBeenCalledWith("C-ORDER", { billingAddress: { countryCode: "FR", postalCode: "17000" } });
    await cards.submit();
    expect(onApprove).toHaveBeenCalledOnce();
  });

  it("checks vault card session result before calling approval", async () => {
    const submit = vi.fn().mockResolvedValue({ state: "failed", data: { message: "3DS declined" } });
    const adapter = buildV6Adapter({
      createCardFieldsSavePaymentSession: () => ({
        createCardFieldsComponent: vi.fn(),
        submit,
      }),
    } as never, eligible);
    const cards = adapter.CardFields!({
      createVaultSetupToken: vi.fn().mockResolvedValue("SETUP-1"),
    }) as Record<string, any>;
    await expect(cards.submit()).rejects.toThrow(/3DS declined/);
    expect(submit).toHaveBeenCalledWith("SETUP-1");
  });

  it("catches rendering failures and safely closes buttons", async () => {
    const target = document.createElement("div");
    const failure = await safePayPalRender(() => {
      throw new Error("failure");
    }, {}, target);
    expect(failure.ok).toBe(false);
    expect(failure.error).toBeInstanceOf(Error);
    expect(() => safePayPalClose(null)).not.toThrow();
  });
});

describe("locale and price guards", () => {
  it("uses expected locales", () => {
    expect(paypalLocale()).toBe("fr_FR");
    expect(paypalLocale("fr-FR")).toBe("fr_FR");
    expect(paypalLocale("en")).toBe("en_US");
  });
  it("permits Pay Later text only for eligible project donations", () => {
    expect(payLaterEligible("29.99")).toBe(false);
    expect(payLaterEligible("30")).toBe(true);
    expect(payLaterEligible("40", "project_pledge")).toBe(true);
    expect(payLaterEligible("40", "mile")).toBe(false);
  });
});

it("renders v6 Pay Later messages using the native element and currency", async () => {
  const open = vi.fn();
  const createLearnMore = vi.fn(() => ({ open }));
  const createPayPalMessages = vi.fn(() => ({ createLearnMore }));
  const adapter = buildV6Adapter({ createPayPalMessages } as never, { isEligible: () => true });
  const host = document.createElement("div");
  const message = adapter.Messages!({ amount: "50.00", currencyCode: "EUR" });
  await message.render(host);
  const element = host.querySelector("paypal-message")!;
  expect(element.amount).toBe("50.00");
  expect(element.currencyCode).toBe("EUR");
  expect(element.textColor).toBe("WHITE");
  expect(element.buyerCountry).toBe("FR");
  expect(createPayPalMessages).toHaveBeenCalledWith({ currencyCode: "EUR", buyerCountry: "FR" });
  expect(createLearnMore).toHaveBeenCalledWith({
    amount: "50.00", currencyCode: "EUR", buyerCountry: "FR", presentationMode: "MODAL",
  });
  expect(element.presentationMode).toBe("MODAL");
  expect(element.getAttribute("presentation-mode")).toBe("MODAL");
  element.dispatchEvent(new MouseEvent("click"));
  expect(open).not.toHaveBeenCalled();
  const learnMoreClick = new CustomEvent("paypal-message-click", {
    cancelable: true,
    detail: { config: { amount: "50.00" } },
  });
  element.dispatchEvent(learnMoreClick);
  expect(learnMoreClick.defaultPrevented).toBe(true);
  expect(open).toHaveBeenCalledTimes(1);
  expect(open).toHaveBeenCalledWith({ amount: "50.00" });
  document.documentElement.dataset.theme = "light";
  await vi.waitFor(() => expect(element.textColor).toBe("BLACK"));
  delete document.documentElement.dataset.theme;
  await message.close!(); expect(host.children).toHaveLength(0);
});

describe("v6 lifecycle and legacy callback parity", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each(["authorize", "capture"] as const)("keeps %s commit semantics on the one-time session", async intent => {
    const factory = vi.fn(() => ({ start: vi.fn(), destroy: vi.fn() }));
    const button = buildV6Adapter({ createPayPalOneTimePaymentSession: factory } as never, { isEligible: () => true }, false, intent).Buttons!({ createOrder: () => "ORDER" });
    expect(factory).toHaveBeenCalledWith(expect.objectContaining({ commit: intent === "capture" }));
    await button.close!();
  });

  it("deduplicates concurrent clicks and preserves late approval for original-pledge reconciliation", async () => {
    let release!: () => void;
    let callbacks: any;
    const destroy = vi.fn();
    const start = vi.fn(async (_opts, pending) => { await pending; await new Promise<void>(resolve => { release = resolve; }); });
    const factory = (options: any) => { callbacks = options; return { start, destroy }; };
    const createOrder = vi.fn(() => "ORDER");
    const onApprove = vi.fn(); const onCancel = vi.fn();
    const host = document.createElement("div");
    const button = buildV6Adapter({ createPayPalOneTimePaymentSession: factory } as never, { isEligible: () => true }).Buttons!({ createOrder, onApprove, onCancel });
    await button.render(host); const element = host.querySelector("paypal-button")!;
    element.dispatchEvent(new MouseEvent("click")); element.dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(createOrder).toHaveBeenCalledOnce());
    expect(start).toHaveBeenCalledOnce();
    await button.close!(); await button.close!();
    await callbacks.onApprove({ orderId: "ORDER" }); callbacks.onCancel();
    expect(onApprove).toHaveBeenCalledOnce(); expect(onCancel).not.toHaveBeenCalled(); expect(destroy).toHaveBeenCalledOnce();
    release(); await expect(button.render(host)).rejects.toThrow(/closed/);
  });

  it("reports rejected merchant token creation through onError", async () => {
    const start = vi.fn(async (_opts, pending) => { await pending; });
    const onError = vi.fn();
    const button = buildV6Adapter({ createPayPalOneTimePaymentSession: () => ({ start, destroy: vi.fn() }) } as never, { isEligible: () => true }).Buttons!({ createOrder: () => { throw new Error("merchant creation failed"); }, onError });
    const host = document.createElement("div"); await button.render(host);
    host.querySelector("paypal-button")!.dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: "merchant creation failed" })));
    await button.close!();
  });

  it("renders Pay Later only when the app and merchant agree, using SDK metadata", async () => {
    const start = vi.fn().mockResolvedValue(undefined); const laterDestroy = vi.fn();
    const sdk = {
      createPayPalOneTimePaymentSession: vi.fn(() => ({ start: vi.fn(), destroy: vi.fn() })),
      createPayLaterOneTimePaymentSession: vi.fn(() => ({ start, destroy: laterDestroy })),
    };
    const adapter = buildV6Adapter(sdk as never, { isEligible: () => true, getDetails: () => ({ countryCode: "FR", productCode: "PAYLATER" }) } as never, false, "capture");
    const host = document.createElement("div"); const createOrder = vi.fn(() => "LATER-ORDER");
    const buttons = adapter.Buttons!({ createOrder, offerPayLater: true }); await buttons.render(host);
    const later = host.querySelector("paypal-pay-later-button")!;
    expect(later.countryCode).toBe("FR"); expect(later.productCode).toBe("PAYLATER");
    later.dispatchEvent(new MouseEvent("click"));
    await expect(start.mock.calls[0][1]).resolves.toEqual({ orderId: "LATER-ORDER" });
    expect(sdk.createPayLaterOneTimePaymentSession).toHaveBeenCalledWith(expect.objectContaining({ commit: true }));
    await buttons.close!(); expect(laterDestroy).toHaveBeenCalledOnce();
    await adapter.Buttons!({ createOrder, offerPayLater: false }).render(host);
    expect(host.querySelector("paypal-pay-later-button")).toBeNull();
  });

  it("destroying all hosted fields prevents a pending submission from reaching PayPal", async () => {
    let resolve!: (id: string) => void;
    const pending = new Promise<string>(done => { resolve = done; });
    const submit = vi.fn(); const destroy = vi.fn();
    const sdk = { createCardFieldsOneTimePaymentSession: () => ({ submit, destroy, createCardFieldsComponent: () => Object.assign(document.createElement("div"), { destroy: vi.fn() }) }) };
    const cards = buildV6Adapter(sdk as never, { isEligible: () => true }).CardFields!({ createOrder: () => pending }) as any;
    const field = cards.NumberField(); await field.render(document.createElement("div"));
    const submission = cards.submit(); await field.close(); resolve("CARD-ORDER");
    await expect(submission).rejects.toThrow(/closed/);
    expect(submit).not.toHaveBeenCalled(); expect(destroy).toHaveBeenCalledOnce();
  });
});

it.each(["succeeded", "canceled", "failed"])("card vault %s result preserves approval gating", async state => {
  const submit = vi.fn().mockResolvedValue({ state, data: { vaultSetupToken: "SETUP", message: "not completed" } });
  const onApprove = vi.fn();
  const onCancel = vi.fn();
  const adapter = buildV6Adapter({ createCardFieldsSavePaymentSession: () => ({ submit, destroy: vi.fn() }) } as never, { isEligible: () => true });
  const cards = adapter.CardFields!({ createVaultSetupToken: () => "SETUP", onApprove, onCancel }) as any;
  if (state === "succeeded") {
    await cards.submit();
    expect(onApprove).toHaveBeenCalledWith({ vaultSetupToken: "SETUP", message: "not completed" });
    expect(onCancel).not.toHaveBeenCalled();
  } else if (state === "canceled") {
    await cards.submit();
    expect(onApprove).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledOnce();
  } else {
    await expect(cards.submit()).rejects.toThrow(/not completed/);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  }
  expect(submit).toHaveBeenCalledWith("SETUP");
});

it("a mismatched card confirmation cannot approve another order", async () => {
  const onApprove = vi.fn();
  const adapter = buildV6Adapter({ createCardFieldsOneTimePaymentSession: () => ({ submit: async () => ({ state: "succeeded", data: { orderId: "OTHER" } }), destroy: vi.fn() }) } as never, { isEligible: () => true });
  const cards = adapter.CardFields!({ createOrder: () => "EXPECTED", onApprove }) as any;
  await expect(cards.submit()).rejects.toThrow(/mismatch/); expect(onApprove).not.toHaveBeenCalled();
});
