import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainChat, createPayPalInvoice } from "../api/escales";
import { isCaptainRateLimitMessage } from "../api/captainRateLimit";
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
    <section className="panel" data-milestone={milestoneId}>
      <h2>{t("escales.captainChat")}</h2>
      {error ? <p className="notice error">{error}</p> : null}
      <form className="stack-form" onSubmit={onChat}>
        <textarea
          value={chatMessage}
          onChange={(event) => setChatMessage(event.target.value)}
          placeholder={t("escales.chatPlaceholder")}
          aria-label={t("escales.captainChat")}
          rows={2}
        />
        <button type="submit" disabled={busy || !chatMessage.trim()}>{t("escales.sendChat")}</button>
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
    </section>
  );
}
