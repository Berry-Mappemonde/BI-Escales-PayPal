import { resumeCheckout } from "./checkoutAttempts";
import { walletFactories } from "./paypalWallets";
import type { CardFieldComponent, CardFieldOptions, Components, PaymentFlow, EligiblePaymentMethodsOutput, PayPalV6Namespace, SdkInstance } from "@paypal/paypal-js/sdk-v6";

/**
 * PayPal Web SDK v6 sandbox adapter for BI Escales.
 *
 * A single v6 core script replaces all legacy v5 URLs. The existing React
 * checkout components receive narrow button/card interfaces, while the SDK
 * uses createInstance, eligibility checks and payment sessions internally.
 * No live environment, merchant secret or PayPal money path is exposed here.
 */
export interface PayPalSdkButtonInstance {
  render: (el: HTMLElement | string) => Promise<void>;
  close?: () => Promise<void>;
}

type Callback = (...args: any[]) => any;
type ButtonCallbacks = {
  createOrder?: Callback;
  createVaultSetupToken?: Callback;
  createSubscription?: Callback;
  onApprove?: Callback;
  onCancel?: Callback;
  onError?: Callback;
  style?: { label?: string };
  offerPayLater?: boolean;
  subscriptionPlanId?: string;
};

type CardCallbacks = {
  createOrder?: Callback;
  createVaultSetupToken?: Callback;
  onApprove?: Callback;
  onError?: Callback;
};

type V6Instance = Pick<SdkInstance<Components[]>,
  "findEligibleMethods" | "createPayPalOneTimePaymentSession" |
  "createPayPalSavePaymentSession" | "createPayPalSubscriptionPaymentSession" |
  "createCardFieldsOneTimePaymentSession" | "createCardFieldsSavePaymentSession" |
  "createPayPalMessages" | "createPayLaterOneTimePaymentSession" | "createGooglePayOneTimePaymentSession" |
  "createApplePayOneTimePaymentSession">;
type V6Core = Pick<PayPalV6Namespace, "createInstance">;

declare global {
  interface Window {
    paypal?: V6Core | PayPalNamespace;
  }
}

export interface PayPalNamespace {
  Buttons?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
  CardFields?: (config: Record<string, unknown>) => Record<string, unknown>;
  Messages?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
  Googlepay?: (config?: Record<string, unknown>) => unknown;
  Applepay?: (config?: Record<string, unknown>) => unknown;
}

const V6_URL = "https://www.sandbox.paypal.com/web-sdk/v6/core";
const SCRIPT_SELECTOR = 'script[data-paypal-web-sdk="v6"]';
const PAY_LATER_MIN = 30;
const instances = new Map<string, Promise<PayPalNamespace>>();
let corePending: Promise<V6Core> | null = null;

export type SdkIntent = "authorize" | "capture";

export function paypalLocale(appLang?: string): string {
  return String(appLang || "fr").trim().toLowerCase().startsWith("en") ? "en_US" : "fr_FR";
}

/** All payment methods share the one v6 core script, never mixed with v5. */
export function paypalSdkUrl(
  _clientId: string,
  _appLang?: string,
  _intent: SdkIntent = "authorize",
  _walletPay = false,
  _currency = "EUR",
): string {
  return V6_URL;
}
export function paypalCardFieldsSdkUrl(_clientId: string, _appLang?: string): string {
  return V6_URL;
}
export function paypalWalletPaySdkUrl(_clientId: string, _appLang?: string, _intent: SdkIntent = "authorize"): string {
  return V6_URL;
}
export function paypalSubscriptionSdkUrl(_clientId: string, _appLang?: string): string {
  return V6_URL;
}
export function paypalNamespaceFor(_src: string): string {
  return "paypalWebSdkV6";
}
export function getPayPalNamespace(_src: string): PayPalNamespace | null {
  return null; // Instances are keyed by merchant and locale; never read a legacy global.
}
export function payLaterEligible(amountEur: string, kind?: string): boolean {
  if (kind && kind.trim() !== "project_pledge") return false;
  const value = Number.parseFloat(amountEur.replace(",", ".").trim());
  return Number.isFinite(value) && value >= PAY_LATER_MIN;
}

function waitForCore(): Promise<V6Core> {
  // Detect coexisting legacy SDKs before returning even a cached v6 instance.
  if (document.querySelector('script[src*="/sdk/js?"]')) {
    return Promise.reject(new Error("PayPal Web SDK v6 cannot coexist with v5"));
  }
  if ((window.paypal as V6Core | undefined)?.createInstance) return Promise.resolve(window.paypal as V6Core);
  if (corePending) return corePending;
  corePending = new Promise<V6Core>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR);
    const script = existing ?? document.createElement("script");
    const onLoad = () => {
      if ((window.paypal as V6Core | undefined)?.createInstance) resolve(window.paypal as V6Core);
      else reject(new Error("PayPal Web SDK v6 createInstance unavailable"));
    };
    const onError = () => reject(new Error("PayPal Web SDK v6 failed to load"));
    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    if (!existing) {
      script.src = V6_URL;
      script.async = true;
      script.dataset.paypalWebSdk = "v6";
      document.body.appendChild(script);
    }
  }).catch((error: unknown) => {
    corePending = null;
    document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR)?.remove();
    throw error;
  });
  return corePending;
}

const subscriptionRequests = new Map<string, Promise<string>>();
const subscriptionResumes = new Map<string, Promise<void>>();
async function createSubscriptionOnServer(appLang: string | undefined, selection: unknown): Promise<string> {
  const plan = (selection as { plan_id?: unknown } | null)?.plan_id;
  if (typeof plan !== "string" || !plan.trim()) throw new Error("Displayed subscription plan missing");
  const scope = `escales-v6-subscription:${location.pathname}:${appLang || "fr"}:${plan}`;
  const existing = subscriptionRequests.get(scope);
  if (existing) return existing;
  let key: string;
  try { key = sessionStorage.getItem(scope) || crypto.randomUUID(); sessionStorage.setItem(scope, key); }
  catch { throw new Error("Subscription retry storage unavailable"); }
  const pending = postSubscription(appLang, plan, key).then(id => { sessionStorage.setItem(scope + ":subscriptionId", id); return id; });
  subscriptionRequests.set(scope, pending);
  try { return await pending; } catch (error) { subscriptionRequests.delete(scope); throw error; }
}
function finishSubscription(appLang: string | undefined, plan: string, id: string | undefined, key: string | undefined) {
  const scope = `escales-v6-subscription:${location.pathname}:${appLang || "fr"}:${plan}`;
  if (!id || !key || sessionStorage.getItem(scope) !== key || sessionStorage.getItem(scope + ":subscriptionId") !== id) return;
  subscriptionRequests.delete(scope); sessionStorage.removeItem(scope); sessionStorage.removeItem(scope + ":subscriptionId");
}
async function postSubscription(appLang: string | undefined, plan: string, key: string): Promise<string> {
  const base = String(import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  const current = window.location.origin + (window.location.pathname || "/");
  const response = await fetch(base + "/api/escales/paypal/subscriptions/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PayPal-Request-Id": key,
    },
    body: JSON.stringify({
      lang: appLang?.startsWith("en") ? "en" : "fr",
      plan_id: plan,
      return_url: current + "?sub=return",
      cancel_url: current + "?sub=cancel",
    }),
  });
  if (!response.ok) throw new Error("PayPal subscription creation failed");
  const data = await response.json() as { subscription_id?: string; plan_id?: string };
  if (data.plan_id !== plan) throw new Error("Subscription plan does not match the displayed selection");
  if (!data.subscription_id) throw new Error("PayPal subscription ID missing");
  return data.subscription_id;
}

export function buildV6Adapter(
  sdk: V6Instance,
  eligible: Pick<EligiblePaymentMethodsOutput, "isEligible"> & Partial<Pick<EligiblePaymentMethodsOutput, "getDetails">>,
  walletPay = false,
  intent: SdkIntent = "authorize",
  appLang?: string,
): PayPalNamespace {
  return {
    ...(walletPay && eligible.getDetails ? walletFactories(sdk, eligible as EligiblePaymentMethodsOutput) : {}),
    ...(sdk.createPayPalMessages ? { Messages: (options: Record<string, unknown>): PayPalSdkButtonInstance => {
      const currencyCode = String(options.currencyCode || "EUR");
      sdk.createPayPalMessages!({ currencyCode });
      let message: HTMLElement | null = null;
      return {
        render: async target => {
          const host = typeof target === "string" ? document.querySelector<HTMLElement>(target) : target;
          if (!host) throw new Error("PayPal message host missing");
          const element = document.createElement("paypal-message");
          element.amount = String(options.amount || "");
          element.currencyCode = currencyCode;
          element.autoBootstrap = true;
          element.setAttribute("auto-bootstrap", "");
          message = element;
          host.replaceChildren(element);

        },
        close: async () => { message?.remove(); },
      };
    } } : {}),
    Buttons: (opts: Record<string, unknown>): PayPalSdkButtonInstance => {
      const config = opts as ButtonCallbacks;
      let element: HTMLElement | null = null;
      let click: EventListener | null = null;
      let closed = false;
      let starting = false;
      let payLaterElement: HTMLElement | null = null;
      let payLaterSession: ReturnType<V6Instance["createPayLaterOneTimePaymentSession"]> | null = null;
      const subscription = typeof config.createSubscription === "function";
      const vault = typeof config.createVaultSetupToken === "function";
      const callbacks = {
        onApprove: async (data: { orderId?: string; subscriptionId?: string; vaultSetupToken?: string }) => {
          if (subscription) { await config.onApprove?.({ subscriptionID: data.subscriptionId }); if (selectedPlan) finishSubscription(appLang, selectedPlan, data.subscriptionId, selectedKey); }
          else await config.onApprove?.(data);
        },
        onCancel: (...args: unknown[]) => { if (!closed) void config.onCancel?.(...args); },
        onError: (...args: unknown[]) => { if (!closed) void config.onError?.(...args); },
        // AUTHORIZE stops are not captured in browser; server approval remains authoritative.
        ...(!subscription && !vault ? { commit: intent === "capture" } : {}),
      };
      let selectedPlan = config.subscriptionPlanId || "";
      let selectedKey: string | undefined;
      let session: { destroy: () => void; hasReturned?: () => boolean; resume?: () => Promise<void> };
      let start: () => Promise<unknown>;
      const token = (value: unknown) => {
        if (typeof value !== "string" || !value.trim()) throw new Error("PayPal payment token missing");
        return value;
      };
      if (subscription) {
        const subscriptionSession = sdk.createPayPalSubscriptionPaymentSession(callbacks);
        session = subscriptionSession;
        start = () => subscriptionSession.start({ presentationMode: "auto" },
          Promise.resolve().then(() => config.createSubscription!({}, {
            subscription: { create: (body: unknown) => { selectedPlan = String((body as { plan_id?: unknown })?.plan_id || ""); return createSubscriptionOnServer(appLang, body).then(id => { selectedKey = sessionStorage.getItem(`escales-v6-subscription:${location.pathname}:${appLang || "fr"}:${selectedPlan}`) || undefined; return id; }); } },
          })).then(value => ({ subscriptionId: token(value) })));
      } else if (vault) {
        const saveSession = sdk.createPayPalSavePaymentSession(callbacks);
        session = saveSession;
        start = () => saveSession.start({ presentationMode: "auto" },
          Promise.resolve().then(() => config.createVaultSetupToken!()).then(value => ({ vaultSetupToken: token(value) })));
      } else {
        const orderSession = sdk.createPayPalOneTimePaymentSession(callbacks);
        session = orderSession;
        start = () => orderSession.start({ presentationMode: "auto" },
          Promise.resolve().then(() => config.createOrder?.()).then(value => ({ orderId: token(value) })));
      }
      return {
        render: async (target) => {
          const host = typeof target === "string" ? document.querySelector<HTMLElement>(target) : target;
          if (closed) throw new Error("PayPal button session closed");
          if (!subscription) await resumeCheckout(session, vault);
          else if (selectedPlan && session.hasReturned?.() && session.resume) {
            const scope = `escales-v6-subscription:${location.pathname}:${appLang || "fr"}:${selectedPlan}`;
            const key = sessionStorage.getItem(scope);
            if (key) {
              selectedKey = key;
              let pending = subscriptionResumes.get(key);
              if (!pending) { pending = session.resume().catch(error => { subscriptionResumes.delete(key); throw error; }); subscriptionResumes.set(key, pending); }
              await pending;
            }
          }
          if (!host) throw new Error("PayPal button host missing");
          if (!eligible.isEligible("paypal")) throw new Error("PayPal not eligible for this checkout");
          element = document.createElement("paypal-button");
          element.setAttribute("type", subscription ? "subscribe" : config.style?.label === "donate" ? "pay" : "pay");
          element.classList.add("paypal-gold");
          click = () => {
            if (closed || starting) return;
            starting = true;
            // Call start synchronously to retain the browser user gesture.
            void start().catch((error: unknown) => { if (!closed) void config.onError?.(error); })
              .finally(() => { starting = false; });
          };
          element.addEventListener("click", click);
          host.replaceChildren(element);
          if (!subscription && !vault && config.offerPayLater && eligible.isEligible("paylater") && eligible.getDetails) {
            const details = eligible.getDetails("paylater");
            payLaterSession = sdk.createPayLaterOneTimePaymentSession(callbacks);
            const payLater = payLaterSession;
            const button = document.createElement("paypal-pay-later-button");
            button.countryCode = details.countryCode;
            button.productCode = details.productCode;
            button.onclick = () => {
              if (closed || starting) return;
              starting = true;
              void payLater.start({ presentationMode: "auto" }, Promise.resolve().then(() => config.createOrder?.()).then(value => ({ orderId: token(value) })))
                .catch(error => { if (!closed) void config.onError?.(error); }).finally(() => { starting = false; });
            };
            payLaterElement = button;
            host.appendChild(button);
          }
        },
        close: async () => {
          if (closed) return;
          closed = true;
          if (element && click) element.removeEventListener("click", click);
          element?.remove();
          if (payLaterElement) payLaterElement.onclick = null;
          payLaterElement?.remove();
          payLaterSession?.destroy();
          session.destroy();
        },
      };
    },
    CardFields: (opts: Record<string, unknown>) => {
      const config = opts as CardCallbacks;
      const vault = typeof config.createVaultSetupToken === "function";
      const session = vault
        ? sdk.createCardFieldsSavePaymentSession()
        : sdk.createCardFieldsOneTimePaymentSession();
      const fields = new Set<CardFieldComponent>();
      let disposed = false;
      let submitting = false;
      const mountField = (type: CardFieldOptions["type"]) => () => {
        let field: CardFieldComponent | null = null;
        return {
          render: async (host: HTMLElement) => {
            if (disposed) throw new Error("PayPal card session closed");
            field = session.createCardFieldsComponent({ type });
            fields.add(field);
            host.appendChild(field);
          },
          close: async () => {
            if (!field) return;
            fields.delete(field);
            field.destroy(); field = null;
            if (fields.size === 0 && !disposed) { disposed = true; session.destroy(); }
          },
        };
      };
      return {
        isEligible: () => eligible.isEligible("advanced_cards"),
        NumberField: mountField("number"),
        ExpiryField: mountField("expiry"),
        CVVField: mountField("cvv"),
        NameField: mountField("name"),
        submit: async () => {
          if (disposed || submitting) throw new Error("PayPal card session unavailable");
          submitting = true;
          try {
            // The card entry is held in PayPal-hosted iframes; raw PAN/CVV never touches our code.
            const token = vault ? await config.createVaultSetupToken?.() : await config.createOrder?.();
            if (!token || typeof token !== "string") throw new Error("PayPal order or vault token missing");
            if (disposed) throw new Error("PayPal card session closed");
            const result = await session.submit(token);
            if (disposed) throw new Error("PayPal card session closed");
            if (result.state !== "succeeded") throw new Error(result.data?.message || "Card confirmation was not completed");
            const confirmedToken = "orderId" in result.data ? result.data.orderId : result.data.vaultSetupToken;
            if (confirmedToken !== token) throw new Error("PayPal confirmation token mismatch");
            await config.onApprove?.(result.data);
          } finally { submitting = false; }
        },
      };
    },
  };
}

function loadConfigured(clientId: string, appLang: string | undefined, currency: string, walletPay: boolean, paymentFlow: PaymentFlow = "ONE_TIME_PAYMENT", intent: SdkIntent = "authorize", amount?: string): Promise<PayPalNamespace> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  let normalizedAmount: string | undefined;
  try { normalizedAmount = amount !== undefined && paymentFlow === "ONE_TIME_PAYMENT" ? normalizeEligibilityAmount(amount) : undefined; }
  catch (error) { return Promise.reject(error); }
  const key = [trimmed, paypalLocale(appLang), currency.toUpperCase(), walletPay, paymentFlow, intent, normalizedAmount].join("|");
  const existing = instances.get(key);
  if (existing) return existing;
  const promise = waitForCore().then(async (core) => {
    const sdk = await core.createInstance({
      clientId: trimmed,
      locale: paypalLocale(appLang).replace("_", "-"),
      pageType: "checkout",
      components: [
        "paypal-payments",
        "paypal-subscriptions",
        "paypal-messages",
        "card-fields",
        ...(walletPay ? ["googlepay-payments", "applepay-payments"] as const : []),
      ],
    });
    const eligible = await sdk.findEligibleMethods({ currencyCode: currency.toUpperCase(), paymentFlow, ...(normalizedAmount ? { amount: normalizedAmount } : {}) });
    return buildV6Adapter(sdk, eligible, walletPay, intent, appLang);
  }).catch((error: unknown) => {
    instances.delete(key);
    throw error;
  });
  instances.set(key, promise);
  return promise;
}

export function loadPayPalSdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
  walletPay = false,
  currency = "EUR",
  paymentFlow: PaymentFlow = "ONE_TIME_PAYMENT",
  amount?: string,
): Promise<PayPalNamespace> {
  return loadConfigured(clientId, appLang, currency, walletPay, paymentFlow, intent, amount);
}
export function loadPayPalWalletPaySdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
): Promise<PayPalNamespace> {
  return loadConfigured(clientId, appLang, "EUR", true, "ONE_TIME_PAYMENT", intent);
}
export function loadPayPalSubscriptionSdk(clientId: string, appLang?: string): Promise<PayPalNamespace> {
  return loadConfigured(clientId, appLang, "EUR", false, "RECURRING_PAYMENT");
}
export function loadNamespacedSdk(_src: string): Promise<PayPalNamespace> {
  return Promise.reject(new Error("Use loadPayPalSdk with client ID for PayPal Web SDK v6"));
}

export async function safePayPalRender(
  factory: unknown,
  config: Record<string, unknown> | undefined,
  el: HTMLElement | string,
): Promise<{ ok: boolean; instance: PayPalSdkButtonInstance | null; error?: unknown }> {
  if (typeof factory !== "function") return { ok: false, instance: null };
  let instance: unknown;
  try { instance = (factory as (c?: Record<string, unknown>) => unknown)(config); }
  catch (error) { return { ok: false, instance: null, error }; }
  if (typeof (instance as { render?: unknown } | null)?.render !== "function") return { ok: false, instance: null };
  const typed = instance as PayPalSdkButtonInstance;
  try { await typed.render(el); return { ok: true, instance: typed }; }
  catch (error) { return { ok: false, instance: typed, error }; }
}
export function safePayPalClose(instance: PayPalSdkButtonInstance | null | undefined): void {
  try {
    if (typeof instance?.close === "function") void Promise.resolve(instance.close()).catch(() => undefined);
  } catch { /* unmounted */ }
}

function normalizeEligibilityAmount(raw: string): string {
  const normalized = raw.trim().replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized) || !Number.isFinite(Number(normalized)) || Number(normalized) <= 0) throw new Error("Eligibility amount invalid");
  return Number(normalized).toFixed(2);
}
