import { afterEach, describe, expect, it, vi } from "vitest";
import { ledgerPledges, ledgerTotals } from "./dashboardLedger";
import { askLedgerModel } from "./llmAdapter";

afterEach(() => vi.unstubAllGlobals());

describe("Studio ledger model requests", () => {
  it("sends only currency, matched topics, and aggregate amounts to the configured proxy", async () => {
    const base = {
      id: "private-pledge-id",
      intent: "CAPTURE",
      currency: "EUR",
      amount_eur: "30.00",
      description: "Private description",
      contributor: "Private Supporter",
      milestone_id: "private-milestone",
    };
    const rows = ledgerPledges([
      { ...base, status: "captured" },
      { ...base, status: "partially_refunded", refunded_amount_eur: "5.10" },
      { ...base, status: "authorized" },
      { ...base, status: "voided" },
    ]);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      status: "completed",
      output: [
        { type: "function_call", name: "query_data", arguments: "{}" },
        { type: "message", content: [{ type: "text", text: "The net captured amount is €54.90." }] },
      ],
    }));
    vi.stubGlobal("fetch", fetcher);
    const signal = new AbortController().signal;

    const summary = await askLedgerModel(
      "/llm", { currency: "EUR", totals: ledgerTotals(rows) },
      "How much was captured for Private Supporter (private@example.test)?", "en", signal,
    );

    expect(summary).toBe("The net captured amount is €54.90.");
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/llm", expect.objectContaining({ method: "POST", signal }));
    const body = String(fetcher.mock.calls[0][1]?.body);
    expect(body).not.toMatch(/private|how much/i);
    const { request } = JSON.parse(body);
    expect(request.toolChoice).toBe("none");
    expect(request).not.toHaveProperty("tools");
    expect(request.input).toHaveLength(1);
    expect(JSON.parse(request.input[0].content[0].text)).toEqual({
      currency: "EUR",
      focus: ["captured"],
      amounts: { captured: 54.9, authorized: 30, vaulted: 0, voided: 30, refunded: 5.1 },
    });
  });

  it("preserves unavailable totals and falls back when the proxy rejects a request", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const totals = { ...ledgerTotals([]), captured: null, refunded: null };

    expect(await askLedgerModel("/llm", { currency: "EUR", totals }, "Montants remboursés", "fr")).toBeUndefined();
    const { request } = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
    expect(request.instructions).toContain("Reply in French");
    expect(JSON.parse(request.input[0].content[0].text)).toMatchObject({
      focus: ["refunded"],
      amounts: { captured: null, refunded: null },
    });
  });
});
