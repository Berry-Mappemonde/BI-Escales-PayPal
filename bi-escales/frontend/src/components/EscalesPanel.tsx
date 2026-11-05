import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainChat } from "../api/escales";
import type { CaptainChatResponse, PublicPledge } from "../api/types";
import { PledgeButton } from "./PledgeButton";

export interface EscalesPanelProps {
  milestoneId: string;
  adminKey?: string;
  onMilestoneId?: (id: string) => void;
  onSuggested?: (pledge: CaptainChatResponse["suggested_pledge"]) => void;
  onAuthorized?: (pledge: PublicPledge) => void;
}

export function EscalesPanel({
  milestoneId,
  adminKey,
  onMilestoneId,
  onSuggested,
  onAuthorized,
}: EscalesPanelProps) {
  const { t, i18n } = useTranslation();
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [chatMessage, setChatMessage] = useState("20 milles près de Mayotte");
  const [chatResult, setChatResult] = useState<CaptainChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onChat = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await captainChat(chatMessage, lang, adminKey);
      setChatResult(res);
      if (res.suggested_pledge) {
        onSuggested?.(res.suggested_pledge);
        onMilestoneId?.(res.suggested_pledge.milestone_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" data-milestone={milestoneId}>
      <h2>{t("escales.captainChat")}</h2>
      {error ? <p className="notice error">{error}</p> : null}
      <form className="stack-form" onSubmit={onChat}>
        <textarea value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} rows={2} />
        <button type="submit" disabled={busy}>{t("escales.sendChat")}</button>
      </form>
      {chatResult ? (
        <div className="chat-result">
          <h3>{t("escales.chatReply")}</h3>
          <p>{chatResult.reply}</p>
          {chatResult.model_label ? (
            <p className="hint" data-testid="captain-model-label">
              {chatResult.model_label}
            </p>
          ) : null}
          {(() => {
            const payload = chatResult.paypal_tools;
            if (!payload || Array.isArray(payload)) return null;
            const called = payload.called;
            if (!called?.length) return null;
            const client = payload.client || "direct";
            return (
              <p className="hint" data-testid="captain-paypal-tools">
                {t("escales.paypalToolLine", { tools: called.join(", "), client })}
              </p>
            );
          })()}
          {chatResult.cart?.lines?.length ? (
            <div data-testid="captain-cart">
              <h3>{t("escales.cartHeading")}</h3>
              {chatResult.cart.lines.map((line, index) => (
                <div key={`${line.kind || "line"}-${index}`} data-testid="cart-line">
                  <p>
                    {line.description} — {line.amount_eur} {chatResult.cart?.currency || "EUR"}
                    {line.price_label ? ` (${t("pledge.simulatedPrice")})` : ""}
                  </p>
                  {line.pledge ? (
                    <PledgeButton
                      values={{ ...line.pledge, lang: line.pledge.lang || lang }}
                      onAuthorized={onAuthorized}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
