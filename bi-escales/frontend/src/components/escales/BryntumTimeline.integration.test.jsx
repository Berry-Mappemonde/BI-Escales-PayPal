import { forwardRef, useLayoutEffect } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const applyLocaleSpy = vi.hoisted(() => vi.fn(() => Promise.resolve()));
const mockWidget = vi.hoisted(() => ({
  columns: { first: { text: "" } },
  localeManager: { applyLocale: applyLocaleSpy },
}));

vi.mock("@bryntum/scheduler-react-community", () => ({
  BryntumScheduler: forwardRef(function MockBryntumScheduler({ columns }, ref) {
    useLayoutEffect(() => {
      mockWidget.columns.first.text = columns?.[0]?.text ?? "";
      if (ref && typeof ref === "object") {
        // Real browsers may not expose `.instance` on the React ref (see resolveSchedulerWidget).
        ref.current = {};
      }
    }, [columns, ref]);
    return <div className="b-scheduler" data-testid="bryntum-scheduler-mock" />;
  }),
}));

vi.mock("@bryntum/scheduler-community", () => ({
  LocaleManager: { applyLocale: vi.fn(() => Promise.resolve()) },
}));

vi.mock("@bryntum/scheduler-community/locales/scheduler.locale.FrFr.js", () => ({}));
vi.mock("@bryntum/scheduler-community/scheduler.css", () => ({}));
vi.mock("@bryntum/scheduler-community/svalbard-light.css", () => ({}));

import i18n from "../../i18n";
import BryntumTimeline, {
  loadBryntumTimelineModules,
  resetBryntumTimelineModulesForTests,
  resolveSchedulerWidget,
  syncTimelineLocale,
} from "./BryntumTimeline.jsx";

const events = [
  {
    id: "dep-a",
    name: "La Rochelle",
    startDate: new Date("2026-11-12"),
    endDate: new Date("2026-11-13"),
    milestoneId: "dep-a",
  },
];

describe("BryntumTimeline (scheduler-react-community)", () => {
  const hostRef = { current: null };

  beforeEach(async () => {
    applyLocaleSpy.mockClear();
    mockWidget.columns.first.text = "";
    resetBryntumTimelineModulesForTests();
    globalThis.bryntum = {
      fromElement: vi.fn(() => mockWidget),
    };
    await act(async () => {
      await i18n.changeLanguage("fr");
    });
  });

  afterEach(() => {
    delete globalThis.bryntum;
  });

  it("loads lazily-imported Bryntum modules in tests", async () => {
    const loaded = await loadBryntumTimelineModules();
    expect(loaded.BryntumScheduler).toBeTruthy();
    expect(loaded.LocaleManager.applyLocale).toBeTypeOf("function");
  });

  it("resolveSchedulerWidget uses bryntum.fromElement when the React ref has no instance", () => {
    const schedulerRef = { current: {} };
    const host = document.createElement("div");
    host.innerHTML = '<div class="b-scheduler"></div>';
    hostRef.current = host;
    const widget = resolveSchedulerWidget(schedulerRef, hostRef);
    expect(globalThis.bryntum.fromElement).toHaveBeenCalled();
    expect(widget).toBe(mockWidget);
  });

  it("renders the scheduler after modules load", async () => {
    const view = render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.queryByTestId("fallback")).not.toBeInTheDocument();
      expect(screen.queryByTestId("bryntum-loading")).not.toBeInTheDocument();
    });
    expect(document.querySelectorAll(".b-scheduler")).toHaveLength(1);
    view.unmount();
  });

  it("renders one scheduler, syncs locales FR then EN, and unmounts cleanly under StrictMode", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const view = render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
      { reactStrictMode: true },
    );

    await waitFor(() => {
      expect(screen.getByTestId("escales-scheduler-bryntum")).toBeInTheDocument();
      expect(document.querySelectorAll(".b-scheduler")).toHaveLength(1);
    });

    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });

    await act(async () => {
      await i18n.changeLanguage("en");
    });

    await waitFor(() => {
      expect(document.querySelectorAll(".b-scheduler")).toHaveLength(1);
      expect(applyLocaleSpy.mock.calls.some((call) => call[0] === "En")).toBe(true);
    });

    const localeCalls = applyLocaleSpy.mock.calls.map((call) => call[0]);
    expect(localeCalls).toContain("FrFr");
    expect(localeCalls).toContain("En");
    expect(localeCalls.indexOf("FrFr")).toBeLessThan(localeCalls.lastIndexOf("En"));

    view.unmount();
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("updates the resource column heading to English after changeLanguage(en)", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("escales-scheduler-bryntum")).toBeInTheDocument();
    });

    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });
    expect(mockWidget.columns.first.text).toBe("Calendrier des escales");

    await act(async () => {
      await i18n.changeLanguage("en");
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });

    expect(mockWidget.columns.first.text).toBe("Stopover calendar");
  });

  it("prefers widget.localeManager.applyLocale for timeline locale", () => {
    const globalManager = { applyLocale: vi.fn(() => Promise.resolve()) };
    const schedulerRef = { current: {} };
    const host = document.createElement("div");
    host.innerHTML = '<div class="b-scheduler"></div>';
    const wrapper = { current: host };
    syncTimelineLocale({
      schedulerRef,
      hostRef: wrapper,
      modules: { LocaleManager: globalManager },
      i18n,
      lng: "fr",
    });
    expect(applyLocaleSpy).toHaveBeenCalledWith("FrFr");
    expect(globalManager.applyLocale).not.toHaveBeenCalled();
  });
});
