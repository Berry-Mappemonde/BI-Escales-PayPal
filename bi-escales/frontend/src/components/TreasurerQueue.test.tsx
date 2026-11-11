import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveCaptainReview,
  captainReview,
  capturePledge,
  fetchSchedule,
  refundPledge,
  voidPledge,
} from "../api/escales";
import i18n from "../i18n";
import { formatPledgeCreatedAt, shortPledgeId, TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
  fetchSchedule: vi.fn().mockResolvedValue({}),
  refundPledge: vi.fn(),
  voidPledge: vi.fn(),
}));

const pledge = {
  id: "p-1",
  status: "authorized" as const,
  intent: "AUTHORIZE",
  currency: "EUR",
  amount_eur: "20.00",
  description: "milles",
  milestone_id: "dep-la-rochelle",
};

describe("TreasurerQueue", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  describe("milestone shown per pledge", () => {
    const rows = [
      pledge,
      { ...pledge, id: "p-2", milestone_id: "dep-ajaccio-corse" },
      { ...pledge, id: "p-3", milestone_id: "leg-la-rochelle-ajaccio" },
      { ...pledge, id: "p-4", milestone_id: "" },
    ];
    const stopNames = { "dep-la-rochelle": "La Rochelle", "dep-ajaccio-corse": "Ajaccio (Corse)" };

    function show(names?: Record<string, string>) {
      vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "wait", pledge_ids: [] });
      render(
        <I18nextProvider i18n={i18n}>
          <TreasurerQueue pledges={rows} adminKey="key" stopNames={names} onRefresh={() => {}} onUpdated={() => {}} />
        </I18nextProvider>,
      );
    }

    it("shows the stop name instead of the milestone id, and keeps the id as a tooltip", () => {
      show(stopNames);
      expect(screen.getByTestId("pledge-milestone-p-1")).toHaveTextContent(/^La Rochelle$/);
      expect(screen.getByTestId("pledge-milestone-p-1")).toHaveAttribute("title", "dep-la-rochelle");
      expect(screen.getByTestId("pledge-milestone-p-2")).toHaveTextContent(/^Ajaccio \(Corse\)$/);
      expect(within(screen.getByTestId("queue-row-p-1")).queryByText("dep-la-rochelle")).toBeNull();
    });

    it("falls back to the id for a milestone the voyage does not know", () => {
      show(stopNames);
      expect(screen.getByTestId("pledge-milestone-p-3")).toHaveTextContent(/^leg-la-rochelle-ajaccio$/);
      expect(screen.getByTestId("pledge-milestone-p-4")).toBeEmptyDOMElement();
      expect(screen.getByTestId("pledge-milestone-p-4")).not.toHaveAttribute("title");
    });

    it("shows ids when no stop names are known yet", () => {
      show(undefined);
      expect(screen.getByTestId("pledge-milestone-p-1")).toHaveTextContent(/^dep-la-rochelle$/);
      expect(screen.getByTestId("pledge-milestone-p-2")).toHaveTextContent(/^dep-ajaccio-corse$/);
    });

    describe("Captain review cards", () => {
      const leg = "leg-la-rochelle-to-ajaccio-corse";
      const cabin = { ...pledge, id: "p-5", milestone_id: leg };

      function showCards(names: Record<string, string> | undefined, pledges = [...rows, cabin]) {
        vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "wait", pledge_ids: [] });
        render(
          <I18nextProvider i18n={i18n}>
            <TreasurerQueue pledges={pledges} adminKey="key" stopNames={names} onRefresh={() => {}} onUpdated={() => {}} />
          </I18nextProvider>,
        );
      }

      afterEach(async () => {
        vi.mocked(fetchSchedule).mockResolvedValue({});
        await i18n.changeLanguage("en");
      });

      it("names the stop under the heading and keeps the id as a tooltip", async () => {
        await i18n.changeLanguage("en");
        showCards(stopNames);
        const card = screen.getByTestId("captain-card-dep-ajaccio-corse");
        const name = within(card).getByTestId("captain-stop-dep-ajaccio-corse");
        expect(name).toHaveTextContent(/^Ajaccio \(Corse\)$/);
        expect(name).toHaveAttribute("title", "dep-ajaccio-corse");
        expect(within(card).queryByText("dep-ajaccio-corse")).toBeNull();
        expect(screen.getByTestId("captain-stop-dep-la-rochelle")).toHaveTextContent(/^La Rochelle$/);
      });

      it.each([
        ["en", "Cabin: La Rochelle → Ajaccio (Corse)"],
        ["fr", "Cabine : La Rochelle → Ajaccio (Corse)"],
      ])("names both ends of a cabin leg (%s), on the card and in its row", async (lang, label) => {
        await i18n.changeLanguage(lang);
        showCards(stopNames);
        const name = screen.getByTestId(`captain-stop-${leg}`);
        expect(name.textContent).toBe(label);
        expect(name).toHaveAttribute("title", leg);
        expect(screen.getByTestId("pledge-milestone-p-5").textContent).toBe(label);
        expect(screen.getByTestId("pledge-milestone-p-5")).toHaveAttribute("title", leg);
      });

      it("keeps the raw id when a cabin leg has an end the voyage does not know", async () => {
        await i18n.changeLanguage("en");
        const unknown = "leg-la-rochelle-to-atlantis";
        showCards(stopNames, [{ ...pledge, id: "p-6", milestone_id: unknown }]);
        expect(screen.getByTestId(`captain-stop-${unknown}`).textContent).toBe(unknown);
        expect(screen.getByTestId(`captain-stop-${unknown}`)).toHaveAttribute("title", unknown);
        expect(screen.getByTestId("pledge-milestone-p-6").textContent).toBe(unknown);
      });

      it("uses the schedule's name when the voyage has none, then the id", async () => {
        await i18n.changeLanguage("en");
        vi.mocked(fetchSchedule).mockResolvedValue({
          milestones: [{ milestone_id: "dep-ajaccio-corse", name: "Ajaccio from the schedule" }],
        } as Awaited<ReturnType<typeof fetchSchedule>>);
        showCards(undefined);
        expect(await screen.findByText("Ajaccio from the schedule")).toBe(
          screen.getByTestId("captain-stop-dep-ajaccio-corse"),
        );
        expect(screen.getByTestId("captain-stop-dep-la-rochelle").textContent).toBe("dep-la-rochelle");
      });

      it("prefers the voyage's stop name over the schedule's", async () => {
        await i18n.changeLanguage("en");
        vi.mocked(fetchSchedule).mockResolvedValue({
          milestones: [{ milestone_id: "dep-la-rochelle", name: "Schedule name" }],
        } as Awaited<ReturnType<typeof fetchSchedule>>);
        showCards(stopNames);
        await waitFor(() => expect(fetchSchedule).toHaveBeenCalled());
        await act(async () => {});
        expect(screen.getByTestId("captain-stop-dep-la-rochelle").textContent).toBe("La Rochelle");
        expect(screen.queryByText("Schedule name")).toBeNull();
      });
    });
  });
  it("records review approval then captures on a separate button", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(captainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      proposal: "capture",
      pledge_ids: ["p-1"],
    });
    vi.mocked(approveCaptainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      approved: true,
    });
    vi.mocked(capturePledge).mockResolvedValue({ ...pledge, status: "captured" });
    const onUpdated = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge]}
          adminKey="test-admin-key"
          onRefresh={() => {}}
          onUpdated={onUpdated}
        />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("captain-proposal-dep-la-rochelle")).toHaveTextContent("Encaisser");
    fireEvent.click(screen.getByTestId("captain-approve-dep-la-rochelle"));
    expect(approveCaptainReview).toHaveBeenCalledWith("dep-la-rochelle", "test-admin-key", undefined);
    await waitFor(() => {
      expect(screen.getByTestId("capture-p-1")).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Capturer la promesse" }));
    expect(capturePledge).toHaveBeenCalledWith("p-1", "test-admin-key", undefined);
    await waitFor(() => {
      expect(onUpdated).toHaveBeenCalled();
    });
  });

  it("lists captured and partially refunded pledges with a refund button", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "", pledge_ids: [] });
    vi.mocked(refundPledge).mockResolvedValue({ ...pledge, id: "p-cap", status: "refunded" });
    const onUpdated = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[
            { ...pledge, id: "p-cap", status: "captured" as const, capture_id: "CAP-1" },
            { ...pledge, id: "p-part", status: "partially_refunded" as const, refunded_amount_eur: "5.00", capture_id: "CAP-2" },
            { ...pledge, id: "p-void", status: "voided" as const },
          ]}
          adminKey="test-admin-key"
          onRefresh={() => {}}
          onUpdated={onUpdated}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("queue-row-p-cap")).toBeInTheDocument();
    expect(screen.getByTestId("queue-row-p-part")).toBeInTheDocument();
    expect(screen.queryByTestId("queue-row-p-void")).toBeNull();
    expect(screen.getByTestId("refund-p-part")).not.toBeDisabled();
    expect(screen.queryByTestId("void-p-cap")).toBeNull();
    fireEvent.click(screen.getByTestId("refund-p-cap"));
    expect(refundPledge).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Refund €20.00 to the donor? This can't be undone." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledTimes(1);
    expect(refundPledge).toHaveBeenCalledWith("p-cap", "test-admin-key", "20.00", undefined);
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
  });

  it("keeps money buttons disabled in keyless demo mode", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "capture", pledge_ids: [] });
    vi.mocked(voidPledge).mockClear();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge, { ...pledge, id: "p-cap", status: "captured" as const }]}
          adminKey=""
          demoTreasurer
          onRefresh={() => {}}
          onUpdated={() => {}}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("treasurer-demo-readonly")).toBeInTheDocument();
    await screen.findByTestId("captain-proposal-dep-la-rochelle");
    expect(screen.getByTestId("captain-approve-dep-la-rochelle")).toBeDisabled();
    expect(screen.getByTestId("captain-override-dep-la-rochelle")).toBeDisabled();
    expect(screen.getByTestId("refund-p-cap")).toBeDisabled();
    fireEvent.click(screen.getByTestId("captain-override-dep-la-rochelle"));
    expect(screen.queryByTestId("captain-release-dep-la-rochelle")).toBeNull();
    expect(voidPledge).not.toHaveBeenCalled();
  });

  function renderQueue(rows = [{ ...pledge, status: "captured" as const, capture_id: "CAP-1" }]) {
    return render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={rows} adminKey="test-admin-key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
  }

  it.each(["en", "fr"])("cancels refunds without a request, in %s", async (lang) => {
    await i18n.changeLanguage(lang);
    renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    const group = screen.getByRole("group");
    expect(group).toHaveTextContent(lang === "fr"
      ? "Rembourser 20,00 € au donateur ? Cette opération est irréversible."
      : "Refund €20.00 to the donor? This can't be undone.");
    const cancel = within(group).getByRole("button", { name: lang === "fr" ? "Annuler" : "Cancel" });
    expect(cancel).toHaveFocus();
    fireEvent.click(cancel);
    expect(screen.queryByRole("group")).toBeNull();
    expect(refundPledge).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("refund-p-1")).toHaveFocus());
  });

  it("confirms the remaining balance after a partial refund", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded", refunded_amount_eur: "7.35" }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €12.65 to the donor?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledWith("p-1", "key", "12.65", undefined);
  });

  it("confirms the amount of an interrupted keyed refund", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "captured", pending_refund: { key: "refund-p-1-1", amount: "5.00" } }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €5.00 to the donor?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledWith("p-1", "key", "5.00", undefined);
  });

  it("sends one refund while busy and requires confirmation again after an error", async () => {
    await i18n.changeLanguage("en");
    let reject!: (error: Error) => void;
    vi.mocked(refundPledge).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    const confirm = screen.getByRole("button", { name: "Confirm" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(refundPledge).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await act(async () => reject(new Error("PayPal unavailable")));
    expect(screen.getByText("PayPal unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).not.toBeDisabled();
    expect(refundPledge).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("drops the confirmation when the refundable balance changes", async () => {
    await i18n.changeLanguage("en");
    const view = renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    view.rerender(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded", refunded_amount_eur: "5.00" }]}
        adminKey="test-admin-key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    expect(screen.queryByRole("group")).toBeNull();
    expect(refundPledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €15.00 to the donor?");
  });

  it.each(["en", "fr"])("confirms or cancels voids inline, keeping Undo, in %s", async (lang) => {
    await i18n.changeLanguage(lang);
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: pledge.milestone_id, proposal: "wait", pledge_ids: [pledge.id] });
    vi.mocked(voidPledge).mockResolvedValue({ ...pledge, status: "voided" });
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[pledge]} adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    await screen.findByTestId(`captain-proposal-${pledge.milestone_id}`);
    const open = () => fireEvent.click(screen.getByTestId(`captain-override-${pledge.milestone_id}`));
    open();
    expect(screen.getByRole("group")).toHaveTextContent(lang === "fr"
      ? "Annuler 1 retenue de 20 € ? Une fois envoyée, cette opération est irréversible."
      : "Void 1 hold of €20? Once sent, this can't be undone.");
    fireEvent.click(screen.getByRole("button", { name: lang === "fr" ? "Annuler" : "Cancel" }));
    expect(voidPledge).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
    open();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: lang === "fr" ? "Confirmer" : "Confirm" }));
    expect(voidPledge).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(voidPledge).toHaveBeenCalledTimes(1);
    expect(voidPledge).toHaveBeenCalledWith(pledge.id, "key", undefined);
  });


  it("requires refreshed data if the partial refund balance is unknown", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded" }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    expect(screen.getByTestId("refund-p-1")).toBeDisabled();
    expect(screen.getByTestId("refund-p-1")).toHaveAttribute("title", "Refresh the queue to load the refundable amount.");
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(refundPledge).not.toHaveBeenCalled();
  });

  it.each(["en", "fr"] as const)(
    "lists demo queue rows with short pledge id, localized created_at, and newest first (%s)",
    async (lang) => {
      const older = {
        ...pledge,
        id: "aaaa1111-older-pledge-id",
        status: "authorized" as const,
        created_at: "2026-11-01T10:00:00.000Z",
      };
      const newer = {
        ...pledge,
        id: "bbbb2222-newer-pledge-id",
        status: "vaulted" as const,
        created_at: "2026-11-08T14:30:00.000Z",
      };
      await i18n.changeLanguage(lang);
      vi.mocked(captainReview).mockResolvedValue({
        milestone_id: "dep-la-rochelle",
        proposal: "capture",
        pledge_ids: [],
      });
      render(
        <I18nextProvider i18n={i18n}>
          <TreasurerQueue
            pledges={[older, newer]}
            adminKey=""
            demoTreasurer
            onRefresh={() => {}}
            onUpdated={() => {}}
          />
        </I18nextProvider>,
      );
      expect(screen.getByTestId("treasurer-demo-readonly")).toBeInTheDocument();
      const rows = screen.getAllByTestId(/^queue-row-/);
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveAttribute("data-testid", "queue-row-bbbb2222-newer-pledge-id");
      const shortNewer = screen.getByTestId("pledge-short-id-bbbb2222-newer-pledge-id");
      expect(shortNewer).toHaveTextContent(shortPledgeId(newer.id));
      expect(shortNewer).toHaveAttribute("title", newer.id);
      expect(screen.getByTestId("pledge-created-bbbb2222-newer-pledge-id")).toHaveTextContent(
        formatPledgeCreatedAt(newer.created_at, lang),
      );
      expect(screen.queryByTestId("capture-bbbb2222-newer-pledge-id")).toBeNull();
    },
  );

});
