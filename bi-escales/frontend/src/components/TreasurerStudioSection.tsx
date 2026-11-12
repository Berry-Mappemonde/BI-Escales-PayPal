import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { StopNames } from "../utils/milestoneLabel";
import { featureAgStudioEnabled } from "../config/features";

// Compared inline so the build drops this import, and the Studio chunk, at 0 or unset.
const TreasurerStudio = lazy(() =>
  import.meta.env.VITE_ENABLE_AG_STUDIO === undefined ||
  import.meta.env.VITE_ENABLE_AG_STUDIO === "" ||
  import.meta.env.VITE_ENABLE_AG_STUDIO === "0"
    ? Promise.reject(new Error("AG Studio is off in this build"))
    : import("./TreasurerStudio"),
);

type BoundaryProps = { children: ReactNode; fallback: ReactNode };

/** A failed Studio load stays here instead of reaching RootErrorBoundary. */
class StudioErrorBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Renders nothing while the flag is off, so the Studio chunk is never requested. */
export function TreasurerStudioSection({ adminKey, demo, stopNames }: {
  adminKey: string;
  demo: boolean;
  stopNames?: StopNames;
}) {
  const { t } = useTranslation();
  const key = demo ? "" : adminKey.trim();
  const [session, setSession] = useState<{ key: string; demo: boolean } | null>(null);
  const open = session?.key === key && session.demo === demo;
  useEffect(() => { setSession(null); }, [key, demo]);
  const openRef = useRef<HTMLButtonElement>(null);

  if (!featureAgStudioEnabled() || (!key && !demo)) return null;

  const close = () => {
    setSession(null);
    openRef.current?.focus();
  };

  return (
    <section data-testid="treasurer-studio-section">
      <button
        ref={openRef}
        type="button"
        data-testid="treasurer-studio-open"
        aria-haspopup="dialog"
        onClick={() => setSession({ key, demo })}
      >
        {t("studio.open")}
      </button>
      {open ? (
        <StudioErrorBoundary fallback={<p className="notice error" role="alert">{t("studio.loadError")}</p>}>
          <Suspense fallback={<p className="rail-loading" role="status">{t("studio.loading")}</p>}>
            <TreasurerStudio adminKey={key} demo={demo} stopNames={stopNames} onClose={close} />
          </Suspense>
        </StudioErrorBoundary>
      ) : null}
    </section>
  );
}
