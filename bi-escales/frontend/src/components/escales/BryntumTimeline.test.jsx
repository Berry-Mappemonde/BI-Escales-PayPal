import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import BryntumTimeline, {
  TIMELINE_LOCALE_SYNC_MAX_ATTEMPTS,
  TIMELINE_LOCALE_SYNC_RETRY_MS,
  bryntumLocaleForLanguage,
  refreshTimelineTimeAxis,
  resolveSchedulerWidget,
  runTimelineLocaleSyncWithRetries,
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

describe("bryntumLocaleForLanguage", () => {
  it("maps French i18n to FrFr and English to En", () => {
    expect(bryntumLocaleForLanguage("fr")).toBe("FrFr");
    expect(bryntumLocaleForLanguage("fr-FR")).toBe("FrFr");
    expect(bryntumLocaleForLanguage("en")).toBe("En");
    expect(bryntumLocaleForLanguage("en-US")).toBe("En");
  });
});

describe("resolveSchedulerWidget", () => {
  it("logs a warning when bryntum.fromElement throws", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const host = document.createElement("div");
    host.innerHTML = '<div class="b-scheduler"></div>';
    globalThis.bryntum = {
      fromElement: vi.fn(() => {
        throw new Error("widget not ready");
      }),
    };
    const widget = resolveSchedulerWidget({ current: {} }, { current: host });
    expect(widget).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("bryntum.fromElement failed"),
      expect.objectContaining({ hasSchedulerElement: true }),
    );
    warnSpy.mockRestore();
    delete globalThis.bryntum;
  });
});

describe("syncTimelineLocale time axis", () => {
  it("applies locale and rebuilds axis headers for FR, EN, then FR", async () => {
    const applyLocale = vi.fn(() => Promise.resolve());
    const refreshTimeAxis = vi.fn();
    const host = document.createElement("div");
    host.innerHTML = '<div class="b-scheduler"></div>';
    const widget = {
      columns: { first: { text: "" } },
      localeManager: { applyLocale },
      refreshTimeAxis,
    };
    globalThis.bryntum = { fromElement: vi.fn(() => widget) };

    for (const lng of ["fr", "en", "fr"]) {
      const { localeName } = await syncTimelineLocale({
        schedulerRef: { current: {} },
        hostRef: { current: host },
        modules: { LocaleManager: { applyLocale: vi.fn() } },
        i18n,
        lng,
      });
      expect(localeName).toBe(lng === "fr" ? "FrFr" : "En");
    }

    expect(applyLocale).toHaveBeenCalledTimes(3);
    expect(refreshTimeAxis).toHaveBeenCalledTimes(3);
    expect(refreshTimeAxis.mock.calls.every((call) => call[0] === true)).toBe(true);
    delete globalThis.bryntum;
  });

  it("falls back to timeAxisColumn.refreshHeader when refreshTimeAxis is missing", () => {
    const refreshHeader = vi.fn();
    refreshTimelineTimeAxis({ timeAxisColumn: { refreshHeader } });
    expect(refreshHeader).toHaveBeenCalledWith(null, true);
  });
});

describe("runTimelineLocaleSyncWithRetries", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it(`retries up to ${TIMELINE_LOCALE_SYNC_MAX_ATTEMPTS} times when the widget is not mounted`, async () => {
    const applyLocale = vi.fn(() => Promise.resolve());
    const refreshTimeAxis = vi.fn();
    const host = document.createElement("div");
    host.innerHTML = '<div class="b-scheduler"></div>';
    const widget = {
      columns: { first: { text: "" } },
      localeManager: { applyLocale },
      refreshTimeAxis,
    };
    let mountAttempt = 0;
    const fromElement = vi.fn(() => {
      mountAttempt += 1;
      return mountAttempt >= 3 ? widget : null;
    });
    globalThis.bryntum = { fromElement };

    const cancel = runTimelineLocaleSyncWithRetries({
      schedulerRef: { current: {} },
      hostRef: { current: host },
      modules: { LocaleManager: { applyLocale } },
      i18n,
      lng: "en",
    });

    await vi.advanceTimersByTimeAsync(TIMELINE_LOCALE_SYNC_RETRY_MS * (TIMELINE_LOCALE_SYNC_MAX_ATTEMPTS - 1));
    await Promise.resolve();
    await Promise.resolve();

    expect(fromElement.mock.calls.length).toBe(3);
    expect(applyLocale).toHaveBeenCalledWith("En");
    expect(refreshTimeAxis).toHaveBeenCalledWith(true);
    cancel();
    delete globalThis.bryntum;
  });
});

describe("BryntumTimeline", () => {
  it("shows the loading line first", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={events} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("bryntum-loading")).toBeInTheDocument();
  });

  it("uses the fallback when there are no events", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <BryntumTimeline events={[]} fallback={<p data-testid="fallback">list</p>} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });
});
