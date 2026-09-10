export interface ChainEntry {
  document_type?: string;
  recording_date?: string;
  grantor?: string;
  grantee?: string;
  book_page?: string;
  instrument_number?: string;
  sale_price?: string;
}

interface Props {
  entries: ChainEntry[];
  currentOwner?: string;
}

function parseUsDate(value: string): number {
  const match = value.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (!match) return 0;
  return new Date(Number(match[3]), Number(match[1]) - 1, Number(match[2])).getTime();
}

function chainKey(entry: ChainEntry): string {
  const date = (entry.recording_date || "").trim();
  const instrument = (entry.instrument_number || "").trim().replace(/\s/g, "");
  if (date || instrument) return `${date}|${instrument}`;
  return `${entry.grantor || ""}|${entry.grantee || ""}|${date}|${entry.sale_price || ""}`;
}

function entryScore(entry: ChainEntry): number {
  return [
    entry.grantor,
    entry.grantee,
    entry.sale_price,
    entry.instrument_number,
    entry.book_page,
  ].filter(Boolean).length;
}

export function mergeChainEntries(
  documents: Record<string, unknown>[],
  rawChain: ChainEntry[] = []
): ChainEntry[] {
  const merged = new Map<string, ChainEntry>();

  const add = (entry: ChainEntry) => {
    const key = chainKey(entry);
    const existing = merged.get(key);
    if (!existing || entryScore(entry) > entryScore(existing)) {
      merged.set(key, entry);
    }
  };

  for (const doc of documents) {
    const ocr = doc.ocr_json as Record<string, unknown> | undefined;
    add({
      document_type: doc.document_type as string | undefined,
      recording_date: doc.recording_date as string | undefined,
      grantor: doc.grantor as string | undefined,
      grantee: doc.grantee as string | undefined,
      book_page: doc.book_page as string | undefined,
      instrument_number: doc.instrument_number as string | undefined,
      sale_price: (ocr?.sale_price as string | undefined) || (doc.sale_price as string | undefined),
    });
  }

  for (const entry of rawChain) {
    add(entry);
  }

  return Array.from(merged.values()).sort(
    (a, b) => parseUsDate(b.recording_date || "") - parseUsDate(a.recording_date || "")
  );
}

function formatOwnership(entry: ChainEntry): string {
  if (entry.grantor && entry.grantee) {
    return `${entry.grantor} → ${entry.grantee}`;
  }
  if (entry.grantor) return `From: ${entry.grantor}`;
  if (entry.grantee) return `To: ${entry.grantee}`;
  return "Seller/buyer names not listed on this county sales record";
}

function formatDetails(entry: ChainEntry): string {
  const parts: string[] = [];
  if (entry.instrument_number) parts.push(`Instrument #${entry.instrument_number}`);
  if (entry.sale_price) parts.push(`Sale price ${entry.sale_price}`);
  if (entry.book_page) parts.push(`Book/Page ${entry.book_page}`);
  return parts.join(" · ");
}

export default function ChainOfTitle({ entries, currentOwner }: Props) {
  if (!entries.length) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-2">Chain of Title</h3>
        <p className="text-sm text-slate-400">No ownership transfers found for this parcel.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h3 className="text-base font-semibold text-slate-800 mb-1">Chain of Title</h3>
      <p className="text-xs text-slate-500 mb-4">
        Ownership history from Sales Information on the assessor report — newest transfers first.
      </p>

      {currentOwner && (
        <div className="mb-5 rounded-lg bg-blue-50 border border-blue-100 px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-blue-600 font-medium">Current Owner</p>
          <p className="text-sm font-semibold text-slate-900 mt-1">{currentOwner}</p>
        </div>
      )}

      <ol className="relative border-l border-slate-200 ml-3 space-y-6">
        {entries.map((entry, i) => (
          <li key={chainKey(entry) || i} className="ml-6">
            <span className="absolute -left-1.5 flex h-3 w-3 rounded-full bg-blue-500 ring-4 ring-white" />
            <time className="text-xs text-slate-400">{entry.recording_date || "Unknown date"}</time>
            <p className="text-sm font-medium text-slate-800 mt-0.5">
              {entry.document_type || "Ownership Transfer"}
            </p>
            <p className="text-sm text-slate-700 mt-1">{formatOwnership(entry)}</p>
            {formatDetails(entry) && (
              <p className="text-xs text-slate-500 mt-1">{formatDetails(entry)}</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
