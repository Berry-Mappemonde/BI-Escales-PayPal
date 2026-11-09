// @vitest-environment node
import { describe, expect, it } from "vitest";
import { DEFAULT_API_PROXY_TARGET, resolveApiProxyTarget } from "./apiProxyTarget";

describe("resolveApiProxyTarget", () => {
  it("defaults to the local backend when VITE_API_PROXY_TARGET is unset or empty", () => {
    expect(resolveApiProxyTarget({})).toBe(DEFAULT_API_PROXY_TARGET);
    expect(resolveApiProxyTarget({ VITE_API_PROXY_TARGET: "" })).toBe(DEFAULT_API_PROXY_TARGET);
    expect(resolveApiProxyTarget({ VITE_API_PROXY_TARGET: "   " })).toBe(DEFAULT_API_PROXY_TARGET);
    expect(DEFAULT_API_PROXY_TARGET).toBe("http://localhost:8000");
  });

  it("uses VITE_API_PROXY_TARGET when set", () => {
    const test2 = "https://bi-escales-api-test2.onrender.com";
    expect(resolveApiProxyTarget({ VITE_API_PROXY_TARGET: test2 })).toBe(test2);
    expect(resolveApiProxyTarget({ VITE_API_PROXY_TARGET: `  ${test2}  ` })).toBe(test2);
  });
});
