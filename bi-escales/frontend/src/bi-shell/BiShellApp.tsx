import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";
import { BiShellHeader } from "./BiShellHeader";
import { BiShellLeftSidebar } from "./BiShellLeftSidebar";
import { BiShellMapStage } from "./BiShellMapStage";
import { BiShellSettingsDrawer } from "./BiShellSettingsDrawer";
import type { BiShellSlots, BiShellView } from "./types";
import "./bi-shell.css";

export type BiShellAppProps = {
  slots?: BiShellSlots;
};

/**
 * Empty Blue Intelligence–look shell, Escales-compatible (Vite/React/i18n).
 * Mount Escalés features later via `slots` without changing BI upstream.
 */
export function BiShellApp({ slots = {} }: BiShellAppProps) {
  const { t, i18n } = useTranslation();
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [view, setView] = useState<BiShellView>("map");
  const [leftOpen, setLeftOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.add("bi-shell-root");
    document.documentElement.dataset.mode = "marinas";
    return () => {
      document.documentElement.classList.remove("bi-shell-root");
      delete document.documentElement.dataset.mode;
    };
  }, []);

  const onLang = (next: "fr" | "en") => {
    void setLanguage(next);
  };

  return (
    <div className="bi-shell" data-testid="bi-shell" data-mode="marinas">
      <div className="bi-shell-preview-banner">{t("biShell.previewBanner")}</div>
      <BiShellHeader
        lang={lang}
        onLang={onLang}
        view={view}
        onView={setView}
        settingsOpen={settingsOpen}
        onToggleSettings={() => setSettingsOpen((v) => !v)}
        title={t("biShell.title")}
        subtitle={t("biShell.subtitle")}
        mapLabel={t("biShell.tabMap")}
        consoleLabel={t("biShell.tabConsole")}
        settingsLabel={t("biShell.settings")}
      />
      <div className="bi-shell-body">
        <button
          type="button"
          className={`bi-shell-floating-toggle bi-shell-floating-toggle--left${leftOpen ? " is-open" : ""}`}
          data-testid="bi-shell-left-toggle"
          aria-expanded={leftOpen}
          aria-label={leftOpen ? t("biShell.leftCollapse") : t("biShell.leftExpand")}
          onClick={() => setLeftOpen((o) => !o)}
        >
          {leftOpen ? "◀" : "▶"}
        </button>
        <BiShellLeftSidebar
          open={leftOpen}
          labels={{
            marinas: t("biShell.slotMarinas"),
            projects: t("biShell.slotProjects"),
            stopovers: t("biShell.slotStopovers"),
            captain: t("biShell.slotCaptain"),
            membership: t("biShell.slotMembership"),
          }}
          marinas={slots.leftMarinas}
          projects={slots.leftProjects}
          stopovers={slots.leftStopovers}
          captain={slots.leftCaptain}
          membership={slots.leftMembership}
        />
        <main className="bi-shell-main" data-testid="bi-shell-main">
          {view === "map" ? (
            slots.map ?? <BiShellMapStage popup={slots.mapPopup} />
          ) : (
            <div className="bi-shell-console" data-testid="bi-shell-console" data-slot="console.treasurer">
              <p className="bi-slot-label">{t("biShell.slotTreasurer")}</p>
              {slots.treasurer ?? (
                <p className="bi-slot-empty">{t("biShell.treasurerEmpty")}</p>
              )}
            </div>
          )}
          <BiShellSettingsDrawer
            open={settingsOpen}
            title={t("biShell.settings")}
            onClose={() => setSettingsOpen(false)}
          >
            {slots.settings}
          </BiShellSettingsDrawer>
        </main>
      </div>
    </div>
  );
}

export default BiShellApp;
