import type { CardFieldComponent, CardFieldOptions, Components, PaymentFlow } from "@paypal/paypal-js/sdk-v6";

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
};

type CardCallbacks = {
  createOrder?: Callback;
  createVaultSetupToken?: Callback;
  onApprove?: Callback;
  onError?: Callback;
};

type V6Session = {
  destroy?: () => void;
  start: (options: { presentationMode: "auto" }, order: Promise<Record<string, string>>) => Promise<void>;
};
type V6CardSession = {
  createCardFieldsComponent: (options: CardFieldOptions) => CardFieldComponent;
  submit: (id: string) => Promise<{ state: string; data?: { message?: string } }>;
};
type V6Instance = {
  findEligibleMethods: (options: { currencyCode: string; paymentFlow?: PaymentFlow }) => Promise<{
    isEligible: (method: string) => boolean;
  }>;
  createPayPalOneTimePaymentSession: (callbacks: Record<string, unknown>) => V6Session;
  createPayPalSavePaymentSession: (callbacks: Record<string, unknown>) => V6Session;
  createPayPalSubscriptionPaymentSession: (callbacks: Record<string, unknown>) => V6Session;
  createCardFieldsOneTimePaymentSession: () => V6CardSession;
  createCardFieldsSavePaymentSession: () => V6CardSession;
};
type V6Core = {
  createInstance: (options: {
    clientId: string;
    components: Components[];
    locale: string;
    pageType: "checkout";
  }) => Promise<V6Instance>;
};

declare global {
  interface Window {
    paypal?: V6Core | PayPalNamespace;
  }
}

export interface PayPalNamespace {
  Buttons?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
  CardFields?: (config: Record<string, unknown>) => Record<string, unknown>;
  Messages?: (config: Record<string, unknown>) => { render?: (el: HTMLElement) => Promise<void> };
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

async function createSubscriptionOnServer(): Promise<string> {
  const base = String(import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  const current = window.location.origin + (window.location.pathname || "/");
  const response = await fetch(base + "/api/escales/paypal/subscriptions/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PayPal-Request-Id": crypto.randomUUID(),
    },
    body: JSON.stringify({
      return_url: current + "?sub=return",
      cancel_url: current + "?sub=cancel",
    }),
  });
  if (!response.ok) throw new Error("PayPal subscription creation failed");
  const data = await response.json() as { subscription_id?: string };
  if (!data.subscription_id) throw new Error("PayPal subscription ID missing");
  return data.subscription_id;
}

export function buildV6Adapter(
  sdk: V6Instance,
  eligible: { isEligible: (method: string) => boolean },
): PayPalNamespace {
  return {
    Buttons: (opts: Record<string, unknown>): PayPalSdkButtonInstance => {
      const config = opts as ButtonCallbacks;
      let element: HTMLElement | null = null;
      let click: EventListener | null = null;
      const subscription = typeof config.createSubscription === "function";
      const vault = typeof config.createVaultSetupToken === "function";
      const callbacks = {
        onApprove: async (data: { orderId?: string; subscriptionId?: string; vaultSetupToken?: string }) => {
          if (subscription) await config.onApprove?.({ subscriptionID: data.subscriptionId });
          else await config.onApprove?.(data);
        },
        onCancel: config.onCancel,
        onError: config.onError,
        // AUTHORIZE stops are not captured in browser; server approval remains authoritative.
        ...(!subscription && !vault ? { commit: false } : {}),
      };
      const session = subscription
        ? sdk.createPayPalSubscriptionPaymentSession(callbacks)
        : vault
          ? sdk.createPayPalSavePaymentSession(callbacks)
          : sdk.createPayPalOneTimePaymentSession(callbacks);
      return {
        render: async (target) => {
          const host = typeof target === "string" ? document.querySelector<HTMLElement>(target) : target;
          if (!host) throw new Error("PayPal button host missing");
          if (!eligible.isEligible("paypal")) throw new Error("PayPal not eligible for this checkout");
          element = document.createElement("paypal-button");
          element.setAttribute("type", subscription ? "subscribe" : config.style?.label === "donate" ? "pay" : "pay");
          element.classList.add("paypal-gold");
          click = () => {
            // Do not await the promise before session.start; browser user gesture is required.
            let token: Promise<Record<string, string>>;
            if (subscription) {
              token = createSubscriptionOnServer().then((subscriptionId) => ({ subscriptionId }));
            } else if (vault) {
              token = Promise.resolve().then(() => config.createVaultSetupToken!())
                .then((vaultSetupToken: string) => ({ vaultSetupToken }));
            } else {
              token = Promise.resolve().then(() => config.createOrder?.())
                .then((orderId: string) => ({ orderId }));
            }
            void session.start({ presentationMode: "auto" }, token)
              .catch((error: unknown) => { void config.onError?.(error); });
          };
          element.addEventListener("click", click);
          host.replaceChildren(element);
        },
        close: async () => {
          if (element && click) element.removeEventListener("click", click);
          element?.remove();
          session.destroy?.();
        },
      };
    },
    CardFields: (opts: Record<string, unknown>) => {
      const config = opts as CardCallbacks;
      const vault = typeof config.createVaultSetupToken === "function";
      const session = vault
        ? sdk.createCardFieldsSavePaymentSession()
        : sdk.createCardFieldsOneTimePaymentSession();
      const mountField = (type: CardFieldOptions["type"]) => () => {
        let field: CardFieldComponent | null = null;
        return {
          render: async (host: HTMLElement) => {
            field = session.createCardFieldsComponent({ type });
            host.appendChild(field);
          },
          close: async () => { field?.destroy(); field = null; },
        };
      };
      return {
        isEligible: () => eligible.isEligible("advanced_cards"),
        NumberField: mountField("number"),
        ExpiryField: mountField("expiry"),
        CVVField: mountField("cvv"),
        submit: async () => {
          // The card entry is held in PayPal-hosted iframes; raw PAN/CVV never touches our code.
          const token = vault ? await config.createVaultSetupToken?.() : await config.createOrder?.();
          if (!token || typeof token !== "string") throw new Error("PayPal order or vault token missing");
          const result = await session.submit(token);
          if (result.state !== "succeeded") throw new Error(result.data?.message || "Card confirmation was not completed");
          await config.onApprove?.(result.data);
        },
      };
    },
  };
}

function loadConfigured(clientId: string, appLang: string | undefined, currency: string, walletPay: boolean, paymentFlow: PaymentFlow = "ONE_TIME_PAYMENT"): Promise<PayPalNamespace> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  const key = [trimmed, paypalLocale(appLang), currency.toUpperCase(), walletPay, paymentFlow].join("|");
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
        "card-fields",
        ...(walletPay ? ["googlepay-payments", "applepay-payments"] as const : []),
      ],
    });
    const eligible = await sdk.findEligibleMethods({ currencyCode: currency.toUpperCase(), paymentFlow });
    return buildV6Adapter(sdk, eligible);
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
  _intent: SdkIntent = "authorize",
  walletPay = false,
  currency = "EUR",
): Promise<PayPalNamespace> {
  return loadConfigured(clientId, appLang, currency, walletPay);
}
export function loadPayPalWalletPaySdk(
  clientId: string,
  appLang?: string,
  _intent: SdkIntent = "authorize",
): Promise<PayPalNamespace> {
  return loadConfigured(clientId, appLang, "EUR", true);
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
