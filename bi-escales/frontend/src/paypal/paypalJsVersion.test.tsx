import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PAYPAL_JS_FEATURES_TIMEOUT_MS,
  currentPayPalJsVersion,
  expectPayPalJsFeatures,
  notePayPalJsFeatures,
  resetPayPalJsVersionForTests,
  usePayPalJsVersion,
} from "./paypalJsVersion";

function Probe() {
  const version = usePayPalJsVersion();
  return <output data-testid="version">{version === null ? "waiting" : version}</output>;
}

function addV5Script() {
  const script = document.createElement("script");
  script.dataset.paypalSdkSrc = "https://www.paypal.com/sdk/js?client-id=test";
  document.body.appendChild(script);
  return script;
}

describe("PayPal JS version (features.paypal_js_v6)", () => {
  beforeEach(() => resetPayPalJsVersionForTests());
  afterEach(() => {
    vi.useRealTimers();
    document.querySelectorAll("script[data-paypal-sdk-src]").forEach((node) => node.remove());
    resetPayPalJsVersionForTests();
  });

  describe("on its own: today's v5", () => {
    it("is v5 at once when no page announced a features request", () => {
      render(<Probe />);
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
      expect(currentPayPalJsVersion()).toBe("v5");
    });

    it("stores nothing in the browser", () => {
      render(<Probe />);
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    });
  });

  describe("flag off", () => {
    it.each([
      ["the flag is false", { paypal_js_v6: false }],
      ["the flag is missing", {}],
      ["the flag is the string \"true\"", { paypal_js_v6: "true" }],
      ["the flag is 1", { paypal_js_v6: 1 }],
      ["the features request failed", null],
      ["there is no answer", undefined],
    ])("is v5 when %s", (_case, features) => {
      expectPayPalJsFeatures();
      render(<Probe />);
      expect(screen.getByTestId("version")).toHaveTextContent("waiting");
      act(() => notePayPalJsFeatures(features as never));
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
    });

    it("keeps v5 for the rest of the page load once decided", () => {
      act(() => notePayPalJsFeatures({ paypal_js_v6: false }));
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(currentPayPalJsVersion()).toBe("v5");
    });
  });

  describe("flag on", () => {
    it("is v6 once the page's features answer says so", () => {
      expectPayPalJsFeatures();
      render(<Probe />);
      expect(screen.getByTestId("version")).toHaveTextContent("waiting");
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getByTestId("version")).toHaveTextContent("v6");
    });

    it("switches a component that was already showing v5", () => {
      render(<Probe />);
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getByTestId("version")).toHaveTextContent("v6");
    });

    it("never mixes: a v5 SDK script already on the page keeps this load on v5", () => {
      addV5Script();
      render(<Probe />);
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
    });

    it("keeps v6 for the rest of the page load once decided", () => {
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      act(() => notePayPalJsFeatures({ paypal_js_v6: false }));
      addV5Script();
      expect(currentPayPalJsVersion()).toBe("v6");
    });
  });

  describe("waiting for the page's features answer", () => {
    it("renders nothing to load until the answer arrives", () => {
      render(<Probe />);
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
      act(() => expectPayPalJsFeatures());
      expect(screen.getByTestId("version")).toHaveTextContent("waiting");
      expect(currentPayPalJsVersion()).toBeNull();
    });

    it("falls back to v5 when no answer arrives in time, and a late answer changes nothing", () => {
      vi.useFakeTimers();
      expectPayPalJsFeatures();
      render(<Probe />);
      act(() => vi.advanceTimersByTime(PAYPAL_JS_FEATURES_TIMEOUT_MS - 1));
      expect(screen.getByTestId("version")).toHaveTextContent("waiting");
      act(() => vi.advanceTimersByTime(1));
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getByTestId("version")).toHaveTextContent("v5");
    });

    it("an answer cancels the timeout", () => {
      vi.useFakeTimers();
      expectPayPalJsFeatures();
      render(<Probe />);
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      act(() => vi.advanceTimersByTime(PAYPAL_JS_FEATURES_TIMEOUT_MS * 2));
      expect(screen.getByTestId("version")).toHaveTextContent("v6");
    });

    it("announcing twice, or after the decision, does not start another wait", () => {
      vi.useFakeTimers();
      expectPayPalJsFeatures(1000);
      act(() => vi.advanceTimersByTime(600));
      expectPayPalJsFeatures(1000);
      act(() => vi.advanceTimersByTime(400));
      expect(currentPayPalJsVersion()).toBe("v5");
      expectPayPalJsFeatures();
      expect(currentPayPalJsVersion()).toBe("v5");
    });

    it("every button on the page gets the same answer", () => {
      expectPayPalJsFeatures();
      render(
        <>
          <Probe />
          <Probe />
          <Probe />
        </>,
      );
      expect(screen.getAllByText("waiting")).toHaveLength(3);
      act(() => notePayPalJsFeatures({ paypal_js_v6: true }));
      expect(screen.getAllByText("v6")).toHaveLength(3);
    });
  });
});
