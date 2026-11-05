import { useTranslation } from "react-i18next";
import "../captain/captain-card.css";
import "./stop-panel.css";

const RING = { cx: 7, cy: 7, r: 5.5, stroke: "currentColor", strokeWidth: 1.5 };
const DISC = { cx: 7, cy: 7, r: 6.25, fill: "currentColor" };
const CUT = {
  stroke: "var(--pledge-chip-cut)",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

/** Teal is the voyage. Amber stays Held only, green Captured, grey Released. */
const STATES = {
  upcoming: { color: "var(--color-st-todo)", glyph: <circle {...RING} /> },
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
  arrived: {
    color: "var(--color-st-route)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m4.4 7.1 1.75 1.75L9.6 5.4" {...CUT} />
      </>
    ),
  },
  cancelled: {
    color: "var(--error)",
    glyph: (
      <>
        <circle {...DISC} />
        <path d="m5 5 4 4m0-4-4 4" {...CUT} />
      </>
    ),
  },
};

export function StopStatusChip({ status }) {
  const { t } = useTranslation();
  const state = STATES[status];
  if (!state) return null;
  return (
    <span className="pledge-chip stop-chip" data-status={status} style={{ "--st": state.color }}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        {state.glyph}
      </svg>
      {t(`stopPanel.status.${status}`)}
    </span>
  );
}
