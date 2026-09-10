import { FormEvent, useEffect, useState } from "react";
import { CountyOption, getCountiesForState, QueryType } from "../api/client";
import { US_STATES } from "../data/states";

interface Props {
  onSearch: (state: string, county: string, queryType: QueryType, queryValue: string) => void;
  loading?: boolean;
}

export default function SearchForm({ onSearch, loading }: Props) {
  const [state, setState] = useState("AZ");
  const [county, setCounty] = useState("gila");
  const [counties, setCounties] = useState<CountyOption[]>([]);
  const [countiesLoading, setCountiesLoading] = useState(false);
  const [countiesError, setCountiesError] = useState<string | null>(null);
  const [queryType, setQueryType] = useState<QueryType>("owner");
  const [queryValue, setQueryValue] = useState("");

  useEffect(() => {
    let cancelled = false;
    setCountiesLoading(true);
    setCountiesError(null);

    getCountiesForState(state)
      .then((list) => {
        if (cancelled) return;
        setCounties(list);
        setCounty((prev) => {
          if (list.some((c) => c.slug === prev)) return prev;
          return list[0]?.slug ?? "";
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setCounties([]);
        setCountiesError(e instanceof Error ? e.message : "Failed to load counties");
      })
      .finally(() => {
        if (!cancelled) setCountiesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [state]);

  const stateName = US_STATES.find((s) => s.code === state)?.name ?? state;
  const countyName = counties.find((c) => c.slug === county)?.name ?? county;

  const parcelPlaceholder =
    state === "FL"
      ? county === "miami-dade"
        ? "e.g. 01-4138-019-0430 (folio)"
        : county === "orange"
          ? "e.g. 22-21-31-1234-00-010 (PIN)"
          : county === "columbia"
            ? "e.g. 12-34-56-12345-678 (parcel #)"
            : "e.g. parcel ID / folio / PIN"
      : state === "HI"
        ? "e.g. 390300650013 (TMK)"
        : "e.g. 123-45-678";

  const ownerPlaceholder =
    state === "FL" ? "e.g. Smith John" : "e.g. John Smith";

  const addressPlaceholder =
    state === "FL" && county === "columbia"
      ? "e.g. 542 N MARION AVE"
      : state === "HI"
        ? "e.g. 1299 Ala Moana Blvd"
        : "e.g. 123 Main St";

  const queryLabel =
    queryType === "owner"
      ? "Owner Name"
      : queryType === "address"
        ? "Street Address"
        : "Parcel Number";

  const queryPlaceholder =
    queryType === "owner"
      ? ownerPlaceholder
      : queryType === "address"
        ? addressPlaceholder
        : parcelPlaceholder;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (queryValue.trim() && county) {
      onSearch(state, county, queryType, queryValue.trim());
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-800">Property Search</h2>
        <p className="text-sm text-slate-500 mt-1">
          Select state & county — powered by{" "}
          <a
            href={`https://publicrecords.netronline.com/state/${state}/county/${county}`}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            NETR Online
          </a>
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">State</label>
        <select
          value={state}
          onChange={(e) => setState(e.target.value)}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {US_STATES.map((s) => (
            <option key={s.code} value={s.code}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">County</label>
        <select
          value={county}
          onChange={(e) => setCounty(e.target.value)}
          disabled={countiesLoading || counties.length === 0}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-400"
        >
          {countiesLoading && <option value="">Loading counties...</option>}
          {!countiesLoading && counties.length === 0 && <option value="">No counties available</option>}
          {counties.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
        {countiesError && <p className="text-xs text-red-600 mt-1">{countiesError}</p>}
      </div>

      <p className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
        Selected: <span className="font-medium text-slate-700">{countyName} County, {stateName}</span>
        {state === "FL" && (
          <span className="block mt-1 text-slate-400">
            Florida counties support parcel ID, owner name, or street address depending on the portal.
            Columbia and other floridapa.com counties accept address searches like 542 N MARION AVE.
          </span>
        )}
      </p>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">Search by</label>
        <div className="flex gap-4">
          {(["owner", "parcel", "address"] as QueryType[]).map((t) => (
            <label key={t} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="queryType"
                checked={queryType === t}
                onChange={() => setQueryType(t)}
                className="text-blue-600"
              />
              <span className="text-sm capitalize">
                {t === "parcel" ? "parcel number" : t === "address" ? "address" : "owner name"}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          {queryLabel}
        </label>
        <input
          value={queryValue}
          onChange={(e) => setQueryValue(e.target.value)}
          placeholder={queryPlaceholder}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>

      <button
        type="submit"
        disabled={loading || countiesLoading || !county}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium py-2.5 rounded-lg transition-colors"
      >
        {loading ? "Starting research..." : "Start Research"}
      </button>
    </form>
  );
}
