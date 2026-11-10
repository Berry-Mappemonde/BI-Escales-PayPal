/**
 * Bryntum Scheduler Community timeline via @bryntum/scheduler-react-community, read-only.
 * Loaded only behind ESCALES_BRYNTUM_ENABLED. Falls back to the local list if packages are absent.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export function bryntumLocaleForLanguage(i18nLanguage) {
  const base = String(i18nLanguage || "").split("-")[0].toLowerCase();
  return base === "fr" ? "FrFr" : "En";
}

/** Bounded retries when the scheduler widget is not mounted yet at locale change. */
export const TIMELINE_LOCALE_SYNC_MAX_ATTEMPTS = 5;
export const TIMELINE_LOCALE_SYNC_RETRY_MS = 32;

let timelineModulesPromise;

export function resetBryntumTimelineModulesForTests() {
  timelineModulesPromise = undefined;
}

/** Dynamic import specifiers used by loadBryntumTimelineModules (for build fallback tests). */
export const BRYNTUM_TIMELINE_IMPORTS = [
  "@bryntum/scheduler-react-community",
  "@bryntum/scheduler-community",
  "@bryntum/scheduler-community/locales/scheduler.locale.FrFr.js",
  "@bryntum/scheduler-community/scheduler.css",
  "@bryntum/scheduler-community/svalbard-light.css",
];

export function loadBryntumTimelineModules() {
  if (!timelineModulesPromise) {
    timelineModulesPromise = Promise.all([
      import("@bryntum/scheduler-react-community"),
      import("@bryntum/scheduler-community"),
      import("@bryntum/scheduler-community/locales/scheduler.locale.FrFr.js"),
      import("@bryntum/scheduler-community/scheduler.css"),
      import("@bryntum/scheduler-community/svalbard-light.css"),
    ])
      .then(([reactMod, schedMod]) => ({
        BryntumScheduler: reactMod.BryntumScheduler,
        LocaleManager: schedMod.LocaleManager,
      }))
      .catch((error) => {
        timelineModulesPromise = undefined;
        throw error;
      });
  }
  return timelineModulesPromise;
}

/**
 * Resolve the live Bryntum Scheduler widget instance.
 * The React wrapper ref is a class component (`.instance` when set); in some runtimes only
 * `bryntum.fromElement` finds the widget — both paths are tried.
 */
export function resolveSchedulerWidget(schedulerRef, hostRef) {
  const reactWrapper = schedulerRef?.current;
  if (reactWrapper?.instance) {
    return reactWrapper.instance;
  }
  const host = hostRef?.current;
  const schedEl = host?.querySelector?.(".b-scheduler") ?? null;
  const fromElement = globalThis.bryntum?.fromElement;
  if (schedEl && typeof fromElement === "function") {
    try {
      return fromElement(schedEl);
    } catch (error) {
      console.warn("[BryntumTimeline] bryntum.fromElement failed while resolving scheduler widget", {
        error,
        hasHost: Boolean(host),
        hasSchedulerElement: Boolean(schedEl),
      });
      return null;
    }
  }
  return null;
}

/**
 * Regenerate every time-axis header cell after a locale switch.
 * `refreshTimeAxis(true)` alone can leave the last partial day cell in the previous language (e.g. `16 nov.`).
 */
export function rebuildTimelineTimeAxisHeaders(widget) {
  if (!widget) return;

  if (widget.isPainted && typeof widget.onLocaleChange === "function") {
    widget.onLocaleChange();
  }

  const timeAxisViewModel = widget.timeAxisViewModel;
  if (timeAxisViewModel && typeof timeAxisViewModel.update === "function") {
    const scrollable = widget.isHorizontal ? widget.timeAxisSubGrid?.scrollable : widget.scrollable;
    const dimension = widget.isHorizontal ? "width" : "height";
    const availableSpace = scrollable?.element?.getBoundingClientRect?.()[dimension];
    if (availableSpace != null) {
      timeAxisViewModel.update(availableSpace, widget.infiniteScroll, true);
    } else {
      timeAxisViewModel.update(undefined, undefined, true);
    }
  }

  widget.currentOrientation?.doUpdateTimeView?.();
  widget.timeAxisColumn?.refreshHeader?.();

  const presetId = widget.viewPreset?.id ?? widget.viewPreset;
  if (presetId && widget.presets?.getById) {
    const presetRecord = widget.presets.getById(presetId);
    if (presetRecord) {
      const startDate = widget.startDate;
      const endDate = widget.endDate;
      presetRecord.options = { ...(presetRecord.options ?? {}), startDate, endDate };
      widget.viewPreset = presetRecord;
    }
  }
}

export async function syncTimelineLocale({ schedulerRef, hostRef, modules, i18n, lng }) {
  const localeName = bryntumLocaleForLanguage(lng);
  const widget = resolveSchedulerWidget(schedulerRef, hostRef);
  const localeManager = widget?.localeManager ?? modules?.LocaleManager;
  if (localeManager) {
    const applyResult = localeManager.applyLocale(localeName);
    if (applyResult && typeof applyResult.then === "function") {
      await applyResult;
    }
  }
  rebuildTimelineTimeAxisHeaders(widget);
  const heading = i18n.t("scheduler.heading", { lng });
  const column = widget?.columns?.first;
  if (column) {
    column.text = heading;
  }
  return { widget, heading, localeName };
}

/**
 * Retry locale sync when the Bryntum widget is not yet mounted (bounded attempts, short delay).
 * Returns a cancel function for effect cleanup.
 */
export function runTimelineLocaleSyncWithRetries(ctx) {
  let attempt = 0;
  let cancelled = false;
  let timerId;

  const trySync = () => {
    if (cancelled) return;
    void syncTimelineLocale(ctx).then(({ widget }) => {
      if (cancelled) return;
      if (widget || attempt >= TIMELINE_LOCALE_SYNC_MAX_ATTEMPTS - 1) {
        return;
      }
      attempt += 1;
      timerId = globalThis.setTimeout(trySync, TIMELINE_LOCALE_SYNC_RETRY_MS);
    });
  };

  trySync();

  return () => {
    cancelled = true;
    if (timerId != null) {
      globalThis.clearTimeout(timerId);
    }
  };
}

export default function BryntumTimeline({ events, onSelect, fallback }) {
  const { t, i18n } = useTranslation();
  const [modules, setModules] = useState(null);
  const [failed, setFailed] = useState(false);
  const schedulerRef = useRef(null);
  const hostRef = useRef(null);
  const loadGenerationRef = useRef(0);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const loadId = ++loadGenerationRef.current;
    let cancelled = false;
    loadBryntumTimelineModules()
      .then((loaded) => {
        if (!cancelled && loadId === loadGenerationRef.current) {
          setFailed(false);
          setModules(loaded);
        }
      })
      .catch(() => {
        if (!cancelled && loadId === loadGenerationRef.current) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!modules) return undefined;
    const ctx = { schedulerRef, hostRef, modules, i18n };

    let cancelActiveSync = runTimelineLocaleSyncWithRetries({ ...ctx, lng: i18n.language });

    const onLanguageChanged = (lng) => {
      cancelActiveSync?.();
      cancelActiveSync = runTimelineLocaleSyncWithRetries({ ...ctx, lng });
    };
    i18n.on("languageChanged", onLanguageChanged);
    return () => {
      cancelActiveSync?.();
      i18n.off("languageChanged", onLanguageChanged);
    };
  }, [modules, i18n]);

  const resources = useMemo(() => [{ id: "route", name: "BI Escales" }], []);

  const timelineEvents = useMemo(
    () =>
      events.map((event) => ({
        id: event.id,
        name: event.name,
        resourceId: "route",
        startDate: event.startDate,
        endDate: event.endDate,
        milestoneId: event.milestoneId,
      })),
    [events],
  );

  const { startDate, endDate } = useMemo(() => {
    if (!events.length) {
      const now = new Date();
      return { startDate: now, endDate: now };
    }
    return {
      startDate: events[0].startDate,
      endDate: events[events.length - 1].endDate,
    };
  }, [events]);

  const listeners = useMemo(
    () => ({
      eventClick({ eventRecord }) {
        onSelectRef.current?.({
          id: eventRecord.id,
          name: eventRecord.name,
          milestoneId: eventRecord.milestoneId,
        });
      },
    }),
    [],
  );

  const columns = useMemo(
    () => [{ text: t("scheduler.heading"), field: "name", width: 160 }],
    [i18n.language, t],
  );

  const bryntumLocaleKey = bryntumLocaleForLanguage(i18n.language);

  const schedulerProps = useMemo(
    () => ({
      readOnly: true,
      height: 220,
      startDate,
      endDate,
      viewPreset: "weekAndMonth",
      columns,
      resources,
      events: timelineEvents,
      listeners,
    }),
    [startDate, endDate, columns, resources, timelineEvents, listeners],
  );

  if (!events.length) return fallback;
  if (failed) return fallback;
  if (!modules) {
    return (
      <p className="escales-scheduler-loading rail-loading" role="status" data-testid="bryntum-loading">
        {t("scheduler.loading", "…")}
      </p>
    );
  }

  const { BryntumScheduler } = modules;
  return (
    <div
      className="escales-scheduler-bryntum"
      data-testid="escales-scheduler-bryntum"
      ref={hostRef}
    >
      <BryntumScheduler key={bryntumLocaleKey} ref={schedulerRef} {...schedulerProps} />
    </div>
  );
}
