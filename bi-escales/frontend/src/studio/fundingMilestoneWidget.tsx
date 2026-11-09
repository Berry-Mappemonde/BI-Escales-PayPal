import { useEffect, useState } from "react";
import type { AgWidgetField, AgWidgetParams } from "ag-studio";
import { useTranslation } from "react-i18next";
import { formatPledgeAmount, studioLanguage } from "./locale";
import { fundingGroups, type FundingGroup } from "./fundingMilestones";

function keyOf(field: AgWidgetField): string {
  const raw = field as unknown as Record<string, unknown>;
  return String(raw.fieldId || raw.id || raw.key || "");
}

const KEYS = ["status", "amount_eur", "net_eur", "kind", "target_id", "milestone_id"];

/** Custom AG Studio Agent Framework widget: ledger-grounded crowdfunding by project or milestone. */
export function FundingMilestoneWidget({ widgetApi }: AgWidgetParams) {
  const { i18n } = useTranslation();
  const language = studioLanguage(i18n.language);
  const [groups, setGroups] = useState<FundingGroup[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      widgetApi.setDisplayState("loading", { prominent: false });
      const source = widgetApi.getSchema().find((entry) => entry.id === "pledges");
      if (!source) {
        widgetApi.setDisplayState("incompleteDataMapping");
        return;
      }
      const fields = KEYS.map((key) => source.fields.find((field) => keyOf(field) === key || keyOf(field).endsWith(`.${key}`)))
        .filter((field): field is AgWidgetField => Boolean(field));
      if (fields.length < KEYS.length) {
        widgetApi.setDisplayState("incompleteDataMapping");
        return;
      }
      try {
        const response = await widgetApi.getData({ kind: "flat", fields });
        if (cancelled) return;
        const data = fundingGroups((response.results?.rows ?? []) as Record<string, unknown>[]);
        setGroups(data);
        setError(null);
        widgetApi.setDisplayState(data.length ? "displayed" : "noData");
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : String(cause));
          widgetApi.setDisplayState("displayed");
        }
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [widgetApi]);

  const headings = language === "fr"
    ? ["Projet / escale", "Encaissé", "Autorisé", "Enregistré (Vault)", "Libéré"]
    : ["Project / stop", "Captured", "Authorized", "Saved (Vault)", "Released"];
  const category = (kind: FundingGroup["kind"]) =>
    language === "fr"
      ? ({ project: "Projet", stop: "Escale", common: "Fonds commun" } as const)[kind]
      : ({ project: "Project", stop: "Stop", common: "Common fund" } as const)[kind];

  return (
    <div className="funding-milestone-widget" data-testid="funding-milestone-widget">
      <p className="validation-title">{language === "fr" ? "Financement par projet et escale" : "Funding by project and stop"}</p>
      <p className="validation-hint">
        {language === "fr"
          ? "Données du grand livre uniquement. Vault n'est ni encaissé ni autorisé. Aucun paiement depuis ce tableau."
          : "Ledger values only. Vault is neither captured nor authorized. This widget cannot initiate payments."}
      </p>
      {error ? <p className="notice error">{error}</p> : null}
      <div className="funding-milestone-scroll">
        <table>
          <thead><tr>{headings.map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>
            {groups.map((row) => (
              <tr key={`${row.kind}:${row.id}`}>
                <th scope="row"><span className="funding-kind">{category(row.kind)}</span> {row.id}</th>
                <td>{formatPledgeAmount(row.capturedEur, language)}</td>
                <td>{formatPledgeAmount(row.authorizedEur, language)}</td>
                <td>{formatPledgeAmount(row.savedEur, language)}</td>
                <td>{formatPledgeAmount(row.releasedEur, language)}</td>
              </tr>
            ))}
            {!groups.length ? <tr><td colSpan={5}>{language === "fr" ? "Aucune donnée" : "No ledger data"}</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
