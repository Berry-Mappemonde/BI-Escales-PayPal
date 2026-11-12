import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  demoCancelStop,
  demoResetStop,
  demoSimulateArrival,
  type DemoStopAction,
  type DemoStopMomentResponse,
} from "../api/escales";

const DEMO_STOP_ID = "dep-la-rochelle";
/** What a reader sees; the id above is for the API only. */
const DEMO_STOP_NAME = "La Rochelle";

function formatNote(actions: DemoStopAction[], t: (key: string, opts?: Record<string, unknown>) => string): string {
  const lines: string[] = [];
  for (const row of actions) {
    if (row.action === "capture" && row.capture_id) {
      lines.push(
        t("treasurer.demoStop.captureLine", {
          pledgeId: row.pledge_id,
          captureId: row.capture_id,
        }),
      );
    }
    if (row.action === "void" && row.void_id) {
      lines.push(
        t("treasurer.demoStop.voidLine", {
          pledgeId: row.pledge_id,
          voidId: row.void_id,
        }),
      );
    }
  }
  return lines.join("\n");
}

export interface DemoStopMomentProps {
  /** Treasurer key: the judge-moment routes capture and void, so they need it. */
  adminKey: string;
  onRefresh: () => void;
}

export function DemoStopMoment({ adminKey, onRefresh }: DemoStopMomentProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [settleNote, setSettleNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const noKey = !adminKey.trim();

  const run = useCallback(
    async (call: () => Promise<DemoStopMomentResponse>) => {
      setBusy(true);
      setError(null);
      try {
        const body = await call();
        const actions = body.actions ?? [];
        setSettleNote(
          actions.length
            ? formatNote(actions, t)
            : t("treasurer.demoStop.emptyActions"),
        );
        onRefresh();
      } catch (err) {
        setSettleNote(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [onRefresh, t],
  );

  return (
    <section className="demo-stop-moment stack-form" data-testid="demo-stop-moment">
      <h3>{t("treasurer.demoStop.heading")}</h3>
      <p className="hint">{t("treasurer.demoStop.hint", { name: DEMO_STOP_NAME })}</p>
      <div className="demo-stop-moment-actions">
        <button
          type="button"
          data-testid="demo-stop-simulate-arrival"
          disabled={busy || noKey}
          onClick={() => run(() => demoSimulateArrival(DEMO_STOP_ID, adminKey))}
        >
          {t("treasurer.demoStop.simulateArrival")}
        </button>
        <button
          type="button"
          data-testid="demo-stop-cancel"
          disabled={busy || noKey}
          onClick={() => run(() => demoCancelStop(DEMO_STOP_ID, adminKey))}
        >
          {t("treasurer.demoStop.cancelStop")}
        </button>
        <button
          type="button"
          data-testid="demo-stop-reset"
          disabled={busy || noKey}
          onClick={() => run(() => demoResetStop(DEMO_STOP_ID, adminKey))}
        >
          {t("treasurer.demoStop.resetDemo")}
        </button>
      </div>
      {busy ? (
        <p className="hint" role="status" data-testid="demo-stop-working">
          {t("treasurer.demoStop.working")}
        </p>
      ) : null}
      {settleNote ? (
        <p className="notice treasurer-settle-note" data-testid="demo-stop-settle-note">
          {settleNote.split("\n").map((line, index) => (
            <span key={`${index}-${line}`} className="settle-note-line">
              {line}
              {index < settleNote.split("\n").length - 1 ? <br /> : null}
            </span>
          ))}
        </p>
      ) : null}
      {error ? (
        <p className="notice error" data-testid="demo-stop-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}
