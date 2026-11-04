import { memo, useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, Send, Sparkles } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { hasAdminSecret } from "../utils/adminSecret.js";
import { formatTimeUtc } from "../engine/journalFormat.js";
import { LlmSourceBadge } from "./LlmSourceBadge.jsx";

/**
 * Le chatbot du journal de bord, dans le panneau gauche : une
 * question sur toutes les données de l'application, une réponse citant les
 * faits du serveur, l'échange consigné au journal quand la clé admin est là.
 */
const AI_CHAT_NOTICE_KEY = "naviguide-ai-act-chat-notice-v1";

/**
 * Questions d'exemple, une par usage réel du serveur (logbook_chat.py) :
 * - deep : « pourquoi / why » → is_hard_question → cascade(tier="judge"), Ultra ;
 * - web : « comment / how » → Ultra aussi, qui lit portWeb (port_web_context, Tavily),
 *   et la réponse porte les liens webSources ;
 * - fast : question courte de fait → understand_question(tier="nano"), Lightning,
 *   puis gabarit des règles (aucun appel Ultra).
 * Le texte vient de l'i18n ; le test pytest test_logbook_examples les route.
 */
export const LOGBOOK_EXAMPLES = [
  { id: "deep", q: "logbookExampleDeepQ", label: "logbookExampleDeepLabel", hint: "logbookExampleDeepHint" },
  { id: "web", q: "logbookExampleWebQ", label: "logbookExampleWebLabel", hint: "logbookExampleWebHint" },
  { id: "fast", q: "logbookExampleFastQ", label: "logbookExampleFastLabel", hint: "logbookExampleFastHint" },
];

function aiNoticeDismissed() {
  try {
    return localStorage.getItem(AI_CHAT_NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

export const LogbookChat = memo(function LogbookChat({ messages = [], pending = false, error = null, onAsk }) {
  const { t } = useLang();
  const [draft, setDraft] = useState("");
  const [aiNoticeOff, setAiNoticeOff] = useState(aiNoticeDismissed);
  const [aiNoticeArmed, setAiNoticeArmed] = useState(false);
  const showAiNotice = !aiNoticeOff && (aiNoticeArmed || messages.length > 0);
  const listRef = useRef(null);
  const inputRef = useRef(null);
  const admin = hasAdminSecret();

  const dismissAiNotice = useCallback(() => {
    setAiNoticeOff(true);
    // Le bouton qui a le focus disparaît : on rend le focus au champ (sinon il tombe sur body).
    inputRef.current?.focus();
    try {
      localStorage.setItem(AI_CHAT_NOTICE_KEY, "1");
    } catch {
      /* private mode: the notice stays closed for this view */
    }
  }, []);

  const onChatFocus = useCallback(() => {
    if (!aiNoticeDismissed()) setAiNoticeArmed(true);
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, pending]);

  const askExample = (key) => {
    const q = t(key);
    if (!q || pending) return;
    setDraft("");
    if (!aiNoticeDismissed()) setAiNoticeArmed(true);
    onAsk?.(q);
  };

  const submit = (e) => {
    e?.preventDefault?.();
    const q = draft.trim();
    if (!q || pending) return;
    setDraft("");
    onAsk?.(q);
  };

  // L'avis reste hors du cadre à hauteur fixe pour préserver la place des réponses.
  return (
    // Cible de la visite (étape 4) : le cadre ET l'avis AI Act, sinon l'overlay driver.js
    // bloque le bouton « Compris » de l'avis qui s'affiche hors du cadre.
    <div data-tour="logbook" className="min-w-0">
    <div data-testid="logbook-chat" className="sim-box-chat rounded-lg border border-violet-500/25 bg-violet-950/25 p-2 min-w-0">
      <div className="flex items-center gap-1.5 mb-1 flex-shrink-0">
        <MessageSquare size={12} className="text-violet-200" />
        <div className="text-[10px] font-semibold uppercase tracking-wider text-violet-200 leading-snug">{t("logbookChatTitle")}</div>
        <span className="ml-auto text-[9px] text-violet-100/60">{admin ? t("logbookChatLogged") : t("logbookChatNotLogged")}</span>
      </div>
      <div
        data-testid="logbook-chat-reply"
        className="flex-1 min-h-0 rounded-md border border-violet-300/30 bg-slate-950/55 px-1.5 py-1"
      >
        <div ref={listRef} className="h-full overflow-y-auto sidebar-scroll space-y-1 min-w-0" data-testid="logbook-chat-list" role="log" aria-live="polite">
          {messages.map((m, i) => (
            <div key={`${m.t}-${i}`} className={`text-[11px] leading-snug break-words [overflow-wrap:anywhere] ${m.role === "skipper" ? "text-slate-100" : "text-violet-100"}`}>
              <span className="text-[9px] text-slate-500 mr-1">{formatTimeUtc(m.t)}</span>
              <span className="font-semibold mr-1">{m.role === "skipper" ? t("logbookChatYou") : t("logbookChatBot")}</span>
              {m.status === "failed"
                ? <span className="text-amber-300/90">{t("logbookChatFailed")}</span>
                : m.text}
              {m.role === "logbook" && m.status === "ready" ? (
                <span className="ml-1 text-[9px] text-slate-500">{m.logged ? "💬 " + t("logbookChatSaved") : t("logbookChatUnsaved")}</span>
              ) : null}
              {m.role === "logbook" && (m.source || m.engine) ? (
                <LlmSourceBadge source={m.source || m.engine} testId="chat-source" className="mt-0.5" />
              ) : null}
              {m.role === "logbook" && m.webSources?.length ? (
                <ul
                  data-testid="logbook-chat-web-sources"
                  className="mt-1 list-none space-y-0.5 pl-0 text-[9px] text-slate-400"
                >
                  <li className="font-semibold text-violet-200/80">{t("logbookWebSourcesTitle")}</li>
                  {m.webSources.map((s) => (
                    <li key={s.url}>
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-violet-200/90 underline underline-offset-2 break-all"
                      >
                        {s.title || s.url}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
          {pending ? <p className="text-[10px] text-slate-400 leading-snug">{t("logbookChatPending")}</p> : null}
          {error ? <p className="text-[10px] text-amber-300/90 leading-snug" role="alert" data-testid="logbook-chat-error">{error}</p> : null}
        </div>
      </div>
      <div
        data-testid="logbook-chat-examples"
        className="mt-1 flex flex-nowrap items-center gap-0.5 flex-shrink-0 min-w-0 overflow-x-auto overflow-y-hidden [scrollbar-width:none]"
      >
        <Sparkles size={11} className="text-violet-200/80" aria-label={t("logbookExamplesTitle")} role="img" />
        {LOGBOOK_EXAMPLES.map((ex) => (
          <button
            key={ex.id}
            type="button"
            disabled={pending}
            onClick={() => askExample(ex.q)}
            data-testid={`logbook-chat-example-${ex.id}`}
            title={`${t(ex.q)} — ${t(ex.hint)}`}
            className="h-5 whitespace-nowrap rounded-full border border-violet-300/35 bg-violet-900/40 px-[5px] text-[10px] flex-shrink-0 text-violet-50 hover:bg-violet-800/60 disabled:opacity-40"
          >
            {t(ex.label)}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="mt-1.5 flex items-center gap-1 flex-shrink-0">
        <input
          ref={inputRef}
          type="text"
          aria-label={t("logbookChatInputLabel")}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={onChatFocus}
          placeholder={t("logbookChatPlaceholder")}
          maxLength={500}
          data-testid="logbook-chat-input"
          className="flex-1 min-w-0 h-7 rounded-md bg-slate-900/70 border border-white/10 px-2 text-[11px] text-white placeholder:text-slate-500 focus:outline-none focus:border-violet-400/60"
        />
        <button
          type="submit"
          disabled={pending || !draft.trim()}
          title={t("logbookChatSend")}
          aria-label={t("logbookChatSend")}
          data-testid="logbook-chat-send"
          className="h-7 w-7 rounded-md bg-violet-600 hover:bg-violet-500 disabled:opacity-40 flex items-center justify-center text-white"
        >
          <Send size={12} aria-hidden="true" />
        </button>
      </form>
    </div>
    {showAiNotice ? (
      <div
        data-testid="logbook-chat-ai-notice"
        className="mt-1.5 rounded-md border border-violet-300/45 bg-violet-950 px-2 py-1.5 text-xs leading-snug text-violet-50"
      >
        {/* Région live autour du texte seul : la notice AI Act est annoncée, pas le bouton. */}
        <p role="status" aria-live="polite" data-testid="logbook-chat-ai-notice-text">{t("aiActChatNotice")}</p>
        <button
          type="button"
          data-testid="logbook-chat-ai-notice-dismiss"
          onClick={dismissAiNotice}
          className="mt-1 text-xs font-semibold text-white underline underline-offset-2 hover:text-violet-100"
        >
          {t("aiActChatNoticeDismiss")}
        </button>
      </div>
    ) : null}
    </div>
  );
});
