import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getPayPalNamespace,
  loadPayPalSdk,
  loadPayPalSubscriptionSdk,
  paypalNamespaceFor,
  safePayPalClose,
  safePayPalRender,
  paypalLocale,
  paypalSdkUrl,
  paypalSubscriptionSdkUrl,
} from "./paypalSdk";

describe("paypalSdkUrl", () => {
  it("loads authorize EUR vault SDK and disables Venmo", () => {
    const url = paypalSdkUrl("test-client-id");
    expect(url).toContain("client-id=test-client-id");
    expect(url).toContain("intent=authorize");
    expect(url).toContain("currency=EUR");
    expect(url).toContain("vault=true");
    expect(url).toContain("disable-funding=venmo");
    expect(url).toContain("enable-funding=paylater");
    expect(url).toContain("locale=fr_FR");
  });

  it("maps English app language to en_US locale", () => {
    const url = paypalSdkUrl("test-client-id", "en");
    expect(url).toContain("locale=en_US");
  });
});

describe("paypalLocale", () => {
  it("defaults to French PayPal locale", () => {
    expect(paypalLocale()).toBe("fr_FR");
    expect(paypalLocale("fr-FR")).toBe("fr_FR");
  });

  it("maps English tags to en_US", () => {
    expect(paypalLocale("en")).toBe("en_US");
    expect(paypalLocale("en-GB")).toBe("en_US");
  });
});

describe("payLaterEligible", () => {
  it("requires at least 30 EUR for messaging", async () => {
    const { payLaterEligible } = await import("./paypalSdk");
    expect(payLaterEligible("29.99")).toBe(false);
    expect(payLaterEligible("30.00")).toBe(true);
    expect(payLaterEligible("80,00")).toBe(true);
  });

  it("only applies to project pledges at the minimum", async () => {
    const { payLaterEligible } = await import("./paypalSdk");
    expect(payLaterEligible("40.00", "project_pledge")).toBe(true);
    expect(payLaterEligible("40.00", "mile")).toBe(false);
    expect(payLaterEligible("40.00", "night")).toBe(false);
  });
});

type NsWindow = Window & Record<string, unknown>;

function sdkScripts(): HTMLScriptElement[] {
  return [...document.querySelectorAll("script[data-paypal-sdk-src]")] as HTMLScriptElement[];
}

/** Simulate PayPal's SDK finishing: it attaches itself under its data-namespace. */
function finishLoad(script: HTMLScriptElement, ns: Record<string, unknown>) {
  (window as unknown as NsWindow)[script.getAttribute("data-namespace") || ""] = ns;
  script.dispatchEvent(new Event("load"));
  script.onload?.(new Event("load"));
}

describe("namespaced PayPal SDK loading (stopover crash: duplicate paypal-buttons)", () => {
  afterEach(() => {
    for (const script of sdkScripts()) {
      delete (window as unknown as NsWindow)[script.getAttribute("data-namespace") || ""];
      script.remove();
    }
    delete window.paypal;
  });

  it("gives subscription and checkout SDKs different namespaces", () => {
    const sub = paypalNamespaceFor(paypalSubscriptionSdkUrl("cid", "en"));
    const auth = paypalNamespaceFor(paypalSdkUrl("cid", "en", "authorize", true));
    const cap = paypalNamespaceFor(paypalSdkUrl("cid", "en", "capture"));
    expect(sub).toMatch(/^paypalSubscriptions_[a-z0-9]+$/);
    expect(auth).toMatch(/^paypalCheckout_[a-z0-9]+$/);
    expect(new Set([sub, auth, cap]).size).toBe(3);
    expect(paypalNamespaceFor(paypalSdkUrl("cid", "en"))).toBe(paypalNamespaceFor(paypalSdkUrl("cid", "en")));
  });

  it("loads the Crew subscription SDK under data-namespace and never sets window.paypal", async () => {
    const pending = loadPayPalSubscriptionSdk("client-sub", "en");
    const [script] = sdkScripts();
    expect(script.getAttribute("data-namespace")).toMatch(/^paypalSubscriptions_/);
    const buttons = vi.fn();
    finishLoad(script, { Buttons: buttons });
    const ns = await pending;
    expect(ns.Buttons).toBe(buttons);
    expect(window.paypal).toBeUndefined();
  });

  it("keeps the subscription SDK when a stopover checkout SDK loads (both coexist)", async () => {
    const subPending = loadPayPalSubscriptionSdk("cid", "en");
    finishLoad(sdkScripts()[0], { Buttons: vi.fn() });
    const sub = await subPending;

    const stopPending = loadPayPalSdk("cid", "en", "authorize", true);
    const scripts = sdkScripts();
    expect(scripts).toHaveLength(2);
    expect(scripts[1].getAttribute("data-namespace")).toMatch(/^paypalCheckout_/);
    finishLoad(scripts[1], { Buttons: vi.fn() });
    const stop = await stopPending;

    expect(stop).not.toBe(sub);
    expect(sdkScripts()).toHaveLength(2);
    expect(getPayPalNamespace(paypalSubscriptionSdkUrl("cid", "en"))).toBe(sub);
  });

  it("reuses one script per SDK URL and adds (never removes) one per locale", async () => {
    const first = loadPayPalSubscriptionSdk("cid", "en");
    const again = loadPayPalSubscriptionSdk("cid", "en");
    expect(sdkScripts()).toHaveLength(1);
    finishLoad(sdkScripts()[0], { Buttons: vi.fn() });
    expect(await again).toBe(await first);

    const fr = loadPayPalSubscriptionSdk("cid", "fr");
    expect(sdkScripts()).toHaveLength(2);
    finishLoad(sdkScripts()[1], { Buttons: vi.fn() });
    await fr;
    expect(sdkScripts()).toHaveLength(2);
    // EN namespace is still there for an FR→EN toggle.
    await expect(loadPayPalSubscriptionSdk("cid", "en")).resolves.toBe(await first);
    expect(sdkScripts()).toHaveLength(2);
  });

  it("rejects without a client id", async () => {
    await expect(loadPayPalSubscriptionSdk("  ")).rejects.toThrow(/client id/);
    await expect(loadPayPalSdk("")).rejects.toThrow(/client id/);
  });
});

describe("safePayPalRender", () => {
  const el = () => document.createElement("div");

  it("is a no-op when the factory is missing", async () => {
    await expect(safePayPalRender(undefined, {}, el())).resolves.toMatchObject({ ok: false });
  });

  it("does not throw when the component has no render (Googlepay() config object)", async () => {
    const googlepay = vi.fn(() => ({ config: vi.fn(), confirmOrder: vi.fn() }));
    await expect(safePayPalRender(googlepay, {}, el())).resolves.toMatchObject({ ok: false, instance: null });
    expect(googlepay).toHaveBeenCalled();
  });

  it("catches a throwing factory (zoid duplicate registration)", async () => {
    const factory = () => {
      throw new Error("Can not register multiple components with the same tag: paypal-buttons");
    };
    const result = await safePayPalRender(factory, {}, el());
    expect(result.ok).toBe(false);
    expect(String(result.error)).toMatch(/multiple components/);
  });

  it("catches a rejected render", async () => {
    const factory = () => ({ render: () => Promise.reject(new Error("zoid destroyed all components")) });
    await expect(safePayPalRender(factory, {}, el())).resolves.toMatchObject({ ok: false });
  });

  it("renders a real component", async () => {
    const render = vi.fn(async () => undefined);
    const target = el();
    const result = await safePayPalRender(() => ({ render }), {}, target);
    expect(result.ok).toBe(true);
    expect(render).toHaveBeenCalledWith(target);
  });

  it("safePayPalClose tolerates missing or throwing close", () => {
    expect(() => safePayPalClose(null)).not.toThrow();
    expect(() =>
      safePayPalClose({
        render: async () => undefined,
        close: () => {
          throw new Error("gone");
        },
      }),
    ).not.toThrow();
  });
});

describe("loadPayPalSdk locale cache", () => {
  it("uses different script URLs per locale", () => {
    expect(paypalSdkUrl("locale-client", "fr")).toContain("locale=fr_FR");
    expect(paypalSdkUrl("locale-client", "en")).toContain("locale=en_US");
  });
});
