interface Document {
  document_type?: string;
  recording_date?: string;
  book_page?: string;
  instrument_number?: string;
  grantor?: string;
  grantee?: string;
  source_url?: string;
  ocr_json?: {
    sale_price?: string;
    source?: string;
    section?: string;
  };
}

interface Props {
  documents: Document[];
}

function sourceLabel(doc: Document): string {
  const source = doc.ocr_json?.source;
  if (source === "assessor_sales") return "Assessor Sales";
  if (source === "assessor") return "Assessor";
  if (source) return String(source);
  return "Recorder";
}

export default function DocumentsList({ documents }: Props) {
  if (!documents.length) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-2">Recorded Transactions</h3>
        <p className="text-sm text-slate-400">No transaction history found yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 overflow-x-auto">
      <h3 className="text-base font-semibold text-slate-800 mb-1">Recorded Transactions</h3>
      <p className="text-xs text-slate-500 mb-4">
        Deed and sale records from Sales Information on the assessor report and county recorder when available.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            <th className="pb-2 pr-4">Type</th>
            <th className="pb-2 pr-4">Date</th>
            <th className="pb-2 pr-4">Instrument</th>
            <th className="pb-2 pr-4">Sale Price</th>
            <th className="pb-2 pr-4">Grantor</th>
            <th className="pb-2 pr-4">Grantee</th>
            <th className="pb-2 pr-4">Source</th>
            <th className="pb-2">Link</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc, i) => (
            <tr key={i} className="border-b border-slate-100">
              <td className="py-2 pr-4">{doc.document_type || "—"}</td>
              <td className="py-2 pr-4">{doc.recording_date || "—"}</td>
              <td className="py-2 pr-4">{doc.instrument_number || "—"}</td>
              <td className="py-2 pr-4">{doc.ocr_json?.sale_price || "—"}</td>
              <td className="py-2 pr-4">{doc.grantor || "—"}</td>
              <td className="py-2 pr-4">{doc.grantee || "—"}</td>
              <td className="py-2 pr-4 text-xs text-slate-500">{sourceLabel(doc)}</td>
              <td className="py-2">
                {doc.source_url ? (
                  <a
                    href={doc.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline text-xs"
                  >
                    Open
                  </a>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
