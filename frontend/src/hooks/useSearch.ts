import { useState } from "react";
import { createSearch, QueryType } from "../api/client";

export function useSearch() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(state: string, county: string, queryType: QueryType, queryValue: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await createSearch({
        state: state.toUpperCase(),
        county: county.toLowerCase(),
        query_type: queryType,
        query_value: queryValue,
      });
      return result.run_id;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
      return null;
    } finally {
      setLoading(false);
    }
  }

  return { search, loading, error };
}
