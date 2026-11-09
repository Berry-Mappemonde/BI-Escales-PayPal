import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildV6Adapter,
  loadPayPalSdk,
  loadPayPalSubscriptionSdk,
  paypalLocale,
  paypalSdkUrl,
  safePayPalClose,
  safePayPalRender,
  payLaterEligible,
} from "./paypalSdk";

describe("PayPal Web SDK v6 core", () => {
  afterEach(() => {
    document.querySelectorAll('script[data-paypal-web-sdk="v6"]').forEach((element) => element.remove());
    document.querySelectorAll("paypal-button").forEach((element) => element.remove());
    delete window.paypal;
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
    window.paypal = { createInstance };
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
    const { loadPayPalSdk: loadNew, loadPayPalSubscriptionSdk: loadSub } = await import("./paypalSdk");
    const sdk = {
      findEligibleMethods: vi.fn().mockResolvedValue({ isEligible: () => true }),
    };
    const createInstance = vi.fn().mockResolvedValue(sdk);
    const first = loadNew("new-client", "fr", "authorize", false, "EUR");
    const script = document.querySelector<HTMLScriptElement>('script[data-paypal-web-sdk="v6"]');
    expect(script).toBeTruthy();
    expect(script?.src).toContain("/web-sdk/v6/core");
    window.paypal = { createInstance };
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
    expect(start).toHaveBeenCalledOnce();
    expect(start.mock.calls[0][0]).toEqual({ presentationMode: "auto" });
    await expect(start.mock.calls[0][1]).resolves.toEqual({ orderId: "TEST-ORDER" });
    await sessionCallbacks.onApprove({ orderId: "TEST-ORDER" });
    expect(onApprove).toHaveBeenCalledOnce();
    safePayPalClose(result.instance);
    expect(destroy).toHaveBeenCalledOnce();
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
      json: async () => ({ subscription_id: "SUB-TEST-1" }),
    });
    vi.stubGlobal("fetch", fetchStub);
    const adapter = buildV6Adapter(sdk as never, eligible);
    const host = document.createElement("div");
    const onApprove = vi.fn();
    const result = await safePayPalRender(adapter.Buttons, { createSubscription: vi.fn(), onApprove }, host);
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
    expect([...host.querySelectorAll("[data-field]")].map((node) => (node as HTMLElement).dataset.field))
      .toEqual(["number", "expiry", "cvv"]);
    const field = host.firstElementChild as HTMLElement & { destroy: ReturnType<typeof vi.fn> };
    await number.close();
    expect(field.destroy).toHaveBeenCalledOnce();
    await cards.submit();
    expect(submit).toHaveBeenCalledWith("C-ORDER");
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
