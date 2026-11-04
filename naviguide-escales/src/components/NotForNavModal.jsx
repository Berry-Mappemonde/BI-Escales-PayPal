import { useState } from "react";
import { useLang } from "../i18n/LangContext.jsx";

export default function NotForNavModal({ open, onAccept, onCancel }) {
  const { t } = useLang();
  const [acked, setAcked] = useState(false);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-slate-950/80 px-4"
      data-testid="not-for-nav-modal"
      role="dialog"
      aria-modal="true"
    >
      <div className="max-w-md w-full bg-slate-900 border border-amber-400/50 rounded-lg p-5">
        <h2 className="text-sm font-bold uppercase tracking-wide text-amber-200">
          {t("notForNavigation")}
        </h2>
        <p className="mt-3 text-[13px] leading-relaxed text-slate-300">
          {t("notForNavBody")}
        </p>
        <label className="mt-4 flex items-start gap-2 text-[12px] text-slate-200">
          <input
            type="checkbox"
            data-testid="not-for-nav-ack"
            className="mt-0.5 accent-amber-400"
            checked={acked}
            onChange={(e) => setAcked(e.target.checked)}
          />
          <span>{t("notForNavAck")}</span>
        </label>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="flex-1 px-3 py-2 text-[11px] uppercase border border-slate-600 text-slate-300 rounded-lg"
            onClick={onCancel}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            data-testid="not-for-nav-accept"
            className="flex-1 px-3 py-2 text-[11px] uppercase border border-amber-400/60 bg-amber-400/15 text-amber-100 rounded-lg disabled:opacity-40"
            disabled={!acked}
            onClick={() => { if (acked) onAccept(); }}
          >
            {t("notForNavAccept")}
          </button>
        </div>
      </div>
    </div>
  );
}
