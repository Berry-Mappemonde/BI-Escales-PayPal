import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";

export interface ShellSettingsPanelProps {
  prod: boolean;
  devT0: string;
  t0: string;
  onDevT0Change: (value: string) => void;
  children?: ReactNode;
}

/** Language and dev clock pin — right settings rail only (theme lives in the sidebar header). */
export function ShellSettingsPanel({
  prod,
  devT0,
  t0,
  onDevT0Change,
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
