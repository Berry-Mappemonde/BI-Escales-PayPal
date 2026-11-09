import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";

export interface ShellSettingsPanelProps {
  prod: boolean;
  devT0: string;
  t0: string;
  onDevT0Change: (value: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  children?: ReactNode;
}

/** Language, theme, and dev clock pin — right settings rail only. */
export function ShellSettingsPanel({
  prod,
  devT0,
  t0,
  onDevT0Change,
  theme,
  onToggleTheme,
  children,
}: ShellSettingsPanelProps) {
  const { t, i18n } = useTranslation();

  return (
    <div className="ng-settings-body" data-testid="ng-settings-body">
      <header className="ng-settings-header">
        <h2 className="ng-settings-title">{t("settings.heading")}</h2>
        <p className="hint ng-settings-lead">{t("settings.leadPanel")}</p>
      </header>
      <div className="ng-controls ng-settings-controls" data-testid="ng-settings-controls">
        <div className="lang-switch" role="group" aria-label={t("app.language")}>
          <button
            type="button"
            className={i18n.language === "fr" ? "active" : ""}
            aria-label={t("app.langFr")}
            aria-pressed={i18n.language === "fr"}
            onClick={() => setLanguage("fr")}
          >
            FR
          </button>
          <button
            type="button"
            className={i18n.language === "en" ? "active" : ""}
            aria-label={t("app.langEn")}
            aria-pressed={i18n.language === "en"}
            onClick={() => setLanguage("en")}
          >
            EN
          </button>
        </div>
        <div className="theme-switch" data-testid="theme-switch">
          <button
            type="button"
            data-testid="theme-toggle"
            aria-label={theme === "light" ? t("app.themeDark") : t("app.themeLight")}
            aria-pressed={theme === "light"}
            onClick={() => onToggleTheme()}
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              {theme === "light" ? (
                <path
                  d="M20.2 15.1A8.4 8.4 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinejoin="round"
                />
              ) : (
                <>
                  <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.7" />
                  <path
                    d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                  />
                </>
              )}
            </svg>
          </button>
        </div>
      </div>
      {!prod ? (
        <label className="dev-t0 ng-settings-dev-t0">
          {t("clock.devT0")}
          <input
            type="text"
            value={devT0 || t0}
            onChange={(event) => onDevT0Change(event.target.value)}
            aria-label={t("clock.devT0")}
          />
        </label>
      ) : null}
      {children}
    </div>
  );
}
