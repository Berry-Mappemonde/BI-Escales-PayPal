import React from "react";
import { readStoredLang } from "../i18n/langStorage.js";

export const ROOT_ERROR_COPY = {
  fr: { title: "Une erreur est survenue", message: "L’application n’a pas pu s’afficher correctement.", reload: "Recharger" },
  en: { title: "Something went wrong", message: "The app could not be displayed correctly.", reload: "Reload" },
};

export const REPLAY_ERROR_COPY = {
  fr: { message: "Le replay a rencontré une erreur.", retry: "Réessayer le replay" },
  en: { message: "Replay hit an error.", retry: "Retry replay" },
};

export function pickErrorLanguage(storage, browserLanguage = "") {
  try {
    const stored = readStoredLang(storage);
    if (stored === "fr" || stored === "en") return stored;
  } catch { /* unavailable storage */ }
  return String(browserLanguage).toLowerCase().startsWith("en") ? "en" : "fr";
}

export function shouldReloadAfterPreloadError(sessionStorage) {
  const key = "naviguide:preload-reload";
  if (sessionStorage.getItem(key)) return false;
  sessionStorage.setItem(key, "1");
  return true;
}

export function claimPreloadReload(state) {
  if (state.inProgress) return false;
  state.inProgress = true;
  return true;
}

const centered = { minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "#0f172a", color: "#f8fafc", fontFamily: "system-ui, sans-serif" };
const panel = { maxWidth: 440, padding: 28, borderRadius: 16, background: "#1e293b", textAlign: "center", boxShadow: "0 20px 50px #0006" };

export class RootErrorBoundary extends React.Component {
  state = { error: null };
  componentDidMount() {
    window.addEventListener("naviguide:preload-fatal", this.onPreloadFatal);
  }
  componentWillUnmount() {
    window.removeEventListener("naviguide:preload-fatal", this.onPreloadFatal);
  }
  onPreloadFatal = () => this.setState({ error: new Error("NAVIGUIDE preload failed after retry") });
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("NAVIGUIDE root render error:", error, info); }
  render() {
    if (!this.state.error) return this.props.children;
    const lang = pickErrorLanguage(typeof localStorage === "undefined" ? null : localStorage, typeof navigator === "undefined" ? "" : navigator.language);
    const copy = ROOT_ERROR_COPY[lang];
    return React.createElement("main", { role: "alert", "data-testid": "root-error-fallback", style: centered, lang },
      React.createElement("section", { style: panel },
        React.createElement("h1", { style: { margin: "0 0 12px", fontSize: 24 } }, copy.title),
        React.createElement("p", { style: { margin: "0 0 20px", lineHeight: 1.5 } }, copy.message),
        React.createElement("button", { type: "button", "data-testid": "root-error-reload", onClick: () => window.location.reload(), style: { cursor: "pointer", padding: "10px 18px", border: 0, borderRadius: 8, fontWeight: 700 } }, copy.reload)));
  }
}

export class PanelBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error, info) { console.error("NAVIGUIDE panel render error:", error, info); }
  render() {
    if (this.state.failed) {
      const lang = pickErrorLanguage(typeof localStorage === "undefined" ? null : localStorage, typeof navigator === "undefined" ? "" : navigator.language);
      const copy = lang === "fr" ? ["Ce panneau a rencontré une erreur.", "Réessayer le panneau"] : ["This panel hit an error.", "Retry panel"];
      return React.createElement("div", { role: "alert", style: { padding: 8, color: "#fca5a5", fontSize: 12 }, lang }, copy[0], " ", React.createElement("button", { type: "button", onClick: () => this.setState({ failed: false }) }, copy[1]));
    }
    return this.props.children;
  }
}

export class ReplayErrorBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error, info) { console.error("NAVIGUIDE replay render error:", error, info); }
  render() {
    if (!this.state.failed) return this.props.children;
    const lang = pickErrorLanguage(typeof localStorage === "undefined" ? null : localStorage, typeof navigator === "undefined" ? "" : navigator.language);
    const copy = REPLAY_ERROR_COPY[lang];
    return React.createElement("div", { role: "alert", "data-testid": "replay-error-fallback", lang, className: "text-center text-xs text-rose-200" },
      React.createElement("span", null, copy.message, " "),
      React.createElement("button", { type: "button", "data-testid": "replay-error-retry", onClick: () => this.setState({ failed: false }), className: "underline" }, copy.retry));
  }
}
