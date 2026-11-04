import { useEffect, useState } from "react";
import { Square, Volume2, VolumeX } from "lucide-react";
import { canSpeak, speak, stopSpeaking } from "../utils/speak.js";

/**
 * « Écouter » — le récit lu à voix haute par le navigateur (zéro LLM).
 * In the film bar this is the only sound control: it arms
 * `replay.voice` (the hook reads the current paragraph during a replay)
 * and, outside a replay, reads the story + briefing. Moment cards and
 * escale sheets still use it as a one-shot reader.
 * `text` may be a string or a list of paragraphs (empty ones skipped).
 */
export function ListenButton({
  text,
  t,
  lang,
  compact = false,
  testId = "briefing-listen",
  className = "",
  listening,
  onListening,
  deferSpeak = false,
  showWhenEmpty = false,
  iconOnly = false,
}) {
  const [speaking, setSpeaking] = useState(false);
  const body = Array.isArray(text) ? text.filter(Boolean).join("\n\n") : (text || "");
  const armed = typeof listening === "boolean";
  const pressed = speaking || (deferSpeak && armed && listening);
  useEffect(() => () => stopSpeaking(), []);
  // A new text while speaking: stop, the button goes back to « Écouter ».
  useEffect(() => {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body]);
  if (!canSpeak() && !showWhenEmpty) return null;
  if (!body && !showWhenEmpty) return null;
  const toggle = () => {
    if (speaking || (deferSpeak && armed && listening)) {
      stopSpeaking();
      setSpeaking(false);
      onListening?.(false);
      return;
    }
    onListening?.(true);
    if (deferSpeak || !body) return;
    const ok = speak(body, lang, { onEnd: () => setSpeaking(false) });
    setSpeaking(ok);
  };
  // Pendant le film, Écouter reste « Écouter » (on/off) — « Stop » est l'arrêt du film.
  const label = (deferSpeak && armed)
    ? t("briefingListen")
    : (pressed ? t("briefingListenStop") : t("briefingListen"));
  const icon = iconOnly
    ? (pressed ? <Volume2 size={11} /> : <VolumeX size={11} />)
    : (pressed ? <Square size={11} /> : <Volume2 size={11} />);
  return (
    <button
      type="button"
      onClick={toggle}
      data-testid={testId}
      aria-pressed={pressed}
      aria-label={label}
      title={label}
      className={`flex items-center gap-1 rounded-md text-[10px] font-semibold border transition-colors relative
        ${iconOnly ? "w-6 h-6 px-0 justify-center" : compact ? "h-6 px-1.5" : "px-1.5 py-0.5 rounded-full"}
        ${pressed ? "bg-sky-600/40 text-sky-100 border-sky-400/40" : "bg-white/5 text-white/80 border-white/10 hover:bg-white/10 hover:text-white"}
        ${className}`}
    >
      {icon}
      {iconOnly
        ? <span className="absolute w-px h-px overflow-hidden">{label}</span>
        : label}
    </button>
  );
}
