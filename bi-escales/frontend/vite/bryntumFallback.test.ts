// @vitest-environment node
import { describe, expect, it } from "vitest";
import { bryntumFallback, bryntumInstalled } from "./bryntumFallback.mjs";

type StubPlugin = {
  resolveId: (source: string) => string | null;
  load: (id: string) => string | null;
};

describe("bryntumFallback", () => {
  it("leaves imports alone when the package is installed", () => {
    const plugin = bryntumFallback({ isInstalled: () => true }) as unknown as StubPlugin;
    expect(plugin.resolveId("@bryntum/scheduler-community")).toBeNull();
    expect(plugin.resolveId("react")).toBeNull();
  });

  it("stubs the module and its css when the optional install failed", () => {
    const plugin = bryntumFallback({ isInstalled: () => false }) as unknown as StubPlugin;
    const js = plugin.resolveId("@bryntum/scheduler-community");
    const css = plugin.resolveId("@bryntum/scheduler-community/scheduler.css");
    expect(js).toBeTruthy();
    expect(css).toBeTruthy();
    expect(js).not.toEqual(css);
    expect(plugin.load(js as string)).toContain("throw new Error");
    expect(plugin.load(css as string)).toContain("not installed");
    expect(plugin.resolveId("@vitejs/plugin-react")).toBeNull();
  });

  it("detects a missing package from a root without node_modules", () => {
    expect(bryntumInstalled("/nonexistent-escales-root")).toBe(false);
  });
});
