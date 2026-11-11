/**
 * Demo treasurer (issue #145): the controls on a pledge this browser made itself.
 * One next step at a time (simulate the arrival, approve, capture), with "void" beside
 * it while the money is held, and "refund" once it is captured. The server decides what
 * may be done next and checks on every call that the pledge is this browser's own.
 */
import { useTranslation } from "react-i18next";
import type { DemoPlay, DemoPlayAction } from "../api/demoPlay";

export interface DemoOwnPledgeActionsProps {
  play: DemoPlay;
  /** True while any action of the queue is running. */
  busy: boolean;
  onRun: (action: DemoPlayAction) => void;
}

/** Where the pledge stands, as one line. */
function stepKey(play: DemoPlay): string | null {
  if (play.actions.includes("simulate_arrival")) return "treasurer.demoPlay.stepHeld";
  if (play.actions.includes("approve")) return "treasurer.demoPlay.stepArrived";
  if (play.actions.includes("capture")) return "treasurer.demoPlay.stepApproved";
  if (play.actions.includes("refund")) return "treasurer.demoPlay.stepCaptured";
  return null;
}

export function DemoOwnPledgeActions({ play, busy, onRun }: DemoOwnPledgeActionsProps) {
  const { t } = useTranslation();
  const step = stepKey(play);
  if (!play.actions.length) return null;
  return (
    <div className="demo-own-actions" data-testid={`own-actions-${play.pledge_id}`}>
      {step ? <p className="hint demo-own-step" data-testid={`own-step-${play.pledge_id}`}>{t(step)}</p> : null}
      <div className="demo-own-buttons">
        {play.actions.map((action) => (
          <button
            key={action}
            type="button"
            className={action === "void" ? "secondary" : undefined}
            data-testid={`own-${action}-${play.pledge_id}`}
            disabled={busy}
            onClick={() => onRun(action)}
          >
            {t(`treasurer.demoPlay.actions.${action}`)}
          </button>
        ))}
      </div>
    </div>
  );
}
