/** Load PayPal JS SDK (sandbox). Venmo is omitted — USD-only, not eligible for EUR Escales. */

declare global {
  interface Window {
    paypal?: {
      Buttons?: (config: Record<string, unknown>) => { render: (el: HTMLElement) => Promise<void> };
      Messages?: (config: Record<string, unknown>) => { render: (el: HTMLElement) => Promise<void> };
    };
  }
}

const PAY_LATER_MIN = 30;

export function paypalSdkUrl(clientId: string): string {
  const params = new URLSearchParams({
    "client-id": clientId,
    components: "buttons,messages",
    intent: "authorize",
    currency: "EUR",
    vault: "true",
    "disable-funding": "venmo",
    "enable-funding": "paylater",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function paypalSubscriptionSdkUrl(clientId: string): string {
  const params = new URLSearchParams({
    "client-id": clientId,
    components: "buttons",
    intent: "subscription",
    vault: "true",
    currency: "EUR",
    "disable-funding": "venmo",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function payLaterEligible(amountEur: string): boolean {
  const normalized = amountEur.replace(",", ".").trim();
  const value = Number.parseFloat(normalized);
  return Number.isFinite(value) && value >= PAY_LATER_MIN;
}

export function loadPayPalSdk(clientId: string): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  if (window.paypal?.Buttons) return Promise.resolve();
  return loadScript(paypalSdkUrl(trimmed));
}

export function loadPayPalSubscriptionSdk(clientId: string): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  return loadScript(paypalSubscriptionSdkUrl(trimmed));
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-paypal-sdk-src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("PayPal SDK failed to load")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.paypalSdkSrc = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("PayPal SDK failed to load"));
    document.body.appendChild(script);
  });
}
