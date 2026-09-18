interface Props {
  gisScreenshotUrl?: string | null;
  gisScreenshotDataUri?: string | null;
  documents?: Record<string, unknown>[];
  queryValue?: string;
}

function resolveGisImageSrc({
  gisScreenshotUrl,
  gisScreenshotDataUri,
  documents,
}: Props): string | null {
  if (gisScreenshotDataUri) return gisScreenshotDataUri;
  if (gisScreenshotUrl) return gisScreenshotUrl;

  const gisDoc = (documents || []).find(
    (doc) =>
      doc.document_type === "gis_map" ||
      (doc.ocr_json as Record<string, unknown> | undefined)?.source === "gis"
  );
  if (!gisDoc) return null;

  const ocr = (gisDoc.ocr_json as Record<string, unknown>) || {};
  const path = String(gisDoc.screenshot_path || ocr.image_path || "");
  if (!path) return null;

  const fileName = path.split(/[/\\]/).pop();
  return fileName ? `/screenshots/${fileName}` : null;
}

export default function GisMapPreview(props: Props) {
  const imageSrc = resolveGisImageSrc(props);
  if (!imageSrc) return null;

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 space-y-3">
      <div>
        <h3 className="text-base font-semibold text-slate-800 dark:text-zinc-100">GIS Parcel Map</h3>
        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
          Aerial map capture from the county GIS / property search portal
          {props.queryValue ? ` for ${props.queryValue}` : ""}.
        </p>
      </div>
      <div className="rounded-lg overflow-hidden border border-slate-200 dark:border-white/[0.08] bg-slate-950">
        <img
          src={imageSrc}
          alt="GIS parcel map"
          className="w-full h-auto max-h-[520px] object-contain mx-auto"
        />
      </div>
    </div>
  );
}
