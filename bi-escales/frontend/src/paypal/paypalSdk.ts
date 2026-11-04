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

export function payLaterEligible(amountEur: string, kind?: string): boolean {
  const pledgeKind = (kind || "").trim();
  if (pledgeKind && pledgeKind !== "project_pledge") {
    return false;
  }
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
  const src = paypalSubscriptionSdkUrl(trimmed);
  const loaded = findPayPalScript(src);
  if (loaded?.dataset.loaded === "1") {
    return Promise.resolve();
  }
  return loadScript(src);
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
