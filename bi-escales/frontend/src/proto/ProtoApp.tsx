import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";
import { CaptainReviewCard } from "./CaptainReviewCard";
import type { Lang } from "./format";
import { createProtoI18n } from "./i18n";
import { PledgeStatusList } from "./PledgeStatusList";
import { StopPanel } from "./StopPanel";
import "./tokens.css";
import "./proto.css";

const SCREENS = ["stop", "captain", "pledges"] as const;
type Screen = (typeof SCREENS)[number];

function readUrl(): { screen: Screen; lang: Lang } {
  const params = new URLSearchParams(window.location.search);
  const screen = SCREENS.find((id) => id === params.get("screen")) ?? "stop";
  const langParam = params.get("lang");
  const lang: Lang =
    langParam === "fr" || langParam === "en"
      ? langParam
      : navigator.language.toLowerCase().startsWith("en")
        ? "en"
        : "fr";
  return { screen, lang };
}

function Preview({ initialScreen }: { initialScreen: Screen }) {
  const { t, i18n } = useTranslation();
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const tabRefs = useRef(new Map<Screen, HTMLButtonElement>());
  const lang = i18n.language as Lang;

  useEffect(() => {
    document.documentElement.lang = lang;
    const url = new URL(window.location.href);
    url.searchParams.set("screen", screen);
    url.searchParams.set("lang", lang);
    window.history.replaceState(null, "", url);
  }, [lang, screen]);

  function onTabKey(event: KeyboardEvent) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    const index = SCREENS.indexOf(screen);
    let next: Screen | undefined;
    if (step) next = SCREENS[(index + step + SCREENS.length) % SCREENS.length];
    if (event.key === "Home") next = SCREENS[0];
    if (event.key === "End") next = SCREENS[SCREENS.length - 1];
    if (!next) return;
    event.preventDefault();
    setScreen(next);
    tabRefs.current.get(next)?.focus();
  }

  return (
    <div className="proto">
      <header className="proto-bar">
        <div className="proto-brand">
          <span className="proto-product">{t("shell.product")}</span>
          <span className="proto-meta">{t("shell.preview")}</span>
        </div>
        <div className="proto-tabs" role="tablist" aria-label={t("shell.screens")} onKeyDown={onTabKey}>
          {SCREENS.map((id) => (
            <button
              key={id}
              ref={(el) => {
                if (el) tabRefs.current.set(id, el);
                else tabRefs.current.delete(id);
              }}
              id={`proto-tab-${id}`}
              type="button"
              role="tab"
              aria-selected={screen === id}
              aria-controls="proto-screen"
              tabIndex={screen === id ? 0 : -1}
              className="proto-tab"
              onClick={() => setScreen(id)}
            >
              {t(`tabs.${id}`)}
            </button>
          ))}
        </div>
        <div className="proto-tools">
          <span className="proto-meta">{t("shell.mock")}</span>
          <div className="proto-lang" role="group" aria-label={t("shell.language")}>
            {(["fr", "en"] as const).map((code) => (
              <button
                key={code}
                type="button"
                aria-pressed={lang === code}
                onClick={() => void i18n.changeLanguage(code)}
              >
                {code.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main id="proto-screen" className="proto-main" role="tabpanel" aria-labelledby={`proto-tab-${screen}`}>
        {/* All stay mounted: a release keeps counting on another tab and stays final on return. */}
        <StopPanel lang={lang} hidden={screen !== "stop"} />
        <CaptainReviewCard lang={lang} hidden={screen !== "captain"} />
        <PledgeStatusList hidden={screen !== "pledges"} />
      </main>
    </div>
  );
}

export function ProtoApp() {
  const [{ screen, i18n }] = useState(() => {
    const url = readUrl();
    return { screen: url.screen, i18n: createProtoI18n(url.lang) };
  });

  return (
    <I18nextProvider i18n={i18n}>
      <Preview initialScreen={screen} />
    </I18nextProvider>
  );
}
