import { FormEvent, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainChat, listMilestones, postEvidence } from "../api/escales";
import type { CaptainChatResponse, Milestone, PublicPledge } from "../api/types";
import { PledgeButton } from "./PledgeButton";

const DEFAULT_MILESTONE = "dep-mayotte";

export interface EscalesPanelProps {
  onPledgeAuthorized?: (pledge: PublicPledge) => void;
}

export function EscalesPanel({ onPledgeAuthorized }: EscalesPanelProps) {
  const { t } = useTranslation();
  const [milestoneId, setMilestoneId] = useState(DEFAULT_MILESTONE);
  const [evidenceMet, setEvidenceMet] = useState(true);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [chatMessage, setChatMessage] = useState("20 milles près de Mayotte");
  const [chatResult, setChatResult] = useState<CaptainChatResponse | null>(null);
  const [amount, setAmount] = useState("20.00");
  const [description, setDescription] = useState("20 milles Mayotte");
  const [contributor, setContributor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMilestones = useCallback(async () => {
    setError(null);
    try {
      setMilestones(await listMilestones());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const onEvidence = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postEvidence(milestoneId, {
        met: evidenceMet,
        facts: { port: milestoneId, source: "frontend-demo" },
      });
      await loadMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onChat = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await captainChat(chatMessage);
      setChatResult(res);
      const s = res.suggested_pledge;
      setAmount(s.amount_eur);
      setDescription(s.description);
      setMilestoneId(s.milestone_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applySuggested = () => {
    if (!chatResult) return;
    const s = chatResult.suggested_pledge;
    setAmount(s.amount_eur);
    setDescription(s.description);
    setMilestoneId(s.milestone_id);
  };

  return (
    <section className="panel escales-panel">
      <h2>{t("escales.heading")}</h2>
      {error ? <p className="notice error">{error}</p> : null}

      <form className="inline-form" onSubmit={onEvidence}>
        <label>
          {t("escales.milestoneId")}
          <input value={milestoneId} onChange={(e) => setMilestoneId(e.target.value)} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={evidenceMet} onChange={(e) => setEvidenceMet(e.target.checked)} />
          {t("escales.evidenceMet")}
        </label>
        <button type="submit" disabled={busy}>
          {t("escales.postEvidence")}
        </button>
        <button type="button" onClick={() => void loadMilestones()} disabled={busy}>
          {t("escales.loadMilestones")}
        </button>
      </form>

      {milestones.length === 0 ? (
        <p className="hint">{t("escales.milestonesEmpty")}</p>
      ) : (
        <ul className="milestone-list">
          {milestones.map((m) => (
            <li key={m.id}>
              <strong>{m.id}</strong> — {m.evidence?.length ?? 0} preuve(s)
              {m.proposal ? ` · ${m.proposal.proposal}` : ""}
            </li>
          ))}
        </ul>
      )}

      <form className="stack-form" onSubmit={onChat}>
        <label>
          {t("escales.captainChat")}
          <textarea value={chatMessage} onChange={(e) => setChatMessage(e.target.value)} rows={2} />
        </label>
        <button type="submit" disabled={busy}>
          {t("escales.sendChat")}
        </button>
      </form>

      {chatResult ? (
        <div className="chat-result">
          <h3>{t("escales.chatReply")}</h3>
          <p>{chatResult.reply}</p>
          <h4>{t("escales.suggestedPledge")}</h4>
          <pre>{JSON.stringify(chatResult.suggested_pledge, null, 2)}</pre>
          <button type="button" onClick={applySuggested}>
            {t("escales.suggestedPledge")}
          </button>
        </div>
      ) : null}

      <div className="pledge-form">
        <label>
          {t("pledge.amount")}
          <input value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          {t("pledge.description")}
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          {t("pledge.milestone")}
          <input value={milestoneId} onChange={(e) => setMilestoneId(e.target.value)} />
        </label>
        <label>
          {t("pledge.contributor")}
          <input value={contributor} onChange={(e) => setContributor(e.target.value)} />
        </label>
        <PledgeButton
          values={{
            amount_eur: amount,
            description,
            milestone_id: milestoneId,
            contributor: contributor.trim() || undefined,
          }}
          disabled={busy}
          onAuthorized={onPledgeAuthorized}
        />
      </div>
    </section>
  );
}
