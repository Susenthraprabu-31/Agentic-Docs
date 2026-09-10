interface TaxTabTable {
  headers?: string[];
  rows?: string[][];
}

interface TaxTabData {
  tables?: TaxTabTable[];
  body_text?: string;
}

interface TaxRecordData {
  owner_name?: string;
  property_address?: string;
  raw_json?: {
    tax_account?: string;
    tax_year?: string;
    bill_number?: string;
    amount_due?: number;
    mailing_address?: string;
    yearly_due_summary?: Array<{ year?: string; label?: string; due?: string }>;
    tabs?: Record<string, TaxTabData>;
  };
}

interface Props {
  taxRecord?: TaxRecordData | null;
}

export default function TaxRecords({ taxRecord }: Props) {
  if (!taxRecord) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="font-semibold mb-2">Tax Records</h3>
        <p className="text-sm text-slate-500">No tax record data found for this run.</p>
      </div>
    );
  }

  const tax = taxRecord.raw_json || {};
  const tabs = tax.tabs || {};

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
      <h3 className="font-semibold text-slate-800">Tax Records</h3>

      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-slate-500">Tax Account</dt>
          <dd className="font-medium">{tax.tax_account || "—"}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Tax Year</dt>
          <dd className="font-medium">{tax.tax_year || "—"}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Bill Number</dt>
          <dd className="font-medium">{tax.bill_number || "—"}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Amount Due</dt>
          <dd className="font-medium">
            {tax.amount_due != null ? `$${Number(tax.amount_due).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : "—"}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-slate-500">Owner</dt>
          <dd className="font-medium">{taxRecord.owner_name || "—"}</dd>
        </div>
      </dl>

      {Object.entries(tabs)
        .filter(([name]) => name !== "Summary")
        .map(([name, tab]) => (
          <div key={name}>
            <h4 className="text-sm font-semibold text-slate-700 mb-2">{name}</h4>
            {(tab.tables || []).map((table, idx) => (
              <div key={idx} className="overflow-x-auto mb-3">
                <table className="min-w-full text-xs border border-slate-200">
                  {table.headers && table.headers.length > 0 && (
                    <thead className="bg-slate-50">
                      <tr>
                        {table.headers.map((h) => (
                          <th key={h} className="px-2 py-1 text-left border-b">{h}</th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {(table.rows || [])
                      .filter((row) => !table.headers || JSON.stringify(row) !== JSON.stringify(table.headers))
                      .map((row, rowIdx) => (
                        <tr key={rowIdx} className="border-b border-slate-100">
                          {row.map((cell, cellIdx) => (
                            <td key={cellIdx} className="px-2 py-1">{cell}</td>
                          ))}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}
