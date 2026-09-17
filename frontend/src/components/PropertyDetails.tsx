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
  "sections",
  "fields",
  "assessment_history",
  "assessment_information",
  "benefits_information",
  "taxable_value_information",
  "assessment_information_table",
  "benefits_information_table",
  "taxable_value_information_table",
  "sales_information_table",
  "land_information_table",
  "building_information_table",
  "extra_features_table",
  "land_information",
  "building_information",
  "extra_features",
  "additional_information",
  "platform",
  "folio",
  "owner",
  "assessed_value_text",
  "full_legal_description",
  "market_value",
  "mailing_address",
  "subdivision",
  "pa_primary_zone",
  "pa_secondary_zone",
  "primary_land_use",
  "lot_size",
  "actual_area",
  "adjusted_area",
  "floors",
  "living_units",
  "bedrooms",
  "bathrooms",
  "half_baths",
  "living_area",
  "year_built",
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

function isSectionTable(value: unknown): value is { headers: string[]; rows: string[][] } {
  if (!value || typeof value !== "object") return false;
  const table = value as { headers?: unknown; rows?: unknown };
  return Array.isArray(table.headers) && Array.isArray(table.rows);
}

function SectionTable({ table, title }: { table: { headers: string[]; rows: string[][] }; title: string }) {
  if (!table.rows.length) return null;
  const colCount = Math.max(table.headers.length, ...table.rows.map((row) => row.length));
  const headers =
    table.headers.length >= colCount
      ? table.headers
      : [...table.headers, ...Array.from({ length: colCount - table.headers.length }, () => "")];

  return (
    <div>
      <h4 className="text-sm font-semibold text-slate-700 mb-2">{title}</h4>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
          <thead className="bg-slate-100">
            <tr>
              {headers.map((header, idx) => (
                <th key={`${header}-${idx}`} className="px-3 py-2 text-left text-slate-700 font-semibold whitespace-nowrap">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIdx) => (
              <tr key={rowIdx} className="border-t border-slate-100 even:bg-slate-50/60">
                {Array.from({ length: colCount }).map((_, colIdx) => (
                  <td key={colIdx} className="px-3 py-2 whitespace-nowrap">
                    {row[colIdx] ?? ""}
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

function KeyValueBlock({ data, title }: { data: Record<string, unknown>; title: string }) {
  const entries = Object.entries(data).filter(
    ([, value]) => value !== null && value !== undefined && value !== ""
  );
  if (!entries.length) return null;
  return (
    <div>
      <h4 className="text-sm font-semibold text-slate-700 mb-2">{title}</h4>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
        {entries.map(([key, value]) => (
          <div key={key} className="border border-slate-100 rounded-lg px-3 py-2">
            <dt className="text-slate-500 text-xs">{formatLabel(key)}</dt>
            <dd className="font-medium break-words">{formatScalar(value)}</dd>
          </div>
        ))}
      </dl>
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

  const parcelFields =
    raw.fields && typeof raw.fields === "object" && !Array.isArray(raw.fields)
      ? Object.entries(raw.fields as Record<string, unknown>).filter(
          ([, value]) => value !== null && value !== undefined && value !== ""
        )
      : [];

  const assessmentHistory = isRecordArray(raw.assessment_history) ? raw.assessment_history : [];

  const assessmentTable = isSectionTable(raw.assessment_information_table)
    ? raw.assessment_information_table
    : null;
  const benefitsTable = isSectionTable(raw.benefits_information_table) ? raw.benefits_information_table : null;
  const taxableTable = isSectionTable(raw.taxable_value_information_table)
    ? raw.taxable_value_information_table
    : null;
  const salesTable = isSectionTable(raw.sales_information_table) ? raw.sales_information_table : null;
  const landTable = isSectionTable(raw.land_information_table) ? raw.land_information_table : null;
  const buildingTable = isSectionTable(raw.building_information_table) ? raw.building_information_table : null;
  const extraFeaturesTable = isSectionTable(raw.extra_features_table) ? raw.extra_features_table : null;

  const assessmentInfo = isRecordArray(raw.assessment_information) ? raw.assessment_information : [];
  const benefitsInfo = isRecordArray(raw.benefits_information) ? raw.benefits_information : [];
  const taxableInfo = isRecordArray(raw.taxable_value_information) ? raw.taxable_value_information : [];
  const extraFeatures = isRecordArray(raw.extra_features) ? raw.extra_features : [];
  const landInfo =
    raw.land_information && typeof raw.land_information === "object" && !Array.isArray(raw.land_information)
      ? (raw.land_information as Record<string, unknown>)
      : {};
  const buildingInfo =
    raw.building_information && typeof raw.building_information === "object" && !Array.isArray(raw.building_information)
      ? (raw.building_information as Record<string, unknown>)
      : {};
  const additionalInfo =
    raw.additional_information && typeof raw.additional_information === "object" && !Array.isArray(raw.additional_information)
      ? (raw.additional_information as Record<string, unknown>)
      : null;

  const ownerRows = Array.isArray(raw.owner_rows) ? raw.owner_rows : [];

  const detailFields = Object.entries(raw).filter(
    ([key, value]) => !STRUCTURED_KEYS.has(key) && (typeof value !== "object" || value === null)
  );

  const sourceUrl = typeof raw.source_url === "string" ? raw.source_url : null;
  const address =
    String(property.property_address || raw["location address"] || raw.address || "—");
  const legalDesc = String(
    raw.full_legal_description ||
      property.legal_desc ||
      raw["legal information"] ||
      raw["legal description"] ||
      "—"
  );

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
          <dt className="text-slate-500">Full Legal Description</dt>
          <dd className="font-medium whitespace-pre-wrap">{legalDesc}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Assessed Value</dt>
          <dd className="font-medium">
            {property.assessed_value ? `$${property.assessed_value}` : "—"}
          </dd>
        </div>
      </dl>

      {parcelFields.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">All Assessor Fields</h4>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            {parcelFields.map(([key, value]) => (
              <div key={key} className="border border-slate-100 rounded-lg px-3 py-2">
                <dt className="text-slate-500 text-xs">{formatLabel(key)}</dt>
                <dd className="font-medium break-words">{formatScalar(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {detailFields.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Additional Fields</h4>
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

      {assessmentTable && <SectionTable table={assessmentTable} title="Assessment Information" />}
      {!assessmentTable && assessmentInfo.length > 0 && (
        <DataTable rows={assessmentInfo} title="Assessment Information" />
      )}

      {benefitsTable && <SectionTable table={benefitsTable} title="Benefits Information" />}
      {!benefitsTable && benefitsInfo.length > 0 && (
        <DataTable rows={benefitsInfo} title="Benefits Information" />
      )}

      {taxableTable && <SectionTable table={taxableTable} title="Taxable Value Information" />}
      {!taxableTable && taxableInfo.length > 0 && (
        <DataTable rows={taxableInfo} title="Taxable Value Information" />
      )}

      {assessmentHistory.length > 0 && <DataTable rows={assessmentHistory} title="Assessment History" />}

      {salesTable && <SectionTable table={salesTable} title="Sales Information" />}
      {!salesTable && salesHistory.length > 0 && (
        <DataTable rows={salesHistory} title="Sales Information" />
      )}

      {landTable && <SectionTable table={landTable} title="Land Information" />}
      {!landTable && Object.keys(landInfo).length > 0 && (
        <KeyValueBlock data={landInfo} title="Land Information" />
      )}

      {buildingTable && <SectionTable table={buildingTable} title="Building Information" />}
      {!buildingTable && Object.keys(buildingInfo).length > 0 && (
        <KeyValueBlock data={buildingInfo} title="Building Information" />
      )}

      {extraFeaturesTable && <SectionTable table={extraFeaturesTable} title="Extra Features" />}
      {!extraFeaturesTable && extraFeatures.length > 0 && (
        <DataTable rows={extraFeatures} title="Extra Features" />
      )}

      {additionalInfo && Boolean(additionalInfo.body_text) && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Additional Information</h4>
          <p className="text-sm whitespace-pre-wrap break-words">{String(additionalInfo.body_text).slice(0, 4000)}</p>
        </div>
      )}

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
