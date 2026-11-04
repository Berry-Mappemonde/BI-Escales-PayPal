export interface PayPalActions {
  order: {
    capture: () => Promise<unknown>;
  };
}

export interface PayPalButtonsConfig {
  createOrder?: () => Promise<string>;
  onApprove?: (data: { orderID: string }, actions: PayPalActions) => Promise<void>;
  onError?: (err: unknown) => void;
  onCancel?: () => void;
}

export interface PayPalButtonsInstance {
  render: (container: HTMLElement) => Promise<void>;
  close?: () => void;
}

export interface PayPalSDK {
  Buttons: (config: PayPalButtonsConfig) => PayPalButtonsInstance;
}

declare global {
  interface Window {
    paypal?: PayPalSDK;
  }
}

export function loadPayPalSdk(clientId: string, currency = "EUR"): Promise<PayPalSDK> {
  if (window.paypal) return Promise.resolve(window.paypal);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-bi-escales-paypal="1"]');
    if (existing) {
      existing.addEventListener("load", () => {
        if (window.paypal) resolve(window.paypal);
        else reject(new Error("PayPal SDK failed to load"));
      });
      return;
    }
    const script = document.createElement("script");
    script.dataset.biEscalesPaypal = "1";
    script.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=${currency}&intent=authorize&components=buttons`;
    script.async = true;
    script.onload = () => {
      if (window.paypal) resolve(window.paypal);
      else reject(new Error("PayPal SDK failed to load"));
    };
    script.onerror = () => reject(new Error("PayPal SDK script error"));
    document.body.appendChild(script);
  });
}
