import { useState } from "react";

interface TaxTabTable {
  headers?: string[];
  rows?: string[][];
}

interface TaxTabData {
  tables?: TaxTabTable[];
  body_text?: string;
}

interface AccountHistoryRow {
  bill?: string;
  amount_due?: string;
  status?: string;
  date?: string;
  action?: string;
}

interface BillDetail {
  bill_title?: string;
  bill_summary?: {
    bill?: string;
    escrow_code?: string;
    millage_code?: string;
    amount_due?: string;
    status?: string;
  };
  ad_valorem_taxes?: {
    headers?: string[];
    rows?: string[][];
  };
  non_ad_valorem_assessments?: {
    headers?: string[];
    rows?: string[][];
  };
  combined_taxes?: string;
  parcel_details?: Record<string, string>;
  exemptions?: Record<string, string>;
  legal_description?: string;
  location?: {
    range?: string;
    township?: string;
    section?: string;
    block?: string;
    use_code?: string;
  };
}

interface TaxRecordData {
  owner_name?: string;
  property_address?: string;
  source_url?: string;
  raw_json?: {
    platform?: string;
    tax_account?: string;
    tax_year?: string;
    bill_number?: string;
    amount_due?: number;
    amount_due_message?: string;
    last_payment?: string;
    property_address?: string;
    mailing_address?: string;
    exemptions_summary?: string;
    account_history?: AccountHistoryRow[];
    last_two_bills?: BillDetail[];
    yearly_due_summary?: Array<{ year?: string; label?: string; due?: string }>;
    tabs?: Record<string, TaxTabData>;
  };
}

interface Props {
  taxRecord?: TaxRecordData | null;
}

export default function TaxRecords({ taxRecord }: Props) {
  const [selectedBillIdx, setSelectedBillIdx] = useState(0);

  if (!taxRecord) {
    return (
      <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 transition-colors">
        <h3 className="font-bold text-slate-900 dark:text-zinc-100 mb-2">Tax Records</h3>
        <p className="text-sm text-slate-500 dark:text-zinc-400">No tax record data found for this run.</p>
      </div>
    );
  }

  const tax = taxRecord.raw_json || {};
  const tabs = tax.tabs || {};
  const history = tax.account_history || [];
  const bills = tax.last_two_bills || [];
  const activeBill = bills[selectedBillIdx] || bills[0];

  const isPaid = (tax.amount_due_message || "").toLowerCase().includes("paid in full") ||
    tax.amount_due === 0;

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 space-y-6 transition-colors">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-bold text-lg text-slate-900 dark:text-zinc-100">
              {tax.tax_account || "Property Tax Account"}
            </h3>
            {isPaid ? (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40">
                Paid in Full
              </span>
            ) : tax.amount_due != null && tax.amount_due > 0 ? (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/40">
                Amount Due: ${Number(tax.amount_due).toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            ) : null}
          </div>
          {tax.amount_due_message && (
            <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">{tax.amount_due_message}</p>
          )}
        </div>

        {taxRecord.source_url && (
          <a
            href={taxRecord.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-semibold text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center gap-1"
          >
            County Tax Portal &rarr;
          </a>
        )}
      </div>

      {/* Account Info Grid */}
      <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 p-4 rounded-xl bg-slate-50/80 dark:bg-zinc-900/60 border border-slate-200/80 dark:border-white/[0.06] text-sm">
        <div>
          <dt className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Owner</dt>
          <dd className="mt-1 font-bold text-slate-900 dark:text-zinc-100">{taxRecord.owner_name || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Situs / Address</dt>
          <dd className="mt-1 font-bold text-slate-900 dark:text-zinc-100">{taxRecord.property_address || tax.property_address || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Most Recent Payment</dt>
          <dd className="mt-1 font-bold text-slate-900 dark:text-zinc-100">{tax.last_payment || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Exemptions</dt>
          <dd className="mt-1 font-bold text-emerald-700 dark:text-emerald-400">{tax.exemptions_summary || "—"}</dd>
        </div>
      </dl>

      {/* Account History Table */}
      {history.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider">
              Account History
            </h4>
            <span className="text-xs text-slate-500 dark:text-zinc-400">{history.length} bills recorded</span>
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-white/[0.08]">
            <table className="min-w-full text-xs text-left">
              <thead className="bg-slate-100 dark:bg-zinc-900 text-slate-800 dark:text-zinc-200 uppercase font-semibold border-b border-slate-200 dark:border-white/[0.08]">
                <tr>
                  <th className="px-3 py-2">Bill</th>
                  <th className="px-3 py-2">Amount Due</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Date / Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05] bg-white dark:bg-[#161b22]">
                {history.map((row, idx) => (
                  <tr key={idx} className="hover:bg-slate-50/70 dark:hover:bg-zinc-800/30 transition-colors">
                    <td className="px-3 py-2 font-semibold text-slate-900 dark:text-zinc-100">{row.bill || "—"}</td>
                    <td className="px-3 py-2 font-mono text-slate-800 dark:text-zinc-200">{row.amount_due || "$0.00"}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                        (row.status || "").toLowerCase().includes("paid")
                          ? "bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40"
                          : "bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/40"
                      }`}>
                        {row.status || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-zinc-400">
                      {[row.date, row.action].filter(Boolean).join(" • ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Last Two Bill Detailed Breakdowns */}
      {bills.length > 0 && (
        <div className="pt-2 space-y-4 border-t border-slate-200 dark:border-white/[0.08]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-blue-600 dark:bg-blue-400 inline-block"></span>
                Bill Details (Last {bills.length} Summaries Captured)
              </h4>
              <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                Opened via the county portal information button with itemized assessments and taxing authority millages.
              </p>
            </div>

            {/* Bill Selector Tabs */}
            <div className="flex items-center gap-1 p-1 bg-slate-100 dark:bg-zinc-800/60 rounded-lg border border-slate-200 dark:border-white/[0.06]">
              {bills.map((b, idx) => {
                const label = b.bill_summary?.bill || b.bill_title || `Bill #${idx + 1}`;
                const active = selectedBillIdx === idx;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setSelectedBillIdx(idx)}
                    className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                      active
                        ? "bg-white dark:bg-zinc-700 text-blue-700 dark:text-blue-300 shadow-sm"
                        : "text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Active Bill Content */}
          {activeBill && (
            <div className="rounded-xl border border-slate-200 dark:border-white/[0.08] bg-slate-50/50 dark:bg-zinc-900/40 p-5 space-y-5">
              {/* Summary KPIs */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white dark:bg-[#161b22] p-4 rounded-lg border border-slate-200 dark:border-white/[0.08]">
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500 dark:text-zinc-400 font-semibold">Bill Year</span>
                  <p className="text-sm font-bold text-slate-900 dark:text-zinc-100 mt-0.5">
                    {activeBill.bill_summary?.bill || "—"}
                  </p>
                </div>
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500 dark:text-zinc-400 font-semibold">Millage Code</span>
                  <p className="text-sm font-bold text-slate-900 dark:text-zinc-100 mt-0.5">
                    {activeBill.bill_summary?.millage_code || "—"}
                  </p>
                </div>
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500 dark:text-zinc-400 font-semibold">Status</span>
                  <p className="text-sm font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">
                    {activeBill.bill_summary?.status || "PAID"}
                  </p>
                </div>
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500 dark:text-zinc-400 font-semibold">Combined Taxes</span>
                  <p className="text-sm font-bold text-blue-700 dark:text-blue-400 mt-0.5">
                    {activeBill.combined_taxes || activeBill.bill_summary?.amount_due || "—"}
                  </p>
                </div>
              </div>

              {/* Ad Valorem Taxes Table */}
              {activeBill.ad_valorem_taxes?.rows && activeBill.ad_valorem_taxes.rows.length > 0 && (
                <div className="space-y-2">
                  <h5 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-zinc-100">
                    Ad Valorem Taxes
                  </h5>
                  <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#161b22]">
                    <table className="min-w-full text-xs text-left">
                      <thead className="bg-slate-100 dark:bg-zinc-900 text-slate-800 dark:text-zinc-200 font-semibold border-b border-slate-200 dark:border-white/[0.08]">
                        <tr>
                          {activeBill.ad_valorem_taxes.headers?.map((h, i) => (
                            <th key={i} className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">{h}</th>
                          )) || (
                            <>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Taxing Authority</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Millage</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Assessed</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Exemption</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Taxable</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Tax</th>
                            </>
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                        {activeBill.ad_valorem_taxes.rows.map((row, rIdx) => {
                          const isHeading = row.length === 2 && row[1] === "";
                          const isTotal = (row[0] || "").toLowerCase().includes("total");
                          return (
                            <tr
                              key={rIdx}
                              className={
                                isHeading
                                  ? "bg-slate-50 dark:bg-zinc-900/60 font-bold text-slate-900 dark:text-zinc-100"
                                  : isTotal
                                  ? "bg-blue-50/50 dark:bg-blue-950/30 font-bold text-slate-900 dark:text-zinc-100"
                                  : "hover:bg-slate-50/80 dark:hover:bg-zinc-800/30 text-slate-800 dark:text-zinc-200"
                              }
                            >
                              {row.map((cell, cIdx) => (
                                <td key={cIdx} className={`px-3 py-1.5 ${cIdx > 0 ? "text-right font-mono" : ""}`}>
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Non-Ad Valorem Assessments Table */}
              {activeBill.non_ad_valorem_assessments?.rows && activeBill.non_ad_valorem_assessments.rows.length > 0 && (
                <div className="space-y-2">
                  <h5 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-zinc-100">
                    Non-Ad Valorem Assessments
                  </h5>
                  <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#161b22]">
                    <table className="min-w-full text-xs text-left">
                      <thead className="bg-slate-100 dark:bg-zinc-900 text-slate-800 dark:text-zinc-200 font-semibold border-b border-slate-200 dark:border-white/[0.08]">
                        <tr>
                          {activeBill.non_ad_valorem_assessments.headers?.map((h, i) => (
                            <th key={i} className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">{h}</th>
                          )) || (
                            <>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Levying Authority</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Rate</th>
                              <th className="px-3 py-2 border-b border-slate-200 dark:border-white/[0.08]">Amount</th>
                            </>
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                        {activeBill.non_ad_valorem_assessments.rows.map((row, rIdx) => (
                          <tr key={rIdx} className="hover:bg-slate-50/70 dark:hover:bg-zinc-800/30 text-slate-800 dark:text-zinc-200">
                            {row.map((cell, cIdx) => (
                              <td key={cIdx} className={`px-3 py-1.5 ${cIdx > 0 ? "text-right font-mono" : ""}`}>
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Parcel Details & Exemptions Breakdown */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                {/* Location & Legal */}
                <div className="bg-white dark:bg-[#161b22] p-4 rounded-lg border border-slate-200 dark:border-white/[0.08] space-y-3">
                  <h6 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-zinc-100">
                    Parcel Details & Location
                  </h6>
                  {activeBill.location && Object.keys(activeBill.location).length > 0 && (
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      {Object.entries(activeBill.location).map(([k, v]) => (
                        <div key={k} className="p-2 rounded bg-slate-50 dark:bg-zinc-900/60 border border-slate-200 dark:border-white/[0.06]">
                          <span className="text-slate-500 dark:text-zinc-400 capitalize block">{k.replace("_", " ")}</span>
                          <span className="font-bold text-slate-900 dark:text-zinc-100">{v}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {activeBill.legal_description && (
                    <div className="text-xs text-slate-600 dark:text-zinc-300">
                      <span className="font-semibold text-slate-900 dark:text-zinc-100 block mb-1">Legal Description:</span>
                      <p className="bg-slate-50 dark:bg-zinc-900/60 p-2.5 rounded border border-slate-200 dark:border-white/[0.06] font-mono text-[11px] leading-relaxed text-slate-800 dark:text-zinc-200">
                        {activeBill.legal_description}
                      </p>
                    </div>
                  )}
                </div>

                {/* Itemized Exemptions */}
                <div className="bg-white dark:bg-[#161b22] p-4 rounded-lg border border-slate-200 dark:border-white/[0.08] space-y-3">
                  <h6 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-zinc-100">
                    Itemized Exemptions
                  </h6>
                  {activeBill.exemptions && Object.keys(activeBill.exemptions).length > 0 ? (
                    <div className="space-y-1.5">
                      {Object.entries(activeBill.exemptions).map(([k, v]) => (
                        <div
                          key={k}
                          className="flex items-center justify-between p-2 rounded bg-emerald-50/50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/40 text-xs"
                        >
                          <span className="font-semibold text-emerald-900 dark:text-emerald-300">{k}</span>
                          <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400">{v}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 dark:text-zinc-400 italic">No specific exemptions breakdown listed.</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Fallback for other county portals / tabs if no last_two_bills */}
      {bills.length === 0 && (
        <>
          {Object.entries(tabs)
            .filter(([name]) => name !== "Summary")
            .map(([name, tab]) => (
              <div key={name}>
                <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 mb-2">{name}</h4>
                {(tab.tables || []).map((table, idx) => (
                  <div key={idx} className="overflow-x-auto mb-3 rounded-lg border border-slate-200 dark:border-white/[0.08]">
                    <table className="min-w-full text-xs">
                      {table.headers && table.headers.length > 0 && (
                        <thead className="bg-slate-100 dark:bg-zinc-900 text-slate-800 dark:text-zinc-200 border-b border-slate-200 dark:border-white/[0.08]">
                          <tr>
                            {table.headers.map((h) => (
                              <th key={h} className="px-2 py-1 text-left font-semibold">{h}</th>
                            ))}
                          </tr>
                        </thead>
                      )}
                      <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05] bg-white dark:bg-[#161b22]">
                        {(table.rows || [])
                          .filter((row) => !table.headers || JSON.stringify(row) !== JSON.stringify(table.headers))
                          .map((row, rowIdx) => (
                            <tr key={rowIdx} className="hover:bg-slate-50/70 dark:hover:bg-zinc-800/30 text-slate-800 dark:text-zinc-200">
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
        </>
      )}
    </div>
  );
}
