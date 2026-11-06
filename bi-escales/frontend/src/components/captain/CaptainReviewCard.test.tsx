import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { approveCaptainReview, captainReview, capturePledge, fetchSchedule, voidPledge } from "../../api/escales";
import type { CaptainProposal, PublicPledge } from "../../api/types";
import en from "../../i18n/locales/en.json";
import fr from "../../i18n/locales/fr.json";
import i18n from "../../i18n";
import { TreasurerQueue } from "../TreasurerQueue";
import { PledgeStatusChip } from "./PledgeStatusChip";
import chipSource from "./PledgeStatusChip.tsx?raw";

vi.mock("../../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
  fetchSchedule: vi.fn(),
  refundPledge: vi.fn(),
  voidPledge: vi.fn(),
}));

const STOP = "dep-ajaccio-corse";

function hold(id: string, amount: string, status: PublicPledge["status"] = "authorized"): PublicPledge {
  return { id, status, intent: "AUTHORIZE", currency: "EUR", amount_eur: amount, description: "milles", milestone_id: STOP };
}

const review: CaptainProposal = {
  milestone_id: STOP,
  proposal: "wait",
  report: "The boat has not reached Ajaccio yet.",
  justification: "The boat has not reached Ajaccio yet. Decision: wait.",
  pledge_ids: ["p-1", "p-2"],
  pending_authorizations: [
    { pledge_id: "p-1", amount_eur: "20.00", authorization_expires_at: "2026-12-03T00:00:00Z" },
    { pledge_id: "p-2", amount_eur: "12.50", authorization_expires_at: "2026-12-11T00:00:00Z" },
  ],
  paypal_tool_calls: [
    { tool: "orders.get", resource_id: "ORDER-1" },
    { tool: "authorizations.get", resource_id: "7AG23904" },
  ],
  model_source: { provider: "nim", model: "private/nvidia/nemotron-3.5-super-120b-a12b" },
  llm_proposal: { proposal: "wait", reason: "The authorization is still valid." },
};

/** Behaves like the app: a voided pledge leaves the queue. */
function Queue({ initial, adminKey = "key" }: { initial: PublicPledge[]; adminKey?: string }) {
  const [pledges, setPledges] = useState(initial);
  return (
    <I18nextProvider i18n={i18n}>
      <TreasurerQueue
        pledges={pledges}
        adminKey={adminKey}
        onRefresh={() => {}}
        onUpdated={(updated) =>
          setPledges((rows) => rows.map((row) => (row.id === updated.id ? updated : row)))
        }
      />
    </I18nextProvider>
  );
}

const card = () => within(screen.getByTestId(`captain-card-${STOP}`));

async function openCard(initial = [hold("p-1", "20.00"), hold("p-2", "12.50")]) {
  render(<Queue initial={initial} />);
  await screen.findByTestId(`captain-proposal-${STOP}`);
}

describe("Captain review card", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.clearAllMocks();
    vi.mocked(captainReview).mockResolvedValue(review);
    vi.mocked(fetchSchedule).mockResolvedValue({
      export: { escales: [{ milestone_id: STOP, name: "Ajaccio (Corse)", arrival_iso: "2026-11-28T22:02:54.002Z" }] },
    });
    vi.mocked(voidPledge).mockImplementation(async (id) => ({ ...hold(id, "0.00"), status: "voided" }));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  describe("citations", () => {
    it("cites each claim, built only from the review and schedule", async () => {
      await openCard();
      await card().findByText(/Scheduled arrival: 28 Nov/);
      expect(card().getByRole("button", { name: "Source 1: Schedule" })).toBeInTheDocument();
      expect(card().getByText(/2 holds · €32\.50 total/)).toBeInTheDocument();
      expect(card().getByText(/Valid to 3 Dec/)).toBeInTheDocument();
      expect(card().getAllByRole("button", { name: "Source 2: pending_authorizations" })).toHaveLength(2);
      expect(card().getByRole("button", { name: "Source 3: authorizations.get" })).toBeInTheDocument();
      expect(card().getByRole("button", { name: "Source 4: orders.get" })).toBeInTheDocument();
      expect(within(screen.getByTestId(`captain-card-${STOP}`).querySelector(".captain-sources") as HTMLElement).getByText("7AG23904")).toBeInTheDocument();
      expect(within(screen.getByTestId(`captain-card-${STOP}`).querySelector(".captain-sources") as HTMLElement).getByText("ORDER-1")).toBeInTheDocument();
    });

    it("says PayPal was read, never what it answered", async () => {
      await openCard();
      expect(card().getByText(/PayPal order read/)).toBeInTheDocument();
      expect(screen.getByTestId(`captain-card-${STOP}`).textContent).not.toMatch(/\bapproved\b/i);
    });

    it("moves to the cited source row", async () => {
      await openCard();
      const cite = await card().findByRole("button", { name: "Source 3: authorizations.get" });
      fireEvent.click(cite);
      const sources = within(screen.getByTestId(`captain-card-${STOP}`).querySelector(".captain-sources") as HTMLElement);
      const row = sources.getByText("authorizations.get").closest("li");
      expect(row).toHaveFocus();
      expect(row).toHaveAttribute("data-active");
    });

    it("leaves the arrival claim out when the schedule is unavailable", async () => {
      vi.mocked(fetchSchedule).mockRejectedValue(new Error("down"));
      await openCard();
      expect(card().queryByText(/Scheduled arrival/)).toBeNull();
      expect(card().getAllByRole("button", { name: "Source 1: pending_authorizations" })).toHaveLength(2);
    });

    it("shows the report without the decision line, and the advisory reason as such", async () => {
      await openCard();
      expect(card().getByText("The boat has not reached Ajaccio yet.")).toBeInTheDocument();
      expect(card().getByText(/The authorization is still valid\./)).toHaveTextContent("Model's note (advisory):");
    });

    it("hides an advisory the backend dropped", async () => {
      vi.mocked(captainReview).mockResolvedValue({ ...review, llm_proposal: { proposal: null, reason: null } });
      await openCard();
      expect(card().queryByText(/advisory/)).toBeNull();
    });

    it("keeps milestones separate: each card cites its own PayPal ids", async () => {
      vi.mocked(captainReview).mockImplementation(async (id) => ({
        ...review,
        milestone_id: id,
        paypal_tool_calls: [{ tool: "orders.get", resource_id: `ORDER-${id}` }],
      }));
      render(<Queue initial={[hold("p-1", "20.00"), { ...hold("p-2", "5.00"), milestone_id: "dep-other" }]} />);
      const first = await screen.findByTestId(`captain-card-${STOP}`);
      const second = await screen.findByTestId("captain-card-dep-other");
      await within(first).findAllByText(`ORDER-${STOP}`);
      await within(second).findAllByText("ORDER-dep-other");
      expect(within(first).queryByText("ORDER-dep-other")).toBeNull();
    });
  });

  describe("who answered", () => {
    it("names the model and provider under the card", async () => {
      await openCard();
      expect(screen.getByTestId(`captain-answered-${STOP}`)).toHaveTextContent("Answered by private/nvidia/nemotron-3.5-super-120b-a12b");
    });

    it("says so when the rules answered", async () => {
      vi.mocked(captainReview).mockResolvedValue({ ...review, model_source: { provider: "rules", model: "" } });
      await openCard();
      expect(screen.getByTestId(`captain-answered-${STOP}`)).toHaveTextContent("Answered by the rules, no model");
    });
  });

  describe("override releases only", () => {
    it("shows the count and total before any timer, and offers nothing else", async () => {
      await openCard();
      fireEvent.click(screen.getByTestId(`captain-override-${STOP}`));
      const release = screen.getByTestId(`captain-release-${STOP}`);
      expect(release.closest("[role=group]")).toHaveTextContent("Void 2 holds totalling €32.50? Once sent, this can't be undone.");
      const buttons = within(release.parentElement as HTMLElement).getAllByRole("button");
      expect(buttons.map((button) => button.textContent)).toEqual(["Confirm", "Cancel"]);
      expect(card().queryByRole("button", { name: /capture/i })).toBeNull();
      expect(voidPledge).not.toHaveBeenCalled();
    });

    it("offers no capture even when the Captain proposes capture", async () => {
      vi.mocked(captainReview).mockResolvedValue({ ...review, proposal: "capture" });
      await openCard();
      expect(card().queryByRole("button", { name: /capture/i })).toBeNull();
      fireEvent.click(screen.getByTestId(`captain-override-${STOP}`));
      expect(card().queryByRole("button", { name: /capture/i })).toBeNull();
    });

    it("has no instant void on the rows", async () => {
      await openCard();
      const row = within(screen.getByTestId("queue-row-p-1"));
      expect(row.queryByRole("button")).toBeNull();
    });

    it("counts held and saved pledges, and skips a pending one", async () => {
      await openCard([hold("p-1", "20.00"), hold("p-v", "10.00", "vaulted"), hold("p-p", "5.00", "pending")]);
      fireEvent.click(screen.getByTestId(`captain-override-${STOP}`));
      expect(screen.getByTestId(`captain-release-${STOP}`).closest("[role=group]")).toHaveTextContent("Void 2 holds totalling €30?");
    });

    it("stays available when the review failed, so holds can always be released", async () => {
      vi.mocked(captainReview).mockRejectedValue(new Error("boom"));
      render(<Queue initial={[hold("p-1", "20.00")]} />);
      await card().findByText(/No review is available/);
      expect(screen.getByTestId(`captain-approve-${STOP}`)).toBeDisabled();
      expect(screen.getByTestId(`captain-override-${STOP}`)).not.toBeDisabled();
    });

    it("shows the rule once when the report already explains capture", async () => {
      vi.mocked(captainReview).mockResolvedValue({ ...review, report: `Arrival verified. ${en.captainCard.rule}` });
      await openCard();
      expect(card().getAllByText(en.captainCard.rule, { exact: false })).toHaveLength(1);
    });

    it("states the capture rule in the agreed words, in both languages", async () => {
      await openCard();
      expect(card().getByText("Captured on arrival (on departure for cabins), only after a person approves.")).toBeInTheDocument();
      expect(JSON.stringify(en.captainCard)).not.toMatch(/evidence/i);
      expect(JSON.stringify(fr.captainCard)).not.toMatch(/preuve/i);
    });
  });

  describe("undo window", () => {
    const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

    async function startRelease(initial?: PublicPledge[]) {
      await openCard(initial);
      vi.useFakeTimers();
      fireEvent.click(screen.getByTestId(`captain-override-${STOP}`));
      fireEvent.click(screen.getByTestId(`captain-release-${STOP}`));
    }

    it("counts down with Undo and sends nothing before 5 s", async () => {
      await startRelease();
      const countdown = screen.getByTestId(`captain-countdown-${STOP}`);
      expect(countdown).toHaveTextContent("Releasing in 5 s");
      expect(card().getByRole("button", { name: "Undo" })).toHaveFocus();
      await wait(1000);
      expect(screen.getByTestId(`captain-countdown-${STOP}`)).toHaveTextContent("Releasing in 4 s");
      await wait(3900);
      expect(voidPledge).not.toHaveBeenCalled();
    });

    it("voids every hold after 5 s, then is final and keeps the result", async () => {
      await startRelease();
      await wait(5000);
      expect(voidPledge).toHaveBeenCalledTimes(2);
      expect(voidPledge).toHaveBeenCalledWith("p-1", "key", undefined);
      expect(voidPledge).toHaveBeenCalledWith("p-2", "key", undefined);
      const result = screen.getByTestId(`captain-card-${STOP}`);
      expect(within(result).getByRole("status")).toHaveTextContent("2 holds released · €32.50 total. This is final.");
      expect(within(result).queryByRole("button", { name: "Undo" })).toBeNull();
      expect(within(result).queryByRole("button", { name: "Approve" })).toBeNull();
      expect(within(result).queryByRole("button", { name: "Void holds…" })).toBeNull();
    });

    it("undo cancels for good and sends nothing", async () => {
      await startRelease();
      await wait(3000);
      fireEvent.click(card().getByRole("button", { name: "Undo" }));
      await wait(10000);
      expect(voidPledge).not.toHaveBeenCalled();
      expect(screen.getByTestId(`captain-approve-${STOP}`)).toHaveFocus();
    });

    it("announces once rather than every second", async () => {
      await startRelease();
      const announced = card().getByRole("status").textContent;
      expect(announced).toContain("5 seconds");
      await wait(2000);
      expect(card().getByRole("status").textContent).toBe(announced);
    });

    it("cancels when the page is hidden, and says nothing was sent", async () => {
      await startRelease();
      await wait(1000);
      const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      act(() => void document.dispatchEvent(new Event("visibilitychange")));
      visibility.mockRestore();
      await wait(10000);
      expect(voidPledge).not.toHaveBeenCalled();
      expect(card().getByRole("status")).toHaveTextContent("Nothing was sent");
      expect(screen.getByTestId(`captain-override-${STOP}`)).toBeInTheDocument();
    });

    it("cancels when the queue closes", async () => {
      await startRelease();
      await wait(1000);
      cleanup();
      await wait(10000);
      expect(voidPledge).not.toHaveBeenCalled();
    });

    it("does not restart when the language changes", async () => {
      await startRelease();
      await wait(2000);
      await act(async () => {
        await i18n.changeLanguage("fr");
      });
      expect(screen.getByTestId(`captain-countdown-${STOP}`)).toHaveTextContent("Libération dans 3 s");
      await wait(3000);
      expect(voidPledge).toHaveBeenCalledTimes(2);
    });

    it("blocks row capture while a release is running", async () => {
      vi.mocked(captainReview).mockResolvedValue({ ...review, proposal: "capture" });
      vi.mocked(approveCaptainReview).mockResolvedValue({ milestone_id: STOP, approved: true });
      await openCard([hold("p-1", "20.00")]);
      fireEvent.click(screen.getByTestId(`captain-approve-${STOP}`));
      await waitFor(() => expect(screen.getByTestId("capture-p-1")).not.toBeDisabled());
      vi.useFakeTimers();
      fireEvent.click(screen.getByTestId(`captain-override-${STOP}`));
      fireEvent.click(screen.getByTestId(`captain-release-${STOP}`));
      expect(screen.getByTestId("capture-p-1")).toBeDisabled();
      expect(capturePledge).not.toHaveBeenCalled();
    });

    it("reports a partial failure and retries only the holds still held", async () => {
      vi.mocked(voidPledge).mockImplementation(async (id) => {
        if (id === "p-2") throw new Error("PayPal said no");
        return { ...hold(id, "20.00"), status: "voided" };
      });
      await startRelease();
      await wait(5000);
      expect(card().getByRole("status")).toHaveTextContent("1 hold released · €20 total");
      expect(card().getByRole("alert")).toHaveTextContent("PayPal said no");

      vi.mocked(voidPledge).mockClear();
      vi.mocked(voidPledge).mockImplementation(async (id) => ({ ...hold(id, "12.50"), status: "voided" }));
      fireEvent.click(card().getByRole("button", { name: "Retry" }));
      expect(screen.getByTestId(`captain-release-${STOP}`).closest("[role=group]")).toHaveTextContent("Void 1 hold of €12.50?");
      fireEvent.click(screen.getByTestId(`captain-release-${STOP}`));
      expect(screen.getByTestId(`captain-countdown-${STOP}`)).toBeInTheDocument();
      await wait(5000);
      expect(voidPledge).toHaveBeenCalledTimes(1);
      expect(voidPledge).toHaveBeenCalledWith("p-2", "key", undefined);
      expect(card().getByRole("status")).toHaveTextContent("2 holds released · €32.50 total");
    });

    it("re-runs the rate-limited review only when a milestone leaves the queue", async () => {
      await startRelease([hold("p-1", "20.00"), hold("p-2", "12.50"), hold("p-3", "5.00")]);
      vi.mocked(voidPledge).mockImplementation(async (id) => {
        if (id === "p-3") throw new Error("stuck");
        return { ...hold(id, "1.00"), status: "voided" };
      });
      const before = vi.mocked(captainReview).mock.calls.length;
      await wait(5000);
      expect(vi.mocked(captainReview).mock.calls.length).toBe(before);
    });
  });

  describe("status chips", () => {
    const chip = (status: string) => {
      const { container, unmount } = render(
        <I18nextProvider i18n={i18n}>
          <PledgeStatusChip status={status} />
        </I18nextProvider>,
      );
      const el = container.querySelector(".pledge-chip") as HTMLElement;
      const row = {
        text: el.textContent,
        color: el.style.getPropertyValue("--st"),
        glyph: el.querySelector("svg")?.innerHTML,
      };
      unmount();
      return row;
    };

    it("labels the five states with a distinct colour and glyph each", () => {
      const rows = ["authorized", "vaulted", "captured", "voided", "refunded"].map(chip);
      expect(rows.map((row) => row.text)).toEqual(["Held", "Saved", "Captured", "Released", "Refunded"]);
      expect(new Set(rows.map((row) => row.color)).size).toBe(5);
      expect(new Set(rows.map((row) => row.glyph)).size).toBe(5);
    });

    it("keeps amber for held alone", () => {
      expect(chip("authorized").color).toBe("var(--color-st-progress)");
      expect(chipSource.match(/--color-st-progress/g)).toHaveLength(1);
      for (const status of ["pending", "partially_refunded", "created", "failed"]) {
        expect(chip(status).color).not.toBe("var(--color-st-progress)");
      }
    });

    it("falls back to the raw status for one it does not know", () => {
      expect(chip("settled").text).toBe("settled");
    });
  });

  it("keeps the FR and EN blocks in step", () => {
    const keys = (value: object, prefix = ""): string[] =>
      Object.entries(value).flatMap(([key, child]) =>
        typeof child === "object" ? keys(child, `${prefix}${key}.`) : [`${prefix}${key}`],
      );
    expect(keys(fr.captainCard)).toEqual(keys(en.captainCard));
  });
});
