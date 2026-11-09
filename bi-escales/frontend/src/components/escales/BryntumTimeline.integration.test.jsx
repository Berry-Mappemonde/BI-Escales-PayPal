import { forwardRef, useLayoutEffect } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const applyLocaleSpy = vi.hoisted(() => vi.fn(() => Promise.resolve()));
const schedulerMountCount = vi.hoisted(() => ({ n: 0 }));

function setMockTimeAxisLabels(localeName) {
  const labels =
    localeName === "FrFr"
      ? ["nov. 2026", "08 nov.", "15 nov.", "16 nov."]
      : ["Nov 2026", "08 Nov", "15 Nov", "16 Nov"];
  mockWidget.timeAxisHeaderLabels = labels;
  for (const cell of document.querySelectorAll("[data-header-label]")) {
    const idx = Number(cell.getAttribute("data-header-index"));
    if (!Number.isNaN(idx)) {
      cell.textContent = labels[idx];
      cell.setAttribute("data-header-label", labels[idx]);
    }
  }
}

const mockWidget = vi.hoisted(() => ({
  columns: { first: { text: "" } },
  localeManager: { applyLocale: applyLocaleSpy },
  isPainted: true,
  isHorizontal: true,
  infiniteScroll: false,
  timeAxisSubGrid: { scrollable: { element: { getBoundingClientRect: () => ({ width: 400 }) } } },
  timeAxisViewModel: {
    update: vi.fn(() => {
      const localeName = applyLocaleSpy.mock.calls.at(-1)?.[0] ?? "FrFr";
      setMockTimeAxisLabels(localeName);
    }),
  },
  timeAxisColumn: {
    refreshHeader: vi.fn(() => {
      const localeName = applyLocaleSpy.mock.calls.at(-1)?.[0] ?? "FrFr";
      setMockTimeAxisLabels(localeName);
    }),
  },
  currentOrientation: { doUpdateTimeView: vi.fn() },
  onLocaleChange: vi.fn(),
  viewPreset: { id: "weekAndMonth" },
  presets: { getById: () => ({ id: "weekAndMonth", options: {} }) },
  startDate: new Date("2026-11-08"),
  endDate: new Date("2026-11-17"),
  timeAxisHeaderLabels: ["nov. 2026", "08 nov.", "15 nov.", "16 nov."],
}));

vi.mock("@bryntum/scheduler-react-community", () => ({
  BryntumScheduler: forwardRef(function MockBryntumScheduler({ columns }, ref) {
    useLayoutEffect(() => {
      schedulerMountCount.n += 1;
      mockWidget.columns.first.text = columns?.[0]?.text ?? "";
      if (ref && typeof ref === "object") {
        // Real browsers may not expose `.instance` on the React ref (see resolveSchedulerWidget).
        ref.current = {};
      }
    }, [columns, ref]);
    return (
      <div className="b-scheduler" data-testid="bryntum-scheduler-mock">
        {mockWidget.timeAxisHeaderLabels.map((label, index) => (
          <span
            key={`${index}-${label}`}
            className="b-sch-header-timeaxis-cell"
            data-header-index={index}
            data-header-label={label}
          >
            {label}
          </span>
        ))}
      </div>
    );
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
    mockWidget.timeAxisViewModel.update.mockClear();
    mockWidget.timeAxisColumn.refreshHeader.mockClear();
    schedulerMountCount.n = 0;
    mockWidget.columns.first.text = "";
    setMockTimeAxisLabels("FrFr");
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
      expect(mockWidget.timeAxisHeaderLabels).toEqual(["Nov 2026", "08 Nov", "15 Nov", "16 Nov"]);
      const domLabels = [...document.querySelectorAll("[data-header-label]")].map((el) => el.textContent);
      expect(domLabels).toEqual(["Nov 2026", "08 Nov", "15 Nov", "16 Nov"]);
      expect(domLabels.some((label) => /\d{1,2}\s+nov\./i.test(label))).toBe(false);
    });

    await act(async () => {
      await i18n.changeLanguage("fr");
    });

    await waitFor(() => {
      expect(applyLocaleSpy.mock.calls.at(-1)?.[0]).toBe("FrFr");
      expect(mockWidget.timeAxisHeaderLabels.at(-1)).toBe("16 nov.");
    });

    const localeCalls = applyLocaleSpy.mock.calls.map((call) => call[0]);
    expect(localeCalls).toContain("FrFr");
    expect(localeCalls).toContain("En");
    expect(localeCalls.indexOf("FrFr")).toBeLessThan(localeCalls.lastIndexOf("En"));
    expect(mockWidget.timeAxisColumn.refreshHeader.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(schedulerMountCount.n).toBeGreaterThanOrEqual(2);

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
