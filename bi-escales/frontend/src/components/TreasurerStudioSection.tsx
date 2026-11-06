import { Component, lazy, Suspense, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { PublicPledge } from "../api/types";
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

  componentDidCatch(error: Error) {
    console.warn("AG Studio failed; app kept running:", error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Renders nothing while the flag is off, so the Studio chunk is never requested. */
export function TreasurerStudioSection({ pledges }: { pledges: PublicPledge[] }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const openRef = useRef<HTMLButtonElement>(null);

  if (!featureAgStudioEnabled()) return null;

  const close = () => {
    setOpen(false);
    openRef.current?.focus();
  };

  return (
    <section className="panel" data-testid="treasurer-studio-section">
      <button
        ref={openRef}
        type="button"
        data-testid="treasurer-studio-open"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {t("studio.open")}
      </button>
      {open ? (
        <StudioErrorBoundary fallback={<p className="notice error">{t("studio.loadError")}</p>}>
          <Suspense fallback={<p className="rail-loading" role="status">{t("studio.loading")}</p>}>
            <TreasurerStudio key={i18n.language} pledges={pledges} onClose={close} />
          </Suspense>
        </StudioErrorBoundary>
      ) : null}
    </section>
  );
}
