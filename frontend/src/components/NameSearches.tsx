import React from "react";

export interface NameSearchEntry {
  name: string;
  source?: string;
}

interface Props {
  entries: NameSearchEntry[];
}

export default function NameSearches({ entries }: Props) {
  const [open, setOpen] = React.useState(true);

  if (!entries.length) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] overflow-hidden transition-colors">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="w-full flex items-center justify-between gap-3 px-6 py-4 text-left hover:bg-slate-50/80 dark:hover:bg-zinc-900/40 transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <svg
            className={`w-4 h-4 text-slate-500 dark:text-zinc-400 shrink-0 transition-transform ${open ? "rotate-0" : "-rotate-90"}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
          <div className="w-8 h-8 rounded-lg bg-violet-600/10 dark:bg-violet-500/20 text-violet-600 dark:text-violet-400 flex items-center justify-center shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100 tracking-wide uppercase">
              Name Searches
            </h3>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Names actually searched by the Name Searcher node in this run
            </p>
          </div>
        </div>
        <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 shrink-0">
          {entries.length}
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-100 dark:border-white/[0.06]">
          <div className="grid grid-cols-[1fr_auto] gap-4 px-6 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-zinc-400 border-b border-slate-100 dark:border-white/[0.06]">
            <div>Name</div>
            <div className="text-right">Source</div>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-white/[0.06]">
            {entries.map((entry) => (
              <div
                key={`${entry.name}|${entry.source || ""}`}
                className="grid grid-cols-[1fr_auto] gap-4 px-6 py-2.5 text-sm"
              >
                <div className="font-mono text-slate-900 dark:text-zinc-100 break-words">{entry.name}</div>
                <div className="text-slate-500 dark:text-zinc-400 text-right whitespace-nowrap">
                  {entry.source || "—"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
