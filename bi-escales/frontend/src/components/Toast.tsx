import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import "../styles/toast.css";

export type ToastVariant = "info" | "success" | "error" | "held" | "warn";

export interface ToastItem {
  id: string;
  title: string;
  detail?: string;
  variant: ToastVariant;
  /** data-testid forwarded to the toast element */
  testId?: string;
}

/* ── SVG status icons (inline, 16×16) ─────────────────────────── */

const IconInfo = () => (
  <svg className="toast-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 7v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="8" cy="4.75" r="0.85" fill="currentColor" />
  </svg>
);

const IconSuccess = () => (
  <svg className="toast-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 8.25l2 2 4-4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const IconError = () => (
  <svg className="toast-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5.75 5.75l4.5 4.5M10.25 5.75l-4.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const IconHeld = () => (
  <svg className="toast-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 4.5v4l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const IconWarn = () => (
  <svg className="toast-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M8 2.5L14.2 13.5H1.8L8 2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M8 6.5V9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="8" cy="11.5" r="0.75" fill="currentColor" />
  </svg>
);

const iconMap: Record<ToastVariant, React.FC> = {
  info: IconInfo,
  success: IconSuccess,
  error: IconError,
  held: IconHeld,
  warn: IconWarn,
};

const AUTO_DISMISS_MS = 6000;

/* ── Single toast card ────────────────────────────────────────── */

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [exiting, setExiting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dismissedRef = useRef(false);
  const hoveredRef = useRef(false);
  const remainRef = useRef(AUTO_DISMISS_MS);
  const startRef = useRef(Date.now());

  const autoDismisses = item.variant !== "error";

  const triggerDismiss = useCallback(() => {
    if (dismissedRef.current) return;
    dismissedRef.current = true;
    onDismiss(item.id);
  }, [item.id, onDismiss]);

  const handleDismiss = useCallback(() => {
    setExiting(true);
    // Timeout fallback for reduced motion or environments where animationend doesn't fire
    setTimeout(triggerDismiss, 130);
  }, [triggerDismiss]);

  const startTimer = useCallback(() => {
    if (!autoDismisses) return;
    startRef.current = Date.now();
    timerRef.current = setTimeout(() => {
      setExiting(true);
      setTimeout(triggerDismiss, 130);
    }, remainRef.current);
  }, [autoDismisses, triggerDismiss]);

  const pauseTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
      remainRef.current -= Date.now() - startRef.current;
      if (remainRef.current < 0) remainRef.current = 0;
    }
  }, []);

  useEffect(() => {
    startTimer();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [startTimer]);

  const Icon = iconMap[item.variant];

  return (
    <div
      className={`toast-card toast-card--${item.variant}${exiting ? " toast-card--exit" : ""}`}
      role="status"
      aria-live={item.variant === "error" ? "assertive" : "polite"}
      data-testid={item.testId}
      onMouseEnter={() => {
        hoveredRef.current = true;
        pauseTimer();
      }}
      onMouseLeave={() => {
        hoveredRef.current = false;
        startTimer();
      }}
      onAnimationEnd={(e) => {
        if (e.animationName === "toast-out") {
          triggerDismiss();
        }
      }}
    >
      <span className={`toast-status-icon toast-status-icon--${item.variant}`}>
        <Icon />
      </span>
      <div className="toast-body">
        <span className="toast-title">{item.title}</span>
        {item.detail ? <span className="toast-detail">{item.detail}</span> : null}
      </div>
      <button
        type="button"
        className="toast-close"
        data-testid="dismiss-notices"
        aria-label={t("app.dismissNoticeAria", t("app.dismissNotice"))}
        onClick={handleDismiss}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}

/* ── Toast container ──────────────────────────────────────────── */

export function ToastContainer({
  items,
  onDismiss,
}: {
  items: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div className="toast-container" aria-label="Notifications">
      {items.map((item) => (
        <ToastCard key={item.id} item={item} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
