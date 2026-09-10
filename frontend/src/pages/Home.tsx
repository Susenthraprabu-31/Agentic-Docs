import { useNavigate } from "react-router-dom";
import SearchForm from "../components/SearchForm";
import { useSearch } from "../hooks/useSearch";
import { QueryType } from "../api/client";

export default function Home() {
  const navigate = useNavigate();
  const { search, loading, error } = useSearch();

  async function handleSearch(state: string, county: string, queryType: QueryType, queryValue: string) {
    const runId = await search(state, county, queryType, queryValue);
    if (runId) navigate(`/runs/${runId}`);
  }

  return (
    <div className="max-w-lg mx-auto">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Docs</h1>
        <p className="text-slate-500 mt-2">Agentic public records research — we show our work</p>
      </div>
      <SearchForm onSearch={handleSearch} loading={loading} />
      {error && <p className="mt-4 text-sm text-red-600 text-center">{error}</p>}
    </div>
  );
}
