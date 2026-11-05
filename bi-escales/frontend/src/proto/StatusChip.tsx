import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";

export type ChipStatus = "en_route" | "held" | "saved" | "captured" | "released" | "refunded";

const RING = { cx: 7, cy: 7, r: 5.5, stroke: "currentColor", strokeWidth: 1.5 };
const DISC = { cx: 7, cy: 7, r: 6.25, fill: "currentColor" };
const CUT = {
  stroke: "var(--color-canvas)",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

/**
 * Meridian's glyphs on their 14px grid. En route (forward arrow) and Refunded
 * (return arrow) are new, drawn to match. Amber means money held, and nothing else.
 */
const STATUS: Record<ChipStatus, { color: string; glyph: ReactNode }> = {
  en_route: {
    color: "var(--color-st-route)",
    glyph: (
      <>
        <circle {...RING} />
        <path
          d="M4.6 7h4.6M7.4 5.2 9.2 7 7.4 8.8"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </>
    ),
  },
  held: {
    color: "var(--color-st-progress)",
    glyph: (
      <>
        <circle {...RING} />
        <path d="M7 3.75a3.25 3.25 0 0 1 0 6.5z" fill="currentColor" />
      </>
    ),
  },
  saved: {
    color: "var(--color-st-triage)",
    glyph: <circle {...RING} strokeDasharray="2.1 1.9" />,
  },
  captured: {
    color: "var(--color-st-done)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m4.4 7.1 1.75 1.75L9.6 5.4" {...CUT} />
      </>
    ),
  },
  released: {
    color: "var(--color-st-declined)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m5 5 4 4m0-4-4 4" {...CUT} />
      </>
    ),
  },
  refunded: {
    color: "var(--color-st-review)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="M5.3 3.9 3.8 5.4l1.5 1.5M3.9 5.4h4a2 2 0 0 1 0 4H6" {...CUT} />
      </>
    ),
  },
};

export function StatusGlyph({ status }: { status: ChipStatus }) {
  const { color, glyph } = STATUS[status];
  return (
    <svg
      className="proto-glyph"
      style={{ color }}
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
      data-glyph={status}
    >
      {glyph}
    </svg>
  );
}

export function StatusChip({ status }: { status: ChipStatus }) {
  const { t } = useTranslation();
  return (
    <span className="proto-chip" style={{ "--st": STATUS[status].color } as CSSProperties}>
      <StatusGlyph status={status} />
      {t(`status.${status}`)}
    </span>
  );
}
