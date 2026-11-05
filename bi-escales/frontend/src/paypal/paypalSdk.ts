/** Load PayPal JS SDK (sandbox). Venmo is omitted — USD-only, not eligible for EUR Escales. */

/**
 * One PayPal JS SDK global. Each distinct SDK URL (intent, locale, components) is loaded
 * once under its own `data-namespace`, so the Crew subscription SDK (intent=subscription)
 * and the stopover/project checkout SDKs (intent=authorize|capture) coexist on one page.
 * Nothing is ever torn down: removing a live SDK makes zoid throw
 * "zoid destroyed all components" and a second un-namespaced load throws
 * "Can not register multiple components with the same tag: paypal-buttons".
 */
export interface PayPalNamespace {
  Buttons?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
  Messages?: (config: Record<string, unknown>) => { render?: (el: HTMLElement) => Promise<void> };
  Googlepay?: (config?: Record<string, unknown>) => unknown;
  Applepay?: (config?: Record<string, unknown>) => unknown;
  CardFields?: (config: Record<string, unknown>) => Record<string, unknown>;
}

declare global {
  interface Window {
    /** Legacy un-namespaced global. The app no longer sets or reads it. */
    paypal?: PayPalNamespace;
  }
}

/** PayPal JS SDK v6 button-like components (Smart Buttons, Google Pay, Apple Pay). */
export interface PayPalSdkButtonInstance {
  render: (el: HTMLElement) => Promise<void>;
  close?: () => Promise<void>;
}

const PAY_LATER_MIN = 30;

export function paypalLocale(appLang?: string): string {
  const raw = String(appLang || "fr").trim().toLowerCase();
  if (raw.startsWith("en")) return "en_US";
  return "fr_FR";
}

function sdkParams(clientId: string, locale: string, extra: Record<string, string>): URLSearchParams {
  return new URLSearchParams({
    "client-id": clientId,
    locale,
    ...extra,
  });
}

export type SdkIntent = "authorize" | "capture";

export function paypalSdkUrl(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
  walletPay = false,
): string {
  const components = walletPay
    ? "buttons,card-fields,messages,applepay,googlepay"
    : "buttons,card-fields,messages";
  const params = sdkParams(clientId, paypalLocale(appLang), {
    components,
    intent,
    currency: "EUR",
    vault: "true",
    "disable-funding": "venmo",
    "enable-funding": "paylater",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

/** Card Fields + wallet buttons when the matching ESCALES_* flags are on (paypalSdk.ts pattern). */
export function paypalCardFieldsSdkUrl(clientId: string, appLang?: string): string {
  const params = sdkParams(clientId, paypalLocale(appLang), {
    components: "card-fields,buttons,messages",
    intent: "authorize",
    currency: "EUR",
    vault: "true",
    "disable-funding": "venmo",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function paypalWalletPaySdkUrl(clientId: string, appLang?: string, intent: SdkIntent = "authorize"): string {
  const params = sdkParams(clientId, paypalLocale(appLang), {
    components: "applepay,googlepay,buttons,messages",
    intent,
    currency: "EUR",
    vault: "true",
    "disable-funding": "venmo",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function paypalSubscriptionSdkUrl(clientId: string, appLang?: string): string {
  const params = sdkParams(clientId, paypalLocale(appLang), {
    components: "buttons",
    intent: "subscription",
    vault: "true",
    currency: "EUR",
    "disable-funding": "venmo",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function payLaterEligible(amountEur: string, kind?: string): boolean {
  const pledgeKind = (kind || "").trim();
  if (pledgeKind && pledgeKind !== "project_pledge") {
    return false;
  }
  const normalized = amountEur.replace(",", ".").trim();
  const value = Number.parseFloat(normalized);
  return Number.isFinite(value) && value >= PAY_LATER_MIN;
}

/** Short stable hash so each SDK URL maps to one JS identifier. */
function hashSrc(src: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < src.length; i += 1) {
    h ^= src.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

/** `data-namespace` for one SDK URL; subscription and checkout SDKs never share a global. */
export function paypalNamespaceFor(src: string): string {
  const prefix = src.includes("intent=subscription") ? "paypalSubscriptions" : "paypalCheckout";
  return `${prefix}_${hashSrc(src)}`;
}

/** The loaded SDK object for `src`, or null when it is not (yet) on the page. */
export function getPayPalNamespace(src: string): PayPalNamespace | null {
  const value = (window as unknown as Record<string, unknown>)[paypalNamespaceFor(src)];
  return value && typeof value === "object" ? (value as PayPalNamespace) : null;
}

const pending = new Map<string, Promise<PayPalNamespace>>();

async function waitForButtons(src: string, timeoutMs = 8000): Promise<PayPalNamespace> {
  const start = Date.now();
  for (;;) {
    const ns = getPayPalNamespace(src);
    if (ns && typeof ns.Buttons === "function") return ns;
    if (Date.now() - start >= timeoutMs) throw new Error("PayPal Buttons unavailable after SDK load");
    await new Promise((r) => setTimeout(r, 50));
  }
}

function findPayPalScript(src: string): HTMLScriptElement | null {
  for (const node of document.querySelectorAll("script[data-paypal-sdk-src]")) {
    const script = node as HTMLScriptElement;
    if (script.dataset.paypalSdkSrc === src) return script;
  }
  return null;
}

function injectScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = findPayPalScript(src);
    if (existing) {
      if (existing.dataset.loaded === "1") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("PayPal SDK failed to load")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.paypalSdkSrc = src;
    script.setAttribute("data-namespace", paypalNamespaceFor(src));
    script.onload = () => {
      script.dataset.loaded = "1";
      resolve();
    };
    script.onerror = () => {
      script.remove();
      reject(new Error("PayPal SDK failed to load"));
    };
    document.body.appendChild(script);
  });
}

/** Load (once) the SDK at `src` under its own namespace and resolve with that namespace. */
export function loadNamespacedSdk(src: string): Promise<PayPalNamespace> {
  const ready = getPayPalNamespace(src);
  if (ready && typeof ready.Buttons === "function") return Promise.resolve(ready);
  const inFlight = pending.get(src);
  if (inFlight && findPayPalScript(src)) return inFlight;
  pending.delete(src);
  const promise = injectScript(src)
    .then(() => waitForButtons(src))
    .catch((err: unknown) => {
      pending.delete(src);
      throw err instanceof Error ? err : new Error(String(err));
    });
  pending.set(src, promise);
  return promise;
}

/** Checkout SDK for stopover / project / marina pledges (intent authorize or capture). */
export function loadPayPalSdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
  walletPay = false,
): Promise<PayPalNamespace> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  return loadNamespacedSdk(paypalSdkUrl(trimmed, appLang, intent, walletPay));
}

export function loadPayPalWalletPaySdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
): Promise<PayPalNamespace> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  return loadNamespacedSdk(paypalWalletPaySdkUrl(trimmed, appLang, intent));
}

/**
 * Crew supporter subscription SDK (intent=subscription). Lives in its own
 * `paypalSubscriptions_*` namespace so it never collides with a stopover checkout SDK.
 * EN↔FR loads the other locale once and keeps both; nothing is removed.
 */
export function loadPayPalSubscriptionSdk(clientId: string, appLang?: string): Promise<PayPalNamespace> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  return loadNamespacedSdk(paypalSubscriptionSdkUrl(trimmed, appLang));
}

/**
 * Call a PayPal SDK factory and render the result into `el` without ever throwing.
 * Resolves true only when the component exposed a `render` function and it resolved.
 * (e.g. `Googlepay()` returns a config object with no `render`: that is a no-op, not a crash.)
 */
export async function safePayPalRender(
  factory: unknown,
  config: Record<string, unknown> | undefined,
  el: HTMLElement | string,
): Promise<{ ok: boolean; instance: PayPalSdkButtonInstance | null; error?: unknown }> {
  if (typeof factory !== "function") return { ok: false, instance: null };
  let instance: unknown;
  try {
    instance = (factory as (c?: Record<string, unknown>) => unknown)(config);
  } catch (error) {
    return { ok: false, instance: null, error };
  }
  const render = (instance as { render?: unknown } | null)?.render;
  if (typeof render !== "function") return { ok: false, instance: null };
  const typed = instance as PayPalSdkButtonInstance;
  try {
    await render.call(instance, el);
    return { ok: true, instance: typed };
  } catch (error) {
    return { ok: false, instance: typed, error };
  }
}

/** Close a PayPal component instance if it supports it; never throws. */
export function safePayPalClose(instance: PayPalSdkButtonInstance | null | undefined): void {
  try {
    const close = instance?.close;
    if (typeof close === "function") void Promise.resolve(close.call(instance)).catch(() => undefined);
  } catch {
    /* already destroyed */
  }
}
