import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; testId?: string };
type State = { error: Error | null };

function isEnglish(): boolean {
  try {
    const stored = localStorage.getItem("bi-escales-lang");
    if (stored) return stored.startsWith("en");
  } catch {
    /* private mode */
  }
  return String(document?.documentElement?.lang || "").toLowerCase().startsWith("en");
}

/**
 * Local boundary around every PayPal-hosting widget: a PayPal SDK failure
 * (missing component, render not a function, zoid error) shows a short notice
 * in place of the buttons instead of reaching RootErrorBoundary.
 */
export class PayPalErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.warn("PayPal widget failed; app kept running:", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <p className="notice error" role="status" data-testid={this.props.testId || "paypal-widget-error"}>
        {isEnglish()
          ? "PayPal is unavailable here right now. Reload the page to try again."
          : "PayPal est indisponible ici pour le moment. Rechargez la page pour réessayer."}
      </p>
    );
  }
}
