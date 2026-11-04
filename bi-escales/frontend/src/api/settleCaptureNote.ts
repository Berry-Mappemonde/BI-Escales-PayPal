import type { TFunction } from "i18next";
import type { ClockSettleResult } from "./types";

/** Turn POST /clock/settle actions into a treasurer-visible summary (FR/EN via i18n). */
export function formatSettleCaptureNote(t: TFunction, settled: ClockSettleResult | undefined): string {
  if (!settled?.actions?.length) {
    return t("treasurer.settleDoneEmpty");
  }
  const captures = settled.actions.filter((row) => row.action === "capture");
  if (!captures.length) {
    const waits = settled.actions.filter((row) => row.action === "wait").length;
    if (waits) {
      return t("treasurer.settleDoneWait", { count: waits });
    }
    const errors = settled.actions.filter((row) => row.action === "error");
    if (errors.length) {
      return t("treasurer.settleDoneErrors", {
        detail: errors.map((row) => row.detail || row.pledge_id).join("; "),
      });
    }
    return t("treasurer.settleDoneEmpty");
  }
  const lines = captures.map((row) =>
    t("treasurer.settleCaptureRow", {
      status: row.status || "captured",
      captureId: row.capture_id || "—",
      pledgeId: row.pledge_id,
    }),
  );
  return [t("treasurer.settleDoneCaptures", { count: captures.length }), ...lines].join("\n");
}
