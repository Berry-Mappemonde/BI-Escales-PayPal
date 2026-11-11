/**
 * App settings: language and theme, one labelled group (brief item B13).
 *
 * Settings belong to the app, not to the visitor tools or the treasurer tools.
 * So this one control is shown in the rail's masthead and again in the treasurer
 * page's top bar: the same two settings wherever the reader is, and never inside
 * either set of tools.
 */
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";

export interface ShellSettingsProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  /** Where it is shown. Only the rail copy keeps the long-standing test ids. */
  place?: "rail" | "treasurer-page";
}

export function ShellSettings({ theme, onToggleTheme, place = "rail" }: ShellSettingsProps) {
  const { t, i18n } = useTranslation();
  const id = (name: string) => (place === "rail" ? name : `${place}-${name}`);
  return (
    <div className="ng-controls shell-settings" role="group" aria-label={t("settings.heading")} data-testid={id("shell-settings")}>
      <div className="lang-switch" role="group" aria-label={t("app.language")}>
        <button
          type="button"
          className={i18n.language === "fr" ? "active" : ""}
          aria-label={t("app.langFrSwitch")}
          aria-pressed={i18n.language === "fr"}
          onClick={() => setLanguage("fr")}
        >
          FR
        </button>
        <button
          type="button"
          className={i18n.language === "en" ? "active" : ""}
          aria-label={t("app.langEnSwitch")}
          aria-pressed={i18n.language === "en"}
          onClick={() => setLanguage("en")}
        >
          EN
        </button>
      </div>
      <div className="theme-switch" data-testid={id("theme-switch")}>
        <button
          type="button"
          data-testid={id("theme-toggle")}
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
                <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </>
            )}
          </svg>
        </button>
      </div>
    </div>
  );
}
