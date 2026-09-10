type Props = {
  property: Record<string, unknown>;
};

const STRUCTURED_KEYS = new Set([
  "assessment_rows",
  "owner_rows",
  "chain_of_title",
  "source_url",
  "key_value",
  "parcel_detail",
  "sales_history",
  "building_characteristics",
  "land_breakdown",
  "assessment_fields",
]);

function formatLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return "—";
  return String(value);
}

function isRecordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length > 0 && value.every((row) => row && typeof row === "object");
}

function DataTable({ rows, title }: { rows: Record<string, unknown>[]; title: string }) {
  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>())
  );

  if (!headers.length) return null;

  return (
    <div>
      <h4 className="text-sm font-semibold text-slate-700 mb-2">{title}</h4>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
          <thead className="bg-slate-50">
            <tr>
              {headers.map((header) => (
                <th key={header} className="px-3 py-2 text-left text-slate-600 font-medium whitespace-nowrap">
                  {formatLabel(header)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx} className="border-t border-slate-100">
                {headers.map((header) => (
                  <td key={header} className="px-3 py-2 whitespace-nowrap">
                    {formatScalar(row[header])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PropertyDetails({ property }: Props) {
  const raw = (property.raw_json as Record<string, unknown>) || {};
  const assessmentRows = Array.isArray(raw.assessment_rows) ? raw.assessment_rows : [];
  const salesHistory = isRecordArray(raw.sales_history) ? raw.sales_history : [];
  const buildingRows = isRecordArray(raw.building_characteristics) ? raw.building_characteristics : [];
  const landRows = isRecordArray(raw.land_breakdown) ? raw.land_breakdown : [];
  const assessmentFields =
    raw.assessment_fields && typeof raw.assessment_fields === "object" && !Array.isArray(raw.assessment_fields)
      ? Object.entries(raw.assessment_fields as Record<string, unknown>).filter(
          ([, value]) => value !== null && value !== undefined && value !== ""
        )
      : [];

  const ownerRows = Array.isArray(raw.owner_rows) ? raw.owner_rows : [];

  const detailFields = Object.entries(raw).filter(
    ([key, value]) => !STRUCTURED_KEYS.has(key) && (typeof value !== "object" || value === null)
  );

  const sourceUrl = typeof raw.source_url === "string" ? raw.source_url : null;
  const address =
    String(property.property_address || raw["location address"] || raw.address || "—");
  const legalDesc =
    String(property.legal_desc || raw["legal information"] || raw["legal description"] || "—");

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-base font-semibold text-slate-800">Property Details</h3>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-blue-600 hover:underline shrink-0"
          >
            View on Assessor Site
          </a>
        )}
      </div>

      <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-slate-500">Owner</dt>
          <dd className="font-medium">
            {ownerRows.length
              ? ownerRows
                  .map((row) => String((row as Record<string, string>)["Owner Name"] || ""))
                  .filter(Boolean)
                  .join("; ")
              : String(property.owner_name || "—")}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">APN / Parcel</dt>
          <dd className="font-medium">{String(property.apn || "—")}</dd>
        </div>
        <div className="md:col-span-2">
          <dt className="text-slate-500">Address</dt>
          <dd className="font-medium">{address}</dd>
        </div>
        <div className="md:col-span-2">
          <dt className="text-slate-500">Legal Description</dt>
          <dd className="font-medium">{legalDesc}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Assessed Value</dt>
          <dd className="font-medium">
            {property.assessed_value ? `$${property.assessed_value}` : "—"}
          </dd>
        </div>
      </dl>

      {detailFields.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">All Assessor Fields</h4>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            {detailFields.map(([key, value]) => (
              <div key={key} className="border border-slate-100 rounded-lg px-3 py-2">
                <dt className="text-slate-500 text-xs">{formatLabel(key)}</dt>
                <dd className="font-medium break-words">{formatScalar(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {salesHistory.length > 0 && <DataTable rows={salesHistory} title="Sales History" />}

      {buildingRows.length > 0 && <DataTable rows={buildingRows} title="Building Characteristics" />}

      {landRows.length > 0 && <DataTable rows={landRows} title="Land Breakdown" />}

      {assessmentFields.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Assessment Fields</h4>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            {assessmentFields.map(([key, value]) => (
              <div key={key} className="border border-slate-100 rounded-lg px-3 py-2">
                <dt className="text-slate-500 text-xs">{formatLabel(key)}</dt>
                <dd className="font-medium break-words">{formatScalar(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {assessmentRows.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Assessment History</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  {Object.keys(assessmentRows[0] as Record<string, string>).map((header) => (
                    <th key={header} className="px-3 py-2 text-left text-slate-600 font-medium">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {assessmentRows.map((row, idx) => (
                  <tr key={idx} className="border-t border-slate-100">
                    {Object.values(row as Record<string, string>).map((cell, cellIdx) => (
                      <td key={cellIdx} className="px-3 py-2">{String(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
