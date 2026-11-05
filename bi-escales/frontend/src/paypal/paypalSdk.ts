/** Load PayPal JS SDK (sandbox). Venmo is omitted — USD-only, not eligible for EUR Escales. */

declare global {
  interface Window {
    paypal?: {
      Buttons?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
      Messages?: (config: Record<string, unknown>) => { render: (el: HTMLElement) => Promise<void> };
      Googlepay?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
      Applepay?: (config: Record<string, unknown>) => PayPalSdkButtonInstance;
      CardFields?: (config: Record<string, unknown>) => Record<string, unknown>;
    };
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

let loadedLocale: string | null = null;

function clearPayPalSdk(): void {
  loadedLocale = null;
  loadedSrc = null;
  delete window.paypal;
  for (const node of document.querySelectorAll("script[data-paypal-sdk-src]")) {
    node.remove();
  }
}

let loadedSrc: string | null = null;

export function loadPayPalSdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
  walletPay = false,
): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  const locale = paypalLocale(appLang);
  const src = paypalSdkUrl(trimmed, appLang, intent, walletPay);
  if ((loadedLocale && loadedLocale !== locale) || (loadedSrc && loadedSrc !== src)) {
    clearPayPalSdk();
  }
  if (window.paypal?.Buttons && loadedLocale === locale && loadedSrc === src) {
    return Promise.resolve();
  }
  loadedLocale = locale;
  loadedSrc = src;
  return loadScript(src);
}

export function loadPayPalWalletPaySdk(
  clientId: string,
  appLang?: string,
  intent: SdkIntent = "authorize",
): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  const locale = paypalLocale(appLang);
  const src = paypalWalletPaySdkUrl(trimmed, appLang, intent);
  if ((loadedLocale && loadedLocale !== locale) || (loadedSrc && loadedSrc !== src)) {
    clearPayPalSdk();
  }
  if (window.paypal?.Buttons && loadedLocale === locale && loadedSrc === src) {
    return Promise.resolve();
  }
  loadedLocale = locale;
  loadedSrc = src;
  return loadScript(src);
}

async function waitForPayPalButtons(timeoutMs = 8000): Promise<void> {
  if (window.paypal?.Buttons) return;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (window.paypal?.Buttons) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  // Script onload can fire before paypal global is attached; last chance.
  if (window.paypal?.Buttons) return;
  throw new Error("PayPal Buttons unavailable after SDK load");
}

export function loadPayPalSubscriptionSdk(clientId: string, appLang?: string): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  const locale = paypalLocale(appLang);
  const src = paypalSubscriptionSdkUrl(trimmed, appLang);
  // Always tear down when locale/src changes so subscription Buttons can remount (EN→FR).
  if ((loadedLocale && loadedLocale !== locale) || (loadedSrc && loadedSrc !== src)) {
    clearPayPalSdk();
  }
  const loaded = findPayPalScript(src);
  if (loaded?.dataset.loaded === "1" && loadedLocale === locale && loadedSrc === src) {
    loadedLocale = locale;
    loadedSrc = src;
    if (window.paypal?.Buttons) return Promise.resolve();
    return waitForPayPalButtons(500).catch(() => undefined);
  }
  loadedLocale = locale;
  loadedSrc = src;
  return loadScript(src).then(() => waitForPayPalButtons());
}

function findPayPalScript(src: string): HTMLScriptElement | null {
  for (const node of document.querySelectorAll("script[data-paypal-sdk-src]")) {
    const script = node as HTMLScriptElement;
    if (script.dataset.paypalSdkSrc === src) {
      return script;
    }
  }
  return null;
}

function loadScript(src: string): Promise<void> {
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
    script.onload = () => {
      script.dataset.loaded = "1";
      resolve();
    };
    script.onerror = () => reject(new Error("PayPal SDK failed to load"));
    document.body.appendChild(script);
  });
}
