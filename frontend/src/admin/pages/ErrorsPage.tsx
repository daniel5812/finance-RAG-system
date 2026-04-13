import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { fetchErrors, ObservabilityError } from "../services/observabilityApi";
import { CategoryBadge } from "../components/StatusBadge";

const CATEGORIES = ["ALL", "INFRA", "PIPELINE", "DATA", "BUSINESS", "SECURITY"];

function formatTs(ts: string) {
  return new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ErrorsPage() {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ObservabilityError[]>([]);
  const [category, setCategory] = useState("ALL");
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setFetchError(null);
    try {
      const data = await fetchErrors({ category: category !== "ALL" ? category : undefined, limit: 100 });
      setErrors(data);
    } catch (e) {
      setFetchError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [category]);

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Error Center</h1>
          <p className="text-sm text-gray-500 mt-0.5">{errors.length} errors shown</p>
        </div>
        <button onClick={load} disabled={loading} className="flex items-center gap-2 px-3 py-1.5 rounded border text-sm hover:bg-gray-50">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Category Filter */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              category === cat
                ? "bg-indigo-600 text-white border-indigo-600"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {fetchError && <div className="mb-4 p-3 rounded bg-red-50 border border-red-200 text-red-700 text-sm">{fetchError}</div>}

      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              {["Timestamp", "Category", "Stage", "Code", "Message", "Request"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>}
            {!loading && errors.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center">
                  <div className="flex flex-col items-center gap-2 text-green-600">
                    <AlertTriangle className="w-6 h-6 text-green-400" />
                    <span className="font-medium">No errors found</span>
                  </div>
                </td>
              </tr>
            )}
            {errors.map(err => (
              <tr key={err.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-xs font-mono text-gray-500 whitespace-nowrap">{formatTs(err.timestamp)}</td>
                <td className="px-4 py-3"><CategoryBadge category={err.error_category} /></td>
                <td className="px-4 py-3 text-xs font-mono text-gray-600">{err.stage}</td>
                <td className="px-4 py-3 text-xs font-mono text-red-700">{err.error_code}</td>
                <td className="px-4 py-3 text-xs text-gray-700 max-w-[300px] truncate">{err.message}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/admin/request/${err.req_id}`)}
                    className="text-xs text-indigo-600 hover:underline font-mono truncate max-w-[80px] block"
                  >
                    {err.req_id.slice(0, 8)}…
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
