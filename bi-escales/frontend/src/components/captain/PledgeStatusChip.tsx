import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "./captain-card.css";

const RING = { cx: 7, cy: 7, r: 5.5, stroke: "currentColor", strokeWidth: 1.5 };
const DISC = { cx: 7, cy: 7, r: 6.25, fill: "currentColor" };
const CUT = {
  stroke: "var(--pledge-chip-cut)",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

const returnArrow = (
  <>
    <circle {...DISC} />
    <path d="M5.3 3.9 3.8 5.4l1.5 1.5M3.9 5.4h4a2 2 0 0 1 0 4H6" {...CUT} />
  </>
);

/** One colour per meaning. Amber is money held, and nothing else. */
const STATES: Record<string, { label: string; color: string; glyph: ReactNode }> = {
  authorized: {
    label: "held",
    color: "var(--color-st-progress)",
    glyph: (
      <>
        <circle {...RING} />
        <path d="M7 3.75a3.25 3.25 0 0 1 0 6.5z" fill="currentColor" />
      </>
    ),
  },
  vaulted: {
    label: "saved",
    color: "var(--color-st-triage)",
    glyph: <circle {...RING} strokeDasharray="2.1 1.9" />,
  },
  captured: {
    label: "captured",
    color: "var(--color-st-done)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m4.4 7.1 1.75 1.75L9.6 5.4" {...CUT} />
      </>
    ),
  },
  voided: {
    label: "released",
    color: "var(--color-st-declined)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m5 5 4 4m0-4-4 4" {...CUT} />
      </>
    ),
  },
  refunded: { label: "refunded", color: "var(--color-st-review)", glyph: returnArrow },
  partially_refunded: { label: "partlyRefunded", color: "var(--color-st-review)", glyph: returnArrow },
  pending: { label: "pending", color: "var(--color-st-todo)", glyph: <circle {...RING} /> },
};

export function PledgeStatusChip({ status }: { status: string }) {
  const { t } = useTranslation();
  const state = STATES[status];
  const color = state?.color ?? "var(--color-st-todo)";

  return (
    <span className="pledge-chip" data-status={status} style={{ "--st": color } as CSSProperties}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        {state?.glyph ?? <circle {...RING} />}
      </svg>
      {state ? t(`captainCard.status.${state.label}`) : status}
    </span>
  );
}
