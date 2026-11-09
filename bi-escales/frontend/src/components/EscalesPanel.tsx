import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainChat, createPayPalInvoice } from "../api/escales";
import { isCaptainRateLimitMessage } from "../api/captainRateLimit";
import type { CaptainChatResponse, PublicPledge } from "../api/types";
import { CaptainToolTrace } from "./captain/CaptainToolTrace";
import { PledgeButton } from "./PledgeButton";

export interface EscalesPanelProps {
  milestoneId: string;
  adminKey?: string;
  onMilestoneId?: (id: string) => void;
  onSuggested?: (pledge: CaptainChatResponse["suggested_pledge"]) => void;
  onAuthorized?: (pledge: PublicPledge) => void;
  onLocateBoat?: () => void;
}

export function EscalesPanel({
  milestoneId,
  adminKey,
  onMilestoneId,
  onSuggested,
  onAuthorized,
  onLocateBoat,
}: EscalesPanelProps) {
  const { t, i18n } = useTranslation();
  const lang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [chatMessage, setChatMessage] = useState("");
  const [chatResult, setChatResult] = useState<CaptainChatResponse | null>(null);
  const [agenticNote, setAgenticNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onChat = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !chatMessage.trim()) return;
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
      const message = err instanceof Error ? err.message : String(err);
      setError(isCaptainRateLimitMessage(message) ? t("escales.rateLimit") : message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel captain-chat" data-milestone={milestoneId}>
      <h2 className="rail-title">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 3h12v8H7l-4 3v-3H2z" stroke="currentColor" strokeLinejoin="round" /></svg>
        {t("escales.captainChat")}
      </h2>
      {error ? <p className="notice error">{error}</p> : null}
      {chatResult ? (
        <div className="chat-result">
          <h3>{t("escales.chatReply")}</h3>
          <p className="captain-bubble">{chatResult.reply}</p>
          <CaptainToolTrace trace={chatResult} modelTestId="captain-model-label" />
          {chatResult.agentic_action?.kind === "create_invoice" && adminKey?.trim() ? (
            <div data-testid="captain-agentic-invoice">
              <p className="hint">{chatResult.agentic_action.toolkit_note}</p>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const preview = chatResult.agentic_action?.preview;
                  if (!preview) return;
                  setBusy(true);
                  setAgenticNote(null);
                  void createPayPalInvoice(adminKey.trim(), {
                    recipient_email: preview.recipient_email || "",
                    amount_eur: preview.amount_eur || "1.00",
                    description: preview.description || "Escales",
                    lang,
                  })
                    .then((row) => setAgenticNote(String(row.id || row.invoice_id || "created")))
                    .catch((err: unknown) =>
                      setAgenticNote(err instanceof Error ? err.message : String(err)),
                    )
                    .finally(() => setBusy(false));
                }}
              >
                {t("escales.agenticConfirmInvoice")}
              </button>
              {agenticNote ? <p className="status">{agenticNote}</p> : null}
            </div>
          ) : null}
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
                      values={{ ...line.pledge, quantity: Number.isInteger(Number(line.quantity)) ? Number(line.quantity) : undefined, lang: line.pledge.lang || lang }}
                      onAuthorized={onAuthorized}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {busy ? <p className="captain-thinking" role="status">{t("escales.working")}</p> : null}
      {!chatResult && !busy ? (
        <ul className="captain-prompts" aria-label={t("escales.exampleQuestions")}>
          <li><svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2a6 6 0 1 0 0 12 6 6 0 1 0 0-12Zm0 3v3l2 1" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" /></svg>{t("escales.whenCharged")}</li>
          <li><svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13 7a5 5 0 1 1-5-4H4m0 0 2-2M4 3l2 2" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" /></svg>{t("escales.cancelledStop")}</li>
          <li>
            <button
              type="button"
              className="captain-prompt-chip"
              data-testid="captain-locate-boat"
              onClick={() => onLocateBoat?.()}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 11h12l-2 3H4zM8 2v8M8 3l4 5H8" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {t("escales.whereIsBoat")}
            </button>
          </li>
        </ul>
      ) : null}
      <form className="stack-form" onSubmit={onChat}>
        <label className="captain-draft">
          {t("escales.yourMessage")}
          <textarea
            value={chatMessage}
            onChange={(event) => setChatMessage(event.target.value)}
            placeholder={t("escales.chatPlaceholder")}
            aria-label={t("escales.yourMessage")}
            rows={2}
          />
        </label>
        <button type="submit" disabled={busy || !chatMessage.trim()}>{t("escales.sendChat")}</button>
      </form>
    </section>
  );
}
