import { afterEach, describe, expect, it, vi } from "vitest";
import { walletFactories } from "./paypalWallets";
import { currentPayPalJsVersion, notePayPalJsFeatures, reportPayPalV6LoadFailure, resetPayPalJsVersionForTests } from "../paypalJsVersion";

const details = { config: { merchantCountry: "FR", supportedNetworks: ["visa"], merchantCapabilities: ["supports3DS"] } };
const eligible = { isEligible: (name: string) => ["googlepay", "applepay"].includes(name), getDetails: () => details } as never;
const config = { apiVersion: 2, apiVersionMinor: 0, allowedPaymentMethods: [], merchantInfo: {}, countryCode: "FR" };
function googleHarness(status = "APPROVED") {
  let callbacks: any;
  let click: () => void;
  const session = { formatConfigForPaymentRequest: vi.fn(() => config), confirmOrder: vi.fn().mockResolvedValue({ status, id: "ORDER" }), initiatePayerAction: vi.fn().mockResolvedValue({}) };
  const client = {
    isReadyToPay: vi.fn().mockResolvedValue({ result: true }),
    createButton: vi.fn(({ onClick }) => { click = onClick; return document.createElement("button"); }),
    loadPaymentData: vi.fn(async () => { await callbacks.onPaymentAuthorized({ paymentMethodData: {} }); return {}; }),
  };
  const ctor = vi.fn(function (opts: any) { callbacks = opts.paymentDataCallbacks; return client; });
  vi.stubGlobal("google", { payments: { api: { PaymentsClient: ctor } } });
  const options = { amount: "12.50", currencyCode: "EUR", createOrder: vi.fn().mockResolvedValue("ORDER"), onApprove: vi.fn().mockResolvedValue(undefined), onError: vi.fn() };
  const sdk = { createGooglePayOneTimePaymentSession: vi.fn(() => session) };
  return { session, client, options, sdk, ctor, click: () => click(), authorize: () => callbacks.onPaymentAuthorized({ paymentMethodData: {} }) };
}
afterEach(() => { resetPayPalJsVersionForTests(); vi.unstubAllGlobals(); vi.restoreAllMocks(); document.querySelectorAll('script[src*="applepay"]').forEach(s => s.remove()); });

describe("independent Google Pay eligibility", () => {
  it("requires merchant eligibility before loading native APIs or creating orders", async () => {
    const h = googleHarness();
    const wallets = walletFactories(h.sdk as never, { isEligible: () => false } as never);
    await expect(wallets.Googlepay(h.options).render(document.createElement("div"))).rejects.toThrow(/eligible/);
    expect(h.ctor).not.toHaveBeenCalled();
    expect(h.options.createOrder).not.toHaveBeenCalled();
  });
  it("Google Pay works without Apple Pay and checks native readiness independently", async () => {
    const h = googleHarness();
    const wallets = walletFactories(h.sdk as never, eligible);
    await expect(wallets.Applepay(h.options).render(document.createElement("div"))).rejects.toThrow(/eligible/);
    await wallets.Googlepay(h.options).render(document.createElement("div"));
    expect(h.ctor).toHaveBeenCalledWith(expect.objectContaining({ environment: "TEST" }));
    expect(h.client.isReadyToPay).toHaveBeenCalledWith(expect.objectContaining({ apiVersion: 2 }));
    expect(h.options.createOrder).not.toHaveBeenCalled();
  });
  it("device ineligibility never creates a payment", async () => {
    const h = googleHarness(); h.client.isReadyToPay.mockResolvedValue({ result: false });
    await expect(walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div"))).rejects.toThrow(/not ready/);
    expect(h.options.createOrder).not.toHaveBeenCalled();
  });
  it("passes buttonLocale fr on a French page and omits it otherwise", async () => {
    const french = googleHarness();
    await walletFactories(french.sdk as never, eligible).Googlepay({ ...french.options, buttonLocale: "fr" }).render(document.createElement("div"));
    expect(french.client.createButton).toHaveBeenCalledWith(expect.objectContaining({ buttonLocale: "fr" }));
    const english = googleHarness();
    await walletFactories(english.sdk as never, eligible).Googlepay(english.options).render(document.createElement("div"));
    expect(english.client.createButton.mock.calls[0][0].buttonLocale).toBeUndefined();
  });
});
describe("Google Pay confirmation and 3DS", () => {
  it("confirms the order before server approval and prevents duplicate clicks", async () => {
    const h = googleHarness(); const wallet = walletFactories(h.sdk as never, eligible).Googlepay(h.options);
    await wallet.render(document.createElement("div")); h.click(); h.click();
    await vi.waitFor(() => expect(h.options.onApprove).toHaveBeenCalledOnce());
    expect(h.client.loadPaymentData).toHaveBeenCalledOnce();
    expect(h.client.loadPaymentData).toHaveBeenCalledWith(expect.objectContaining({ transactionInfo: expect.objectContaining({ totalPrice: "12.50", currencyCode: "EUR" }) }));
    expect(h.session.confirmOrder).toHaveBeenCalledWith({ orderId: "ORDER", paymentMethodData: {} });
  });
  it("keeps v6 as soon as the Google sheet starts, before payment authorization", async () => {
    resetPayPalJsVersionForTests();
    notePayPalJsFeatures({ paypal_js_v6: true });
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const h = googleHarness();
    h.client.loadPaymentData.mockImplementation(() => new Promise(() => {}));
    await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div"));
    h.click();
    reportPayPalV6LoadFailure(new Error("another instance failed"));
    expect(currentPayPalJsVersion()).toBe("v6");
    expect(h.options.createOrder).not.toHaveBeenCalled();
  });
  it("waits until the native sheet closes to start 3DS; rejection forbids approval", async () => {
    const h = googleHarness("PAYER_ACTION_REQUIRED");
    h.client.loadPaymentData.mockImplementation(async () => {
      expect(await h.authorize()).toEqual({ transactionState: "SUCCESS" });
      expect(h.session.initiatePayerAction).not.toHaveBeenCalled();
      return {};
    });
    h.session.initiatePayerAction.mockRejectedValue(new Error("cancelled"));
    await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div")); h.click();
    await vi.waitFor(() => expect(h.options.onError).toHaveBeenCalledOnce());
    expect(h.options.onApprove).not.toHaveBeenCalled();
  });
  it("allows approval only after successful 3DS", async () => {
    const h = googleHarness("PAYER_ACTION_REQUIRED");
    await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div")); h.click();
    await vi.waitFor(() => expect(h.options.onApprove).toHaveBeenCalledOnce());
    expect(h.session.initiatePayerAction).toHaveBeenCalledWith({ orderId: "ORDER" });
  });
  it("native cancellation creates no order and closed wallets cannot approve", async () => {
    const h = googleHarness(); h.client.loadPaymentData.mockRejectedValue(new Error("cancelled"));
    const wallet = walletFactories(h.sdk as never, eligible).Googlepay(h.options);
    await wallet.render(document.createElement("div")); h.click();
    await vi.waitFor(() => expect(h.options.onError).toHaveBeenCalledOnce());
    expect(h.options.createOrder).not.toHaveBeenCalled();
    await wallet.close!(); h.click(); expect(h.client.loadPaymentData).toHaveBeenCalledOnce();
  });
  it("an incomplete PayPal confirmation never invokes server approval", async () => {
    const h = googleHarness("CREATED");
    await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div")); h.click();
    await vi.waitFor(() => expect(h.session.confirmOrder).toHaveBeenCalledOnce());
    await new Promise(r => setTimeout(r, 0)); expect(h.options.onApprove).not.toHaveBeenCalled();
  });
});

it("Apple Pay validates the merchant before confirming and closes its native session", async () => {
  resetPayPalJsVersionForTests();
  notePayPalJsFeatures({ paypal_js_v6: true });
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const native = { begin: vi.fn(), abort: vi.fn(), completeMerchantValidation: vi.fn(), completePayment: vi.fn() } as any;
  const Apple = Object.assign(vi.fn(function () { return native; }), { canMakePayments: () => true, STATUS_SUCCESS: 1, STATUS_FAILURE: 0 });
  vi.stubGlobal("ApplePaySession", Apple);
  const session = { formatConfigForPaymentRequest: () => details.config, validateMerchant: vi.fn().mockResolvedValue({ merchantSession: {} }), confirmOrder: vi.fn().mockResolvedValue({ approveApplePayPayment: { status: "APPROVED", id: "APPLE-ORDER" } }) };
  const options = { amount: "5.00", currencyCode: "EUR", createOrder: vi.fn().mockResolvedValue("APPLE-ORDER"), onApprove: vi.fn().mockResolvedValue(undefined) };
  const wallet = walletFactories({ createApplePayOneTimePaymentSession: () => session } as never, eligible).Applepay(options);
  const host = document.createElement("div"); const rendering = wallet.render(host);
  document.querySelector<HTMLScriptElement>('script[src*="applepay"]')!.dispatchEvent(new Event("load"));
  await rendering; host.firstElementChild!.dispatchEvent(new MouseEvent("click"));
  expect(native.begin).toHaveBeenCalledOnce();
  reportPayPalV6LoadFailure(new Error("another instance failed"));
  expect(currentPayPalJsVersion()).toBe("v6");
  expect(options.createOrder).not.toHaveBeenCalled();
  native.onvalidatemerchant({ validationURL: "https://apple-pay-gateway.apple.com/paymentservices/startSession" });
  await vi.waitFor(() => expect(native.completeMerchantValidation).toHaveBeenCalledOnce());
  native.onpaymentauthorized({ payment: { token: {}, billingContact: {} } });
  await vi.waitFor(() => expect(options.onApprove).toHaveBeenCalledOnce());
  expect(session.confirmOrder).toHaveBeenCalledWith({ orderId: "APPLE-ORDER", token: {}, billingContact: {} });
  await wallet.close!(); expect(host.children).toHaveLength(0);
});

it("deduplicates repeated native authorization callbacks within one Google sheet", async () => {
  const h = googleHarness();
  h.client.loadPaymentData.mockImplementation(async () => { await Promise.all([h.authorize(), h.authorize()]); return {}; });
  await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div")); h.click();
  await vi.waitFor(() => expect(h.options.onApprove).toHaveBeenCalledOnce());
  expect(h.options.createOrder).toHaveBeenCalledOnce();
  expect(h.session.confirmOrder).toHaveBeenCalledOnce();
});

it("rejects a wallet confirmation for a different PayPal order", async () => {
  const h = googleHarness(); h.session.confirmOrder.mockResolvedValue({ status: "APPROVED", id: "OTHER-ORDER" });
  await walletFactories(h.sdk as never, eligible).Googlepay(h.options).render(document.createElement("div")); h.click();
  await vi.waitFor(() => expect(h.session.confirmOrder).toHaveBeenCalledOnce());
  await new Promise(r => setTimeout(r, 0)); expect(h.options.onApprove).not.toHaveBeenCalled();
});
