import { useTranslation } from "react-i18next";
import type { CaptainTrace, CaptainToolCall } from "../../api/types";
import "./captain-tool-trace.css";

export function CaptainToolTrace({ trace, modelTestId }: { trace: CaptainTrace; modelTestId?: string }) {
  const { t } = useTranslation();
  const payload = trace.paypal_tools && !Array.isArray(trace.paypal_tools) ? trace.paypal_tools : undefined;
  const calls: CaptainToolCall[] = payload?.calls ?? trace.paypal_tool_calls ?? (payload?.called ?? []).map((tool) => ({ tool }));
  // Prefer the server's exact label. Older responses can fall back to their exact model id.
  const label = trace.model_label || trace.model_source?.model || "rules";
  const latency = (ms?: number) => typeof ms === "number" && Number.isFinite(ms)
    ? `${Math.round(ms)} ms` : t("captainTrace.unavailable");
  return (
    <div className="captain-tool-trace">
      <p data-testid={modelTestId}>
        {label === "rules"
          ? t(trace.rule_by_design ? "captainTrace.fixedRule" : "captainCard.answeredByRules")
          : t("captainTrace.answeredBy", { model: label })}
        {" · "}{t("captainTrace.latency", { time: latency(trace.latency_ms) })}
      </p>
      <div data-testid="captain-paypal-tools">
        {payload?.client ? <span>{t("captainTrace.client", { client: payload.client })}</span> : null}
        {calls.length ? (
          <ul>
            {calls.map((call, index) => (
              <li key={`${call.tool}-${index}`}>
                <span>{call.tool}</span>{" · "}<code>{call.resource_id || "—"}</code>{" "}
                <span className="captain-tool-badge">{t("captainTrace.readOnly")}</span>
                {" · "}{latency(call.latency_ms)}
                {call.status === "error" ? <> · {t("captainTrace.failed")}</> : null}
                {call.debug_id ? <p>{t("captainTrace.debugId")}: <code>{call.debug_id}</code></p> : null}
              </li>
            ))}
          </ul>
        ) : <p>{t("captainTrace.noTools")}</p>}
      </div>
    </div>
  );
}
