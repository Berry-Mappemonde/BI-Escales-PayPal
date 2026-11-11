import type {
  ApplePayOneTimePaymentSession, GooglePayOneTimePaymentSession,
  GooglePayPaymentMethodData, EligiblePaymentMethodsOutput,
} from "@paypal/paypal-js/sdk-v6";
import type { PayPalSdkButtonInstance } from "./paypalSdkV6";

export type WalletSdk = {
  createGooglePayOneTimePaymentSession?: () => GooglePayOneTimePaymentSession;
  createApplePayOneTimePaymentSession?: () => ApplePayOneTimePaymentSession;
};
type WalletOptions = {
  amount: string;
  currencyCode: string;
  createOrder: () => Promise<string>;
  onApprove: () => Promise<void>;
  onError?: (error: Error) => void;
};
const scripts = new Map<string, Promise<void>>();
function loadNativeScript(src: string): Promise<void> {
  const cached = scripts.get(src);
  if (cached) return cached;
  const pending = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => { script.remove(); reject(new Error("Wallet SDK unavailable")); };
    document.head.appendChild(script);
  }).catch(error => { scripts.delete(src); throw error; });
  scripts.set(src, pending);
  return pending;
}
function targetHost(target: HTMLElement | string): HTMLElement {
  const host = typeof target === "string" ? document.querySelector<HTMLElement>(target) : target;
  if (!host) throw new Error("Wallet host missing");
  return host;
}
function amount(options: WalletOptions): string {
  const value = options.amount.replace(",", ".").trim();
  if (!/^\d+(\.\d{1,2})?$/.test(value) || Number(value) <= 0) throw new Error("Wallet amount invalid");
  return Number(value).toFixed(2);
}

/** Independent merchant and device checks; no payment is created during eligibility. */
export function walletFactories(sdk: WalletSdk, eligible: Pick<EligiblePaymentMethodsOutput, "isEligible" | "getDetails">) {
  return {
    Googlepay: (raw?: Record<string, unknown>): PayPalSdkButtonInstance => {
      const options = raw as WalletOptions;
      let closed = false;
      let busy = false;
      let button: HTMLElement | null = null;
      return {
        render: async target => {
          if (!eligible.isEligible("googlepay") || !sdk.createGooglePayOneTimePaymentSession) throw new Error("Google Pay not eligible");
          const price = amount(options);
          if (typeof google === "undefined" || !google.payments?.api?.PaymentsClient) {
            await loadNativeScript("https://pay.google.com/gp/p/js/pay.js");
          }
          if (closed) return;
          const session = sdk.createGooglePayOneTimePaymentSession();
          const config = session.formatConfigForPaymentRequest(eligible.getDetails("googlepay").config);
          let confirmation: { orderId: string; requiresAction: boolean } | null = null;
          let authorization: Promise<google.payments.api.PaymentAuthorizationResult> | null = null;
          const client = new google.payments.api.PaymentsClient({
            environment: "TEST",
            paymentDataCallbacks: {
              onPaymentAuthorized: data => authorization ??= (async () => {
                try {
                  if (closed) throw new Error("Wallet closed");
                  const orderId = await options.createOrder();
                  if (closed) throw new Error("Wallet closed");
                  const result = await session.confirmOrder({ orderId, paymentMethodData: data.paymentMethodData as GooglePayPaymentMethodData });
                  if (result.id !== orderId || !["APPROVED", "PAYER_ACTION_REQUIRED"].includes(result.status)) throw new Error("Wallet confirmation incomplete");
                  confirmation = { orderId, requiresAction: result.status === "PAYER_ACTION_REQUIRED" };
                  // Closing the Google sheet must precede PayPal's 3DS modal.
                  return { transactionState: "SUCCESS" };
                } catch {
                  confirmation = null;
                  return { transactionState: "ERROR", error: { intent: "PAYMENT_AUTHORIZATION", reason: "OTHER_ERROR", message: "Wallet authorization failed" } };
                }
              })(),
            },
          });
          const allowedPaymentMethods: google.payments.api.PaymentMethodSpecification[] = config.allowedPaymentMethods.map(method => {
            if (method.type !== "CARD" || method.tokenizationSpecification.type !== "PAYMENT_GATEWAY") throw new Error("Google Pay configuration unsupported");
            return { type: "CARD", parameters: { ...method.parameters, billingAddressParameters: method.parameters.billingAddressParameters ? { ...method.parameters.billingAddressParameters, format: method.parameters.billingAddressParameters.format || "MIN" } : undefined, allowedAuthMethods: [...method.parameters.allowedAuthMethods], allowedCardNetworks: [...method.parameters.allowedCardNetworks] }, tokenizationSpecification: { type: "PAYMENT_GATEWAY", parameters: { ...method.tokenizationSpecification.parameters } } };
          });
          const base = { apiVersion: config.apiVersion, apiVersionMinor: config.apiVersionMinor, allowedPaymentMethods };
          const ready = await client.isReadyToPay(base);
          if (!ready.result || closed) throw new Error("Google Pay device not ready");
          button = client.createButton({ onClick: () => {
            if (busy || closed) return;
            busy = true;
            authorization = null;
            confirmation = null;
            void (async () => {
              await client.loadPaymentData({ ...base, merchantInfo: config.merchantInfo, callbackIntents: ["PAYMENT_AUTHORIZATION"], transactionInfo: { countryCode: config.countryCode, currencyCode: options.currencyCode, totalPrice: price, totalPriceStatus: "FINAL" } });
              if (!confirmation || closed) return;
              const approved = confirmation as { orderId: string; requiresAction: boolean };
              if (approved.requiresAction) await session.initiatePayerAction({ orderId: approved.orderId });
              if (!closed) await options.onApprove();
            })().catch(() => { if (!closed) options.onError?.(new Error("Google Pay was cancelled or could not complete")); }).finally(() => { busy = false; });
          } });
          targetHost(target).replaceChildren(button);
        },
        close: async () => { closed = true; button?.remove(); },
      };
    },
    Applepay: (raw?: Record<string, unknown>): PayPalSdkButtonInstance => {
      const options = raw as WalletOptions;
      let closed = false;
      let native: ApplePaySession | null = null;
      let button: HTMLElement | null = null;
      return {
        render: async target => {
          if (!eligible.isEligible("applepay") || !sdk.createApplePayOneTimePaymentSession || typeof ApplePaySession === "undefined" || !ApplePaySession.canMakePayments()) throw new Error("Apple Pay not eligible on this device");
          const price = amount(options);
          const session = sdk.createApplePayOneTimePaymentSession();
          const config = session.formatConfigForPaymentRequest(eligible.getDetails("applepay").config);
          await loadNativeScript("https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js");
          if (closed) return;
          button = document.createElement("apple-pay-button");
          button.setAttribute("buttonstyle", "black");
          button.setAttribute("type", "donate");
          button.onclick = () => {
            if (closed || native) return;
            const sheet = new ApplePaySession(4, { ...config, countryCode: config.merchantCountry || "FR", currencyCode: options.currencyCode, requiredBillingContactFields: ["postalAddress"], total: { label: "BI Escales", amount: price, type: "final" } });
            native = sheet;
            let validated = false;
            let processing = false;
            sheet.onvalidatemerchant = event => {
              void session.validateMerchant({ validationUrl: event.validationURL, displayName: "BI Escales", domainName: window.location.hostname }).then(result => {
                if (!closed && native === sheet) { validated = true; sheet.completeMerchantValidation(result.merchantSession); }
              }).catch(() => { sheet.abort(); native = null; options.onError?.(new Error("Apple Pay merchant validation failed")); });
            };
            sheet.onpaymentmethodselected = () => sheet.completePaymentMethodSelection({ newTotal: { label: "BI Escales", amount: price, type: "final" } });
            sheet.onpaymentauthorized = event => {
              if (processing || !validated || closed || native !== sheet) return;
              processing = true;
              void (async () => {
                if (closed) return;
                const orderId = await options.createOrder();
                if (closed) return;
                const result = await session.confirmOrder({ orderId, token: event.payment.token, billingContact: event.payment.billingContact || {} });
                if (result.approveApplePayPayment.id !== orderId || result.approveApplePayPayment.status !== "APPROVED") throw new Error("Wallet confirmation incomplete");
                if (closed) return;
                await options.onApprove();
                sheet.completePayment({ status: ApplePaySession.STATUS_SUCCESS });
              })().catch(() => { if (!closed) { sheet.completePayment({ status: ApplePaySession.STATUS_FAILURE }); options.onError?.(new Error("Apple Pay authorization failed")); } }).finally(() => { native = null; });
            };
            sheet.oncancel = () => { native = null; };
            sheet.begin();
          };
          targetHost(target).replaceChildren(button);
        },
        close: async () => { closed = true; native?.abort(); native = null; if (button) button.onclick = null; button?.remove(); },
      };
    },
  };
}
