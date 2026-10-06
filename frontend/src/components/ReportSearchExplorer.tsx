import React, { useEffect, useMemo, useRef, useState } from "react";
import { downloadOfficialDocument } from "../api/client";
import TaxRecords from "./TaxRecords";
import {
  Document,
  NameSearchGroup,
  buildNameSearchGroups,
  getDocumentCategory,
  getPrimaryRecorderDocuments,
  DocumentTable,
} from "./DocumentsList";

export type SearchCategory = "recorder" | "assessor" | "tax" | "name_search";

interface SearchSubject {
  id: string;
  category: SearchCategory;
  title: string;
  subtitle?: string;
  badge: string;
  recordCount: number;
  documents: Document[];
  why?: string;
}

interface Props {
  documents: Document[];
  runId?: string;
  queryValue?: string;
  queryType?: string;
  county?: string;
  state?: string;
  nameSearchGroups?: NameSearchGroup[];
  recorderPrimaryDocuments?: Document[];
  taxRecord?: Parameters<typeof TaxRecords>[0]["taxRecord"];
}

const CATEGORY_TABS: { id: SearchCategory; label: string }[] = [
  { id: "recorder", label: "Recorder" },
  { id: "assessor", label: "Assessor" },
  { id: "tax", label: "Tax" },
  { id: "name_search", label: "Name Search" },
];

function truncate(value: string, max = 42): string {
  const text = value.trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function buildSubjects(
  documents: Document[],
  nameSearchGroups: NameSearchGroup[] | undefined,
  queryValue?: string,
  queryType?: string,
  taxRecord?: Props["taxRecord"],
  recorderPrimaryDocuments?: Document[],
): Record<SearchCategory, SearchSubject[]> {
  const recorderDocs = documents.filter((d) => getDocumentCategory(d) === "recorder");
  const assessorDocs = documents.filter((d) => getDocumentCategory(d) === "assessor");
  const groupedNameSearches = buildNameSearchGroups(recorderDocs, nameSearchGroups);
  const primaryRecorderDocs = getPrimaryRecorderDocuments(recorderDocs, {
    providedPrimary: recorderPrimaryDocuments,
    nameSearchGroups,
  });

  const recorderTitle =
    queryType === "book_page" && queryValue
      ? `Book/Page ${queryValue}`
      : queryValue
        ? truncate(queryValue, 48)
        : "County Recorder Search";

  const recorderSubjects: SearchSubject[] = primaryRecorderDocs.length
    ? [
        {
          id: "recorder-primary",
          category: "recorder",
          title: recorderTitle,
          subtitle: "Official records from recorder node",
          badge: "Recorder",
          recordCount: primaryRecorderDocs.length,
          documents: primaryRecorderDocs,
          //Why:queryType || "recorder",
        },
      ]
    : [];

  const folio =
    assessorDocs.find((d) => d.instrument_number)?.instrument_number ||
    queryValue;

  const assessorSubjects: SearchSubject[] = assessorDocs.length
    ? [
        {
          id: "assessor-primary",
          category: "assessor",
          title: folio ? `Folio ${folio}` : "Property Assessor",
          subtitle: "Sales history and appraiser reports",
          badge: "Assessor",
          recordCount: assessorDocs.length,
          documents: assessorDocs,
          //Why:"Assessor",
        },
      ]
    : [];

  const taxAccount = taxRecord?.raw_json?.tax_account || taxRecord?.owner_name || "Tax Account";
  const taxSubjects: SearchSubject[] = taxRecord
    ? [
        {
          id: "tax-primary",
          category: "tax",
          title: String(taxAccount),
          subtitle: taxRecord.property_address || "County tax records",
          badge: "Tax",
          recordCount: (taxRecord.raw_json?.account_history || []).length || 1,
          documents: [],
          //Why:"Tax",
        },
      ]
    : [];

  const nameSearchSubjects: SearchSubject[] = groupedNameSearches.map((group) => ({
    id: `name-search-${group.name}`,
    category: "name_search" as const,
    title: group.name,
    subtitle: "Party name search results",
    badge: "Name",
    recordCount: group.document_count ?? group.documents.length,
    documents: group.documents,
    //Why:"Name Searcher",
  }));

  return {
    recorder: recorderSubjects,
    assessor: assessorSubjects,
    tax: taxSubjects,
    name_search: nameSearchSubjects,
  };
}

export default function ReportSearchExplorer({
  documents,
  runId,
  queryValue,
  queryType,
  county,
  state,
  nameSearchGroups,
  recorderPrimaryDocuments,
  taxRecord,
}: Props) {
  const [category, setCategory] = useState<SearchCategory>("recorder");
  const [selectedId, setSelectedId] = useState<string>("");
  const [downloading, setDownloading] = useState(false);
  const didPickInitialCategory = useRef(false);

  const subjectsByCategory = useMemo(
    () =>
      buildSubjects(
        documents,
        nameSearchGroups,
        queryValue,
        queryType,
        taxRecord,
        recorderPrimaryDocuments,
      ),
    [documents, nameSearchGroups, queryValue, queryType, taxRecord, recorderPrimaryDocuments],
  );

  const subjects = subjectsByCategory[category];
  const totalRecords = subjects.reduce((sum, item) => sum + item.recordCount, 0);

  // Pick the first tab with data once on load; do not override explicit tab clicks.
  useEffect(() => {
    if (didPickInitialCategory.current) return;
    const firstCategoryWithData = CATEGORY_TABS.find((tab) => subjectsByCategory[tab.id].length > 0);
    if (!firstCategoryWithData) return;
    didPickInitialCategory.current = true;
    setCategory(firstCategoryWithData.id);
    setSelectedId(subjectsByCategory[firstCategoryWithData.id][0]?.id || "");
  }, [subjectsByCategory]);

  useEffect(() => {
    if (!subjects.length) {
      if (selectedId) setSelectedId("");
      return;
    }
    if (!subjects.some((item) => item.id === selectedId)) {
      setSelectedId(subjects[0].id);
    }
  }, [category, subjects, selectedId]);

  const selected = subjects.find((item) => item.id === selectedId) || subjects[0];

  const handleDownload = async (filename?: string) => {
    if (!runId) return;
    try {
      setDownloading(true);
      await downloadOfficialDocument(runId, filename);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  const categoryLabel =
    category === "recorder"
      ? "Recorder Searches"
      : category === "assessor"
        ? "Assessor Searches"
        : category === "tax"
          ? "Tax Records"
          : "Name Searches";

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-200 dark:border-white/[0.08] flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-bold text-slate-900 dark:text-zinc-100">{categoryLabel}</h3>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
            {county ? `${county.charAt(0).toUpperCase()}${county.slice(1)} County` : "County"}
            {state ? `, ${state}` : ""} — select a subject on the left to view its records.
          </p>
        </div>
        {runId && (
          <button
            type="button"
            onClick={() => handleDownload()}
            disabled={downloading}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50"
          >
            {downloading ? "Downloading..." : "Download Official Documents"}
          </button>
        )}
      </div>

      <div className="px-6 pt-4 border-b border-slate-200 dark:border-white/[0.08]">
        <div className="flex flex-wrap gap-2">
          {CATEGORY_TABS.map((tab) => {
            const count = subjectsByCategory[tab.id].length;
            const active = category === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setCategory(tab.id);
                  setSelectedId(subjectsByCategory[tab.id][0]?.id || "");
                }}
                className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                  active
                    ? "bg-sky-100 dark:bg-sky-950/50 text-sky-800 dark:text-sky-200 border-sky-300 dark:border-sky-800"
                    : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300 border-slate-200 dark:border-white/[0.08] hover:bg-slate-50 dark:hover:bg-zinc-800"
                }`}
              >
                {tab.label}
                {count > 0 ? ` (${count})` : ""}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-slate-500 dark:text-zinc-400 py-3">
          {subjects.length} subject{subjects.length === 1 ? "" : "s"} • {totalRecords} total record
          {totalRecords === 1 ? "" : "s"}
        </p>
      </div>

      {!subjects.length ? (
        <div className="p-8 text-sm text-slate-500 dark:text-zinc-400 italic">
          No {categoryLabel.toLowerCase()} found for this run.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)] min-h-[420px]">
          <aside className="border-b lg:border-b-0 lg:border-r border-slate-200 dark:border-white/[0.08] bg-slate-50/70 dark:bg-zinc-950/40">
            <div className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400 border-b border-slate-200 dark:border-white/[0.08]">
              Search Subjects
            </div>
            <div className="divide-y divide-slate-200 dark:divide-white/[0.06]">
              {subjects.map((subject) => {
                const active = selected?.id === subject.id;
                return (
                  <button
                    key={subject.id}
                    type="button"
                    onClick={() => setSelectedId(subject.id)}
                    className={`w-full text-left px-4 py-3 transition-colors ${
                      active
                        ? "bg-sky-50 dark:bg-sky-950/30 border-l-2 border-sky-500"
                        : "hover:bg-white dark:hover:bg-zinc-900/60 border-l-2 border-transparent"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 text-slate-400 dark:text-zinc-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-slate-900 dark:text-zinc-100 break-words">
                            {truncate(subject.title, 36)}
                          </span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-200 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300">
                            {subject.badge}
                          </span>
                        </div>
                        {subject.subtitle && (
                          <p className="text-[11px] text-slate-500 dark:text-zinc-400 mt-0.5">{subject.subtitle}</p>
                        )}
                        <p className="text-xs text-slate-600 dark:text-zinc-300 mt-1 font-medium">
                          {subject.recordCount} record{subject.recordCount === 1 ? "" : "s"}
                        </p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          <section className="p-6">
            {selected && (
              <>
                <div className="mb-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-xl font-bold text-slate-900 dark:text-zinc-100">{selected.title}</h4>
                    <span className="px-2 py-0.5 rounded text-xs font-semibold bg-sky-100 dark:bg-sky-950/50 text-sky-800 dark:text-sky-200 border border-sky-200 dark:border-sky-800/40">
                      {selected.badge}
                    </span>
                  </div>
                  {selected.subtitle && (
                    <p className="text-sm text-slate-500 dark:text-zinc-400 mt-1">{selected.subtitle}</p>
                  )}
                  {selected.why && (
                    <p className="text-xs text-slate-500 dark:text-zinc-400 mt-2">
                      //Why:<span className="font-semibold text-slate-700 dark:text-zinc-200">{selected.why}</span>
                    </p>
                  )}
                </div>

                {selected.category === "tax" ? (
                  <div className="-mx-2">
                    <TaxRecords
                      taxRecord={taxRecord}
                      taxDocuments={documents.filter(
                        (doc) => doc.document_type === "tax_bill" || doc.ocr_json?.source === "tax_bill",
                      )}
                      runId={runId}
                      embedded
                    />
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between mb-3">
                      <h5 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wide">
                        Records
                      </h5>
                      <span className="text-xs text-slate-500 dark:text-zinc-400">
                        {selected.recordCount} result{selected.recordCount === 1 ? "" : "s"}
                      </span>
                    </div>
                    <DocumentTable
                      documents={selected.documents}
                      runId={runId}
                      onDownload={handleDownload}
                      downloading={downloading}
                    />
                  </>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
