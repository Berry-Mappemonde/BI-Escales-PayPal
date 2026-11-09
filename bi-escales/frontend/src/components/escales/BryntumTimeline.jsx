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

let timelineModulesPromise;

export function resetBryntumTimelineModulesForTests() {
  timelineModulesPromise = undefined;
}

export function loadBryntumTimelineModules() {
  if (!timelineModulesPromise) {
    timelineModulesPromise = Promise.all([
      import("@bryntum/scheduler-react-community"),
      import("@bryntum/scheduler-community"),
      import("@bryntum/scheduler-community/locales/scheduler.locale.FrFr.js"),
      import("@bryntum/scheduler-community/scheduler.css"),
      import("@bryntum/scheduler-community/svalbard-light.css"),
      import("@bryntum/core-community"),
    ])
      .then(([reactMod, , , , , coreMod]) => ({
        BryntumScheduler: reactMod.BryntumScheduler,
        LocaleManager: coreMod.LocaleManager,
      }))
      .catch((error) => {
        timelineModulesPromise = undefined;
        throw error;
      });
  }
  return timelineModulesPromise;
}

export default function BryntumTimeline({ events, onSelect, fallback }) {
  const { t, i18n } = useTranslation();
  const [modules, setModules] = useState(null);
  const [failed, setFailed] = useState(false);
  const schedulerRef = useRef(null);
  const loadGenerationRef = useRef(0);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const columnHeadingRef = useRef(t("scheduler.heading"));
  columnHeadingRef.current = t("scheduler.heading");

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
    if (!modules?.LocaleManager) return undefined;
    const syncLocale = (lng) => {
      void modules.LocaleManager.applyLocale(bryntumLocaleForLanguage(lng));
    };
    syncLocale(i18n.language);
    const onLanguageChanged = (lng) => {
      syncLocale(lng);
      const column = schedulerRef.current?.instance?.columns?.first;
      if (column) {
        column.text = columnHeadingRef.current;
      }
    };
    i18n.on("languageChanged", onLanguageChanged);
    return () => {
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
    () => [{ text: columnHeadingRef.current, field: "name", width: 160 }],
    // Column title is refreshed on i18n languageChanged via schedulerRef (see effect above).
    [],
  );

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
    <div className="escales-scheduler-bryntum" data-testid="escales-scheduler-bryntum">
      <BryntumScheduler ref={schedulerRef} {...schedulerProps} />
    </div>
  );
}
