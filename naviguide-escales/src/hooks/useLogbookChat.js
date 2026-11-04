import { useCallback, useEffect, useRef, useState } from "react";
import { adminHeaders } from "../utils/adminSecret.js";
import { chatErrorKey, postLogbookChat } from "../utils/logbookChatRequest.js";
import { useLang } from "../i18n/LangContext.jsx";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const HISTORY_MAX = 30;

/**
 * Chatbot journal de bord. `ask(question)` posts to /logbook/chat with
 * the facts only the client knows (`contextFn()` → view, boat of the film,
 * polar, skipper's orders). The server answers from its own facts and logs
 * the exchange when the admin key travels with the request. Never blocks
 * Play; one question in flight at a time.
 */
export function useLogbookChat({ lang = "fr", contextFn = null } = {}) {
  const { t: tr } = useLang();
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const inFlight = useRef(false);
  const requestController = useRef(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestController.current?.abort();
    };
  }, []);

  const ask = useCallback(async (question, opts = {}) => {
    const q = String(question || "").trim();
    if (!q || inFlight.current) return null;
    inFlight.current = true;
    const controller = new AbortController();
    requestController.current = controller;
    setPending(true);
    setError(null);
    const timestamp = new Date().toISOString();
    setMessages((prev) => [...prev, { role: "skipper", text: q, t: timestamp }].slice(-HISTORY_MAX));
    let context = null;
    try {
      context = typeof contextFn === "function" ? contextFn() : null;
    } catch {
      context = null;
    }
    try {
      const body = await postLogbookChat({
        url: `${API_URL}/logbook/chat`,
        fetchImpl: (url, options) => fetch(url, { ...options, headers: { ...options.headers, ...adminHeaders() } }),
        body: { question: q, lang, context },
        signal: controller.signal,
      });
      const reply = {
        role: "logbook",
        text: body.answer || "",
        status: body.status,
        reason: body.reason || null,
        logged: Boolean(body.logged),
        engine: body.engine || null,
        source: body.source || body.engine || null,
        webSources: Array.isArray(body.webSources) ? body.webSources : [],
        portWebStatus: body.portWebStatus || null,
        t: body.t || new Date().toISOString(),
      };
      if (mounted.current) setMessages((prev) => [...prev, reply].slice(-HISTORY_MAX));
      return reply;
    } catch (err) {
      if (err?.code === "aborted" || err?.name === "AbortError") return null;
      console.warn("Logbook chat request failed:", err?.detail ?? err?.message);
      if (mounted.current) setError(tr(chatErrorKey(err?.code)));
      return null;
    } finally {
      if (requestController.current === controller) requestController.current = null;
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }, [lang, contextFn, tr]);

  const clear = useCallback(() => setMessages([]), []);

  return { messages, pending, error, ask, clear };
}
