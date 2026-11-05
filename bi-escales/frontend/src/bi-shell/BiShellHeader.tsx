import type { BiShellView } from "./types";

type Props = {
  lang: "fr" | "en";
  onLang: (lang: "fr" | "en") => void;
  view: BiShellView;
  onView: (view: BiShellView) => void;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  title: string;
  subtitle: string;
  mapLabel: string;
  consoleLabel: string;
  settingsLabel: string;
};

export function BiShellHeader({
  lang,
  onLang,
  view,
  onView,
  settingsOpen,
  onToggleSettings,
  title,
  subtitle,
  mapLabel,
  consoleLabel,
  settingsLabel,
}: Props) {
  return (
    <header className="bi-shell-header" data-testid="bi-shell-header">
      <h1 className="bi-shell-brand" title={subtitle}>
        <span className="bi-shell-brand-title">{title}</span>
        <span className="bi-shell-brand-sub">{subtitle}</span>
      </h1>
      <nav className="bi-shell-nav" aria-label="BI Escales shell">
        <div className="bi-nav-group">
          <button
            type="button"
            className="bi-nav-tab"
            data-testid="bi-shell-view-map"
            aria-current={view === "map" ? "true" : undefined}
            onClick={() => onView("map")}
          >
            {mapLabel}
          </button>
          <button
            type="button"
            className="bi-nav-tab"
            data-testid="bi-shell-view-console"
            aria-current={view === "console" ? "true" : undefined}
            onClick={() => onView("console")}
          >
            {consoleLabel}
          </button>
        </div>
        <div className="bi-nav-group" role="group" aria-label="Language">
          <button
            type="button"
            className="bi-nav-tab"
            data-testid="bi-shell-lang-en"
            aria-pressed={lang === "en"}
            onClick={() => onLang("en")}
          >
            EN
          </button>
          <button
            type="button"
            className="bi-nav-tab"
            data-testid="bi-shell-lang-fr"
            aria-pressed={lang === "fr"}
            onClick={() => onLang("fr")}
          >
            FR
          </button>
        </div>
        <button
          type="button"
          className="bi-nav-icon"
          data-testid="bi-shell-settings-toggle"
          aria-pressed={settingsOpen}
          aria-label={settingsLabel}
          title={settingsLabel}
          onClick={onToggleSettings}
        >
          ⚙
        </button>
      </nav>
    </header>
  );
}
