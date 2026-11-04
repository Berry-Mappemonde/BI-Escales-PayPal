/** Load PayPal JS SDK (sandbox). Venmo is omitted — USD-only, not eligible for EUR Escales. */

declare global {
  interface Window {
    paypal?: {
      Buttons?: (config: Record<string, unknown>) => { render: (el: HTMLElement) => Promise<void> };
    };
  }
}

export function paypalSdkUrl(clientId: string): string {
  const params = new URLSearchParams({
    "client-id": clientId,
    components: "buttons,card-fields,messages",
    intent: "authorize",
    currency: "EUR",
    vault: "true",
    "disable-funding": "venmo",
  });
  return `https://www.paypal.com/sdk/js?${params.toString()}`;
}

export function loadPayPalSdk(clientId: string): Promise<void> {
  const trimmed = clientId.trim();
  if (!trimmed) return Promise.reject(new Error("PayPal client id missing"));
  if (window.paypal?.Buttons) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-paypal-sdk="1"]');
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("PayPal SDK failed to load")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = paypalSdkUrl(trimmed);
    script.async = true;
    script.dataset.paypalSdk = "1";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("PayPal SDK failed to load"));
    document.body.appendChild(script);
  });
}
