// @vitest-environment node
import { describe, expect, it } from "vitest";
import { BRYNTUM_TIMELINE_IMPORTS } from "../src/components/escales/BryntumTimeline.jsx";
import { bryntumFallback, bryntumInstalled } from "./bryntumFallback.mjs";

type StubPlugin = {
  resolveId: (source: string) => string | null;
  load: (id: string) => string | null;
};

describe("bryntumFallback", () => {
  it("leaves imports alone when the packages are installed", () => {
    const plugin = bryntumFallback({ isInstalled: () => true }) as unknown as StubPlugin;
    expect(plugin.resolveId("@bryntum/scheduler-community")).toBeNull();
    expect(plugin.resolveId("@bryntum/scheduler-react-community")).toBeNull();
    expect(plugin.resolveId("react")).toBeNull();
  });

  it("stubs the modules and their css when the optional install failed", () => {
    const plugin = bryntumFallback({ isInstalled: () => false }) as unknown as StubPlugin;
    const js = plugin.resolveId("@bryntum/scheduler-community");
    const reactJs = plugin.resolveId("@bryntum/scheduler-react-community");
    const css = plugin.resolveId("@bryntum/scheduler-community/scheduler.css");
    expect(js).toBeTruthy();
    expect(reactJs).toBeTruthy();
    expect(css).toBeTruthy();
    expect(js).not.toEqual(css);
    expect(plugin.load(js as string)).toContain("throw new Error");
    expect(plugin.load(reactJs as string)).toContain("throw new Error");
    expect(plugin.load(css as string)).toContain("not installed");
    expect(plugin.resolveId("@vitejs/plugin-react")).toBeNull();
  });

  it("stubs every dynamic import used by loadBryntumTimelineModules", () => {
    const plugin = bryntumFallback({ isInstalled: () => false }) as unknown as StubPlugin;
  for (const specifier of BRYNTUM_TIMELINE_IMPORTS) {
      const resolved = plugin.resolveId(specifier);
      expect(resolved, specifier).toBeTruthy();
      const body = plugin.load(resolved as string);
      if (specifier.endsWith(".css")) {
        expect(body).toContain("not installed");
      } else {
        expect(body).toContain("throw new Error");
      }
    }
  });

  it("detects a missing package from a root without node_modules", () => {
    expect(bryntumInstalled("/nonexistent-escales-root")).toBe(false);
  });
});
