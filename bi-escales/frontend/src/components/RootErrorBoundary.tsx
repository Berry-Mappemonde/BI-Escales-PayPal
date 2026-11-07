import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

const COPY = {
  fr: {
    title: "Une erreur est survenue",
    message: "L’application n’a pas pu s’afficher correctement.",
    reload: "Recharger",
  },
  en: {
    title: "Something went wrong",
    message: "The app could not be displayed correctly.",
    reload: "Reload",
  },
} as const;

function pickLang(): "fr" | "en" {
  try {
    const stored = localStorage.getItem("bi-escales-lang");
    if (stored?.startsWith("en")) return "en";
    if (stored?.startsWith("fr")) return "fr";
  } catch {
    /* private mode */
  }
  return String(navigator?.language || "").toLowerCase().startsWith("en") ? "en" : "fr";
}

/** Prevents a hard-reload white screen when a child tree throws. */
export class RootErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("BI Escales root render error:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const lang = pickLang();
    const copy = COPY[lang];
    return (
      <main
        role="alert"
        data-testid="root-error-fallback"
        lang={lang}
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
          background: "#0f172a",
          color: "#f8fafc",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <section
          style={{
            maxWidth: 440,
            padding: 28,
            borderRadius: 16,
            background: "#1e293b",
            textAlign: "center",
          }}
        >
          <h1 style={{ margin: "0 0 12px", fontSize: 24 }}>{copy.title}</h1>
          <p style={{ margin: "0 0 20px", lineHeight: 1.5 }}>{copy.message}</p>
          <button
            type="button"
            data-testid="root-error-reload"
            onClick={() => window.location.reload()}
            style={{
              cursor: "pointer",
              padding: "10px 18px",
              border: 0,
              borderRadius: 8,
              fontWeight: 700,
            }}
          >
            {copy.reload}
          </button>
        </section>
      </main>
    );
  }
}
