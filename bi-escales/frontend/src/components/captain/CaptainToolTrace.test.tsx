import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../../i18n";
import { CaptainToolTrace } from "./CaptainToolTrace";

async function show(lang: string, trace: Parameters<typeof CaptainToolTrace>[0]["trace"]) {
  await i18n.changeLanguage(lang);
  render(<I18nextProvider i18n={i18n}><CaptainToolTrace trace={trace} /></I18nextProvider>);
}

describe("Captain tool trace", () => {
  it.each([['en', 'Read-only'], ['fr', 'Lecture seule']])('shows exact API model, resource, latency and debug_id in %s', async (lang, badge) => {
    const label = "NVIDIA NIM — nvidia/nemotron-3.5-lightning-30b-a3b";
    await show(lang, {
      model_label: label, model_source: { provider: 'nim', model: 'wrong-super-model' }, latency_ms: 125,
      paypal_tool_calls: [{ tool: 'orders.get', resource_id: 'ORDER-42', latency_ms: 23, status: 'error', debug_id: 'DEBUG-42' }],
    });
    expect(screen.getByText(new RegExp(label))).toBeInTheDocument();
    expect(screen.queryByText(/wrong-super-model/)).toBeNull();
    expect(screen.getByText('ORDER-42')).toBeInTheDocument();
    expect(screen.getByText(badge)).toBeInTheDocument();
    expect(screen.getByText('DEBUG-42')).toBeInTheDocument();
    expect(screen.getByText(/125 ms/)).toBeInTheDocument();
    expect(screen.getByText(/23 ms/)).toBeInTheDocument();
  });

  it('identifies rules and an empty tool trace without inventing latency', async () => {
    await show('en', { model_label: 'rules', paypal_tools: { calls: [] } });
    expect(screen.getByText(/Answered by the rules, no model/)).toBeInTheDocument();
    expect(screen.getByText('No PayPal tools called')).toBeInTheDocument();
    expect(screen.getByText(/Latency: Unavailable/)).toBeInTheDocument();
  });
});
