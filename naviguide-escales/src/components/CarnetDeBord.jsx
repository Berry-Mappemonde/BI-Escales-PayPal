import { useEffect, useState } from "react";
import { sortJournalEntries } from "../hooks/useMomentJournal.js";
import { formatJournalLine } from "./iciMaintenant.js";

export function isCarnetSearch(search = "") {
  const raw = String(search || "");
  const q = new URLSearchParams(raw.startsWith("?") ? raw.slice(1) : raw);
  return q.get("page") === "carnet";
}

export function carnetPageHref(search = "") {
  const raw = String(search || "");
  const q = new URLSearchParams(raw.startsWith("?") ? raw.slice(1) : raw);
  q.set("page", "carnet");
  return `?${q.toString()}`;
}

export function mapPageHref(search = "") {
  const raw = String(search || "");
  const q = new URLSearchParams(raw.startsWith("?") ? raw.slice(1) : raw);
  q.delete("page");
  const s = q.toString();
  return s ? `?${s}` : "/";
}

const CARNET_EVENT = "naviguide:carnet";

function currentSearch() {
  return typeof window !== "undefined" ? window.location.search : "";
}

/** Ouvre ou ferme le carnet sans recharger la page : le mode (Berry ou ma route) reste en mémoire. */
export function followCarnetLink(event, href) {
  if (typeof window === "undefined" || !window.history?.pushState) return;
  if (event && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
  if (event) event.preventDefault();
  window.history.pushState(window.history.state, "", href);
  window.dispatchEvent(new Event(CARNET_EVENT));
}

export function useCarnetPage() {
  const [open, setOpen] = useState(() => isCarnetSearch(currentSearch()));
  useEffect(() => {
    const sync = () => setOpen(isCarnetSearch(currentSearch()));
    window.addEventListener("popstate", sync);
    window.addEventListener(CARNET_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(CARNET_EVENT, sync);
    };
  }, []);
  return open;
}

export function CarnetDeBord({
  title,
  storyLabel,
  journalLabel,
  backLabel,
  backHref,
  chapters = [],
  entries = [],
  lang = "fr",
}) {
  const story = (Array.isArray(chapters) ? chapters : []).filter(Boolean);
  const rows = sortJournalEntries(entries);
  return (
    <main
      data-testid="carnet-de-bord"
      className="fixed inset-0 z-[2300] overflow-auto bg-slate-950 text-slate-100"
    >
      <div className="max-w-2xl mx-auto px-6 py-8">
        <a
          href={backHref}
          onClick={(e) => followCarnetLink(e, backHref)}
          data-testid="carnet-back"
          className="text-sm text-sky-300 hover:text-sky-100 no-underline"
        >
          {backLabel}
        </a>
        <h1 data-testid="carnet-title" className="mt-4 text-2xl font-semibold text-white">
          {title}
        </h1>
        <section data-testid="carnet-story" className="mt-8">
          <h2 className="text-sm font-semibold text-sky-200">{storyLabel}</h2>
          {story.map((text, i) => (
            <p
              key={`${i}-${text.slice(0, 24)}`}
              data-testid="carnet-chapter"
              className="mt-3 text-sm leading-relaxed text-slate-200"
            >
              {text}
            </p>
          ))}
        </section>
        <section data-testid="carnet-journal" className="mt-10">
          <h2 className="text-sm font-semibold text-sky-200">{journalLabel}</h2>
          <ul className="mt-3 m-0 p-0 list-none">
            {rows.map((entry) => (
              <li
                key={entry.signature || `${entry.seq}-${entry.t}`}
                data-testid="carnet-entry"
                data-t={entry.t}
                className="py-1 text-sm leading-snug text-slate-200 break-words"
              >
                {formatJournalLine(entry, lang)}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
