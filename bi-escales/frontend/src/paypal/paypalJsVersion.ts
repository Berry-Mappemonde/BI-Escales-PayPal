/**
 * Which PayPal browser SDK this page uses: JS SDK v5 (today's Smart Buttons) or
 * Web SDK v6. The answer comes from the backend features endpoint
 * (`features.paypal_js_v6`, env ESCALES_PAYPAL_JS_V6_ENABLED, off by default).
 *
 * Rules:
 *  1. The default is v5. A PayPal button rendered on its own (a test, a page that
 *     never announces a features request) uses v5 at once, as before this flag.
 *  2. A page that requests the features anyway (App, the wishlist page) announces
 *     it with `expectPayPalJsFeatures()`. Until that answer arrives its PayPal
 *     buttons render nothing, so that none of them loads the v5 SDK before the
 *     flag is known. The wait is capped: no answer in time, or a failed request,
 *     means v5.
 *  3. One decision per page load, and v5 and v6 are never mixed: if a v5 SDK
 *     script is somehow on the page already, the page stays on v5.
 *
 * This module makes no request and stores nothing.
 */
import { useSyncExternalStore } from "react";

export type PayPalJsVersion = "v5" | "v6";

/** `features` as far as this module reads it. */
type FeatureAnswer = { paypal_js_v6?: unknown } | null | undefined;

/**
 * How long PayPal buttons wait for the features answer before using v5. On
 * escales.naviguide.fr the answer takes about half a second; the v5 pledge
 * button already waits for the same endpoint before it loads its SDK.
 */
export const PAYPAL_JS_FEATURES_TIMEOUT_MS = 4000;

/** Set by the v5 loader on every script it injects (see paypalSdk.ts `injectScript`). */
const V5_SCRIPT_SELECTOR = "script[data-paypal-sdk-src]";

let decided: PayPalJsVersion | null = null;
let waiting: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function v5ScriptOnPage(): boolean {
  return typeof document !== "undefined" && document.querySelector(V5_SCRIPT_SELECTOR) !== null;
}

function decide(next: PayPalJsVersion): void {
  if (decided !== null) return; // one decision per page load, never revisited
  decided = next;
  if (waiting !== null) clearTimeout(waiting);
  waiting = null;
  notify();
}

/**
 * A features request is on its way: PayPal buttons wait for `notePayPalJsFeatures`
 * (rule 2). Safe to call more than once; ignored once the page has decided.
 */
export function expectPayPalJsFeatures(timeoutMs: number = PAYPAL_JS_FEATURES_TIMEOUT_MS): void {
  if (decided !== null || waiting !== null) return;
  waiting = setTimeout(() => {
    waiting = null;
    decide("v5");
  }, timeoutMs);
  notify();
}

/** The features answer the page received. `null` means the request failed: v5. */
export function notePayPalJsFeatures(features: FeatureAnswer): void {
  if (decided !== null) return;
  const on = features !== null && features !== undefined && features.paypal_js_v6 === true;
  decide(on && !v5ScriptOnPage() ? "v6" : "v5");
}

/** The version to render now; null while the page waits for its features answer (rule 2). */
export function currentPayPalJsVersion(): PayPalJsVersion | null {
  if (decided !== null) return decided;
  return waiting !== null ? null : "v5";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * The PayPal SDK version for this page load. Components that render a PayPal
 * button pick their v5 or v6 implementation from it and render nothing on null.
 */
export function usePayPalJsVersion(): PayPalJsVersion | null {
  return useSyncExternalStore(subscribe, currentPayPalJsVersion, () => "v5" as const);
}

let v6LoadFailureLogged = false;

/**
 * The v6 script or createInstance failed. Log once and use v5 for this page load.
 * Other checkout errors must not call this: the judge path stays on v6.
 */
export function reportPayPalV6LoadFailure(reason: unknown): void {
  if (!v6LoadFailureLogged) {
    v6LoadFailureLogged = true;
    console.warn("PayPal Web SDK v6 failed to load; using the v5 checkout", reason);
  }
  if (waiting !== null) clearTimeout(waiting);
  waiting = null;
  if (decided !== "v5") {
    decided = "v5";
    notify();
  }
}

/** Tests only: forget the decision and any pending wait. */
export function resetPayPalJsVersionForTests(): void {
  decided = null;
  v6LoadFailureLogged = false;
  if (waiting !== null) clearTimeout(waiting);
  waiting = null;
  notify();
}
