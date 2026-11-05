import type { AgWidgetParams } from "ag-studio";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import fr from "../i18n/locales/fr.json";
import i18n from "../i18n";
import { nextDataAgentAction, nextTreasurerAction } from "./agentPlan";
import { treasurerInitialState } from "./initialReport";
import { formatPledgeAmount, formatPledgeStatus } from "./locale";
import { pledgeStudioData } from "./pledgeData";
import { spokenTreasurerReply, treasurerAgentProfile, treasurerPromptStarters, treasurerSpeech } from "./treasurerAgent";
import { ValidationScoreboard } from "./validationWidget";
import { humanValidationWidget } from "./widgets";

const LANGUAGES = ["fr", "en"] as const;

function flatKeys(value: unknown, prefix = ""): string[] {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([key, child]) => flatKeys(child, prefix ? `${prefix}.${key}` : key));
}

function widgetTitle(language: (typeof LANGUAGES)[number], widgetId: string): string | undefined {
  const state = treasurerInitialState(language) as unknown as {
    pages: { widgets: Record<string, { format?: { title?: { text?: string } } }> }[];
  };
  return state.pages[0]?.widgets[widgetId]?.format?.title?.text;
}

function fieldFormatter(language: (typeof LANGUAGES)[number], fieldId: string) {
  const source = pledgeStudioData([], language).sources[0];
  const field = source?.fields?.find((entry) => entry.id === fieldId);
  return field?.createValueFormatter?.(undefined, {} as never);
}

afterEach(async () => {
  await i18n.changeLanguage("fr");
});

describe("copies studio", () => {
  it("aligne les clés françaises et anglaises", () => {
    expect(flatKeys(fr).sort()).toEqual(flatKeys(en).sort());
  });

  it.each(LANGUAGES)("formate 120 en %s", (language) => {
    expect(formatPledgeAmount(120, language)).toBe(language === "fr" ? "120,00 €" : "120.00 EUR");
    expect(formatPledgeAmount(1200.5, language)).toBe(language === "fr" ? "1200,50 €" : "1200.50 EUR");
  });

  it.each(LANGUAGES)("traduit titres, colonnes et statuts en %s", (language) => {
    const copy = language === "fr" ? fr.studio : en.studio;
    expect(widgetTitle(language, "validation")).toBe(copy.scoreTitle);
    expect(widgetTitle(language, "status-chart")).toBe(copy.chartTitle);
    expect(widgetTitle(language, "pledge-grid")).toBe(copy.gridTitle);

    const source = pledgeStudioData([], language).sources[0];
    expect(source?.name).toBe(copy.sourceName);
    expect(source?.fields?.map((field) => field.name)).toEqual([
      copy.colPledge,
      copy.colStatus,
      copy.colMilestone,
      copy.colAmount,
      copy.colNet,
      copy.colContributor,
      copy.colDescription,
    ]);
    expect(fieldFormatter(language, "amount_eur")?.(120)).toBe(
      language === "fr" ? "120,00 €" : "120.00 EUR",
    );
    expect(fieldFormatter(language, "net_eur")?.(120)).toBe(
      language === "fr" ? "120,00 €" : "120.00 EUR",
    );
    expect(fieldFormatter(language, "status")?.("authorized")).toBe(copy.held);
    expect(formatPledgeStatus("created", language)).toBe(copy.statusCreated);
    expect(formatPledgeStatus("vaulted", language)).toBe(copy.saved);
    expect(formatPledgeStatus("voided", language)).toBe(copy.released);
    expect(formatPledgeStatus("partially_refunded", language)).toBe(copy.statusPartiallyRefunded);

    const widget = humanValidationWidget(language);
    expect(widget.label).toBe(copy.widgetLabel);
    expect(widget.ai.description).toBe(copy.widgetAiDescription);
    const form = widget.form({ createDefaults: (value: unknown) => value } as never) as {
      dataMappingItems: { key: string; label: string }[];
    };
    expect(form.dataMappingItems).toEqual([
      { key: "status", label: copy.colStatus },
      { key: "amount", label: copy.colAmount },
    ]);
  });

  it.each(LANGUAGES)("fait parler l’agent trésorier en %s", async (language) => {
    const copy = language === "fr" ? fr.studio : en.studio;
    const other = language === "fr" ? en.studio : fr.studio;
    const starters = treasurerPromptStarters(language);
    expect(starters.map((starter) => starter.label)).toEqual([copy.promptTotals, copy.promptWidget]);
    expect(starters[0]?.prompt).toBe(copy.promptTotalsText);
    expect(nextTreasurerAction(starters[1]?.prompt ?? "", 1, language).kind).toBe("add-validation-widget");
    expect(treasurerSpeech(starters[1]?.prompt ?? "", 1, language)).toBe(copy.agentAdding);
    expect(treasurerSpeech(starters[0]?.prompt ?? "", 1, language)).toBe(copy.agentReply);
    expect(treasurerSpeech(starters[1]?.prompt ?? "", 2, language)).toBe(copy.agentReplyAdded);
    expect(treasurerSpeech("", 0, language)).toBe(copy.agentDelegating);
    expect(nextTreasurerAction("  ", 0, language)).toEqual({
      kind: "delegate-data",
      instructions: copy.delegateFallback,
    });
    expect(treasurerAgentProfile(language).name).toBe(copy.agentName);
    expect(nextDataAgentAction(1, "pledges.amount_eur", language).summary).toContain(copy.dataAgentSummaryEmpty);
    expect(nextDataAgentAction(1, "pledges.amount_eur", language).summary).toContain("pledges.amount_eur");
    expect(copy.agentReply).not.toBe(other.agentReply);

    await i18n.changeLanguage(language);
    expect(await spokenTreasurerReply(copy.promptWidgetText, 1)).toBe(copy.agentAdding);
    expect(await spokenTreasurerReply(copy.promptTotalsText, 1)).toBe(copy.agentReply);
    expect(await spokenTreasurerReply(copy.promptWidgetText, 2)).toBe(copy.agentReplyAdded);
    expect(await spokenTreasurerReply("totaux", 0)).toBe(copy.agentDelegating);
  });
});

describe("jauge de validation humaine", () => {
  function scoreboard() {
    const widgetApi = {
      setDisplayState: vi.fn(),
      getSchema: () => [],
      getData: vi.fn(async () => ({
        results: { rows: [{ status: "authorized", amount_eur: 120 }] },
      })),
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ValidationScoreboard
          {...({
            widgetApi,
            dataMapping: {
              status: [{ id: "status" }],
              amount: [{ id: "amount_eur" }],
            },
          } as AgWidgetParams)}
        />
      </I18nextProvider>,
    );
  }

  it("suit le français puis l’anglais", async () => {
    await i18n.changeLanguage("fr");
    scoreboard();
    expect(await screen.findByText("120,00 €")).toBeInTheDocument();
    expect(screen.getAllByText("0,00 €")).toHaveLength(3);
    expect(screen.getByText(fr.studio.scoreTitle)).toBeInTheDocument();
    expect(screen.getByText(fr.studio.scoreHint)).toBeInTheDocument();
    expect(screen.getByText(fr.studio.held)).toBeInTheDocument();
    expect(screen.getByText(fr.studio.saved)).toBeInTheDocument();
    expect(screen.getByText(fr.studio.captured)).toBeInTheDocument();
    expect(screen.getByText(fr.studio.released)).toBeInTheDocument();

    await i18n.changeLanguage("en");
    expect(await screen.findByText("120.00 EUR")).toBeInTheDocument();
    expect(screen.queryByText("120,00 €")).not.toBeInTheDocument();
    expect(screen.getAllByText("0.00 EUR")).toHaveLength(3);
    expect(screen.getByText(en.studio.scoreTitle)).toBeInTheDocument();
    expect(screen.getByText(en.studio.scoreHint)).toBeInTheDocument();
    expect(screen.getByText(en.studio.held)).toBeInTheDocument();
    expect(screen.getByText(en.studio.saved)).toBeInTheDocument();
    expect(screen.getByText(en.studio.captured)).toBeInTheDocument();
    expect(screen.getByText(en.studio.released)).toBeInTheDocument();
    expect(screen.queryByText(fr.studio.scoreHint)).not.toBeInTheDocument();
  });
});
