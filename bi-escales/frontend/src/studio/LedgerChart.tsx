import { useEffect, useRef } from "react";
import { AgCharts, AllEnterpriseModule, LicenseManager, ModuleRegistry } from "ag-charts-enterprise";
import { dashboardMoney, totalFields, type LedgerTotals } from "./dashboardLedger";
import { dashboardCopy } from "./dashboardLocale";

ModuleRegistry.registerModules(AllEnterpriseModule);

export default function LedgerChart({ totals, currency, language, licenseKey }: {
  totals: LedgerTotals;
  currency: string;
  language: string;
  licenseKey: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const copy = dashboardCopy(language);
  const hasAmounts = totalFields.some((field) => totals[field]);
  useEffect(() => {
    if (!container.current || !hasAmounts) return;
    LicenseManager.setLicenseKey(licenseKey);
    const styles = getComputedStyle(container.current);
    const chart = AgCharts.create({
      container: container.current,
      theme: document.documentElement.dataset.theme === "light" ? "ag-default" : "ag-default-dark",
      background: { fill: styles.getPropertyValue("--color-panel").trim() },
      data: totalFields.flatMap((field) => totals[field] === null
        ? [] : [{ status: copy[field], amount: totals[field] }]),
      series: [{
        type: "bar",
        direction: "horizontal",
        xKey: "status",
        yKey: "amount",
        fill: styles.getPropertyValue("--color-accent").trim(),
        tooltip: { renderer: ({ datum }) => ({
          title: datum.status,
          data: [{ label: currency, value: dashboardMoney(datum.amount, currency, language) }],
        }) },
      }],
      axes: {
        x: { type: "number", label: { formatter: ({ value }) => dashboardMoney(value, currency, language) } },
        y: { type: "category" },
      },
      animation: { enabled: false },
      legend: { enabled: false },
    });
    return () => chart.destroy();
  }, [totals, currency, language, copy, hasAmounts, licenseKey]);

  return (
    <section className="studio-chart" aria-label={copy.chartTitle}>
      <h3>{copy.chartTitle}</h3>
      {hasAmounts ? <div ref={container} className="studio-chart-canvas" /> : <p>{copy.chartEmpty}</p>}
    </section>
  );
}
