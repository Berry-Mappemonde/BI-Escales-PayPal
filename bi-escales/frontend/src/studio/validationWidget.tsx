import { useEffect, useState } from "react";
import type { AgWidgetField, AgWidgetParams } from "ag-studio";
import { useTranslation } from "react-i18next";
import { formatPledgeAmount } from "./locale";
import { totalsFromStudioRows, type StatusTotals } from "./pledgeRows";

const EMPTY: StatusTotals = { held: 0, saved: 0, captured: 0, released: 0 };

function mappedFields(dataMapping: AgWidgetParams["dataMapping"]): AgWidgetField[] {
  const bag = dataMapping as { status?: AgWidgetField[]; amount?: AgWidgetField[] };
  return [...(bag.status ?? []), ...(bag.amount ?? [])];
}

function fieldKey(field: AgWidgetField): string {
  if ("fieldId" in field && typeof field.fieldId === "string") return field.fieldId;
  if ("id" in field && typeof field.id === "string") return field.id;
  if ("key" in field && typeof field.key === "string") return field.key;
  return "";
}

function schemaFields(widgetApi: AgWidgetParams["widgetApi"]): AgWidgetField[] {
  const tables = widgetApi.getSchema();
  const table = tables.find((entry) => entry.id === "pledges") ?? tables[0];
  if (!table) return [];
  const status = table.fields.find((field) => /status$/i.test(fieldKey(field)));
  const amount =
    table.fields.find((field) => /net_eur$/i.test(fieldKey(field))) ??
    table.fields.find((field) => /amount/i.test(fieldKey(field)));
  return [status, amount].filter((field): field is AgWidgetField => Boolean(field));
}

export function ValidationScoreboard(props: AgWidgetParams) {
  const { t, i18n } = useTranslation();
  const { widgetApi, dataMapping, format } = props;
  const [totals, setTotals] = useState<StatusTotals>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      widgetApi.setDisplayState("loading", { prominent: false });
      const fields = mappedFields(dataMapping);
      const queryFields = fields.length > 0 ? fields : schemaFields(widgetApi);
      if (queryFields.length === 0) {
        widgetApi.setDisplayState("incompleteDataMapping");
        return;
      }
      try {
        const response = await widgetApi.getData({ kind: "flat", fields: queryFields });
        if (cancelled) return;
        const rows = response.results?.rows ?? [];
        setTotals(rows.length === 0 ? EMPTY : totalsFromStudioRows(rows));
        setError(null);
        widgetApi.setDisplayState(rows.length === 0 ? "noData" : "displayed");
      } catch (cause) {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : String(cause));
        widgetApi.setDisplayState("displayed");
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [widgetApi, dataMapping]);

  const title =
    format && typeof format === "object" && "title" in format && format.title && typeof format.title === "object" && "text" in format.title && typeof format.title.text === "string"
      ? format.title.text
      : t("studio.scoreTitle");
  const max = Math.max(totals.held, totals.saved, totals.captured, totals.released, 1);
  const bars: { key: keyof StatusTotals; label: string; tone: string }[] = [
    { key: "held", label: t("studio.held"), tone: "tone-auth" },
    { key: "saved", label: t("studio.saved"), tone: "tone-saved" },
    { key: "captured", label: t("studio.captured"), tone: "tone-cap" },
    { key: "released", label: t("studio.released"), tone: "tone-void" },
  ];

  return (
    <div className="validation-scoreboard" data-testid="validation-scoreboard">
      <p className="validation-title">{title}</p>
      <p className="validation-hint">{t("studio.scoreHint")}</p>
      {error ? <p className="notice error">{error}</p> : null}
      <ul>
        {bars.map((bar) => (
          <li key={bar.key}>
            <span>{bar.label}</span>
            <span>{formatPledgeAmount(totals[bar.key], i18n.language)}</span>
            <div className="gauge-track">
              <div
                className={`gauge-fill ${bar.tone}`}
                style={{ width: `${Math.round((totals[bar.key] / max) * 100)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
