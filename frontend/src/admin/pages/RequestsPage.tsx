import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Search } from "lucide-react";
import { fetchRequests, RequestRun } from "../services/observabilityApi";
import { StatusBadge, ConfidenceBadge, LLMClassBadge } from "../components/StatusBadge";

function formatTs(ts: string) {
  return new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function statusFromRun(run: RequestRun): "success" | "warning" | "failed" {
  if (run.error_count > 0 || run.status_code >= 400) return "failed";
  return "success";
}

type RequestTypeFilter = "all" | "user" | "admin";
type StatusFilter = "all" | "success" | "failed";

function FilterBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
        active
          ? "bg-indigo-600 text-white border-indigo-600"
          : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"
      }`}
    >
      {children}
    </button>
  );
}

export function RequestsPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RequestRun[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [userFilter, setUserFilter] = useState("");
  const [requestTypeFilter, setRequestTypeFilter] = useState<RequestTypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [llmIssuesOnly, setLlmIssuesOnly] = useState(false);

  const PAGE_SIZE = 20;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRequests({
        page,
        page_size: PAGE_SIZE,
        user_id: userFilter || undefined,
        request_type: requestTypeFilter === "all" ? undefined : requestTypeFilter,
        errors_only: errorsOnly || undefined,
      });
      setRuns(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [page, userFilter, requestTypeFilter, errorsOnly]);

  // Client-side filters (status, LLM issues) applied after fetch
  const displayedRuns = useMemo(() => {
    return runs.filter(run => {
      if (statusFilter === "success" && statusFromRun(run) !== "success") return false;
      if (statusFilter === "failed" && statusFromRun(run) !== "failed") return false;
      if (llmIssuesOnly) {
        const cls = run.llm_behavior_classification;
        if (cls !== "deviated" && cls !== "added_unsupported_claims") return false;
      }
      return true;
    });
  }, [runs, statusFilter, llmIssuesOnly]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  function resetPage() { setPage(1); }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Request Explorer</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total.toLocaleString()} total requests</p>
        </div>
        <button onClick={load} disabled={loading} className="flex items-center gap-2 px-3 py-1.5 rounded border text-sm hover:bg-gray-50">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Filter Bar */}
      <div className="bg-white rounded-lg border p-4 mb-4 space-y-3">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-gray-400" />
            <input
              value={userFilter}
              onChange={e => { setUserFilter(e.target.value); resetPage(); }}
              placeholder="Filter by user..."
              className="pl-8 pr-3 py-1.5 rounded border text-sm w-52 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 font-medium mr-1">Type:</span>
            <FilterBtn active={requestTypeFilter === "all"} onClick={() => { setRequestTypeFilter("all"); resetPage(); }}>All</FilterBtn>
            <FilterBtn active={requestTypeFilter === "user"} onClick={() => { setRequestTypeFilter("user"); resetPage(); }}>User</FilterBtn>
            <FilterBtn active={requestTypeFilter === "admin"} onClick={() => { setRequestTypeFilter("admin"); resetPage(); }}>Admin</FilterBtn>
          </div>
        </div>

        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 font-medium mr-1">Status:</span>
            <FilterBtn active={statusFilter === "all"} onClick={() => setStatusFilter("all")}>All</FilterBtn>
            <FilterBtn active={statusFilter === "success"} onClick={() => setStatusFilter("success")}>Success</FilterBtn>
            <FilterBtn active={statusFilter === "failed"} onClick={() => setStatusFilter("failed")}>Failed</FilterBtn>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 font-medium mr-1">Special:</span>
            <FilterBtn active={errorsOnly} onClick={() => { setErrorsOnly(!errorsOnly); resetPage(); }}>Errors Only</FilterBtn>
            <FilterBtn active={llmIssuesOnly} onClick={() => setLlmIssuesOnly(!llmIssuesOnly)}>LLM Issues</FilterBtn>
          </div>
        </div>
      </div>

      {error && <div className="mb-4 p-3 rounded bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>}

      {/* Table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              {["Timestamp", "Type", "User", "Path", "Status", "Intent", "Confidence", "LLM", "Latency", "Errors"].map(h => (
                <th key={h} className="px-3 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {!loading && displayedRuns.length === 0 && (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">No requests found</td></tr>
            )}
            {displayedRuns.map(run => (
              <tr
                key={run.req_id}
                onClick={() => navigate(`/admin/request/${run.req_id}`)}
                className="hover:bg-indigo-50 cursor-pointer transition-colors"
              >
                <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap font-mono">{formatTs(run.timestamp)}</td>
                <td className="px-3 py-3">
                  <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${
                    run.request_type === "admin"
                      ? "bg-purple-100 text-purple-700"
                      : "bg-blue-100 text-blue-700"
                  }`}>{run.request_type ?? "user"}</span>
                </td>
                <td className="px-3 py-3 text-xs font-mono text-gray-700 max-w-[110px] truncate">{run.user_id || "—"}</td>
                <td className="px-3 py-3 text-xs font-mono text-gray-600 max-w-[160px] truncate">{run.path}</td>
                <td className="px-3 py-3"><StatusBadge status={statusFromRun(run)} /></td>
                <td className="px-3 py-3 text-xs text-gray-600 max-w-[110px] truncate">{run.intent || "—"}</td>
                <td className="px-3 py-3"><ConfidenceBadge level={run.intelligence_confidence} /></td>
                <td className="px-3 py-3"><LLMClassBadge cls={run.llm_behavior_classification} /></td>
                <td className="px-3 py-3 text-xs text-gray-600 whitespace-nowrap">
                  {run.total_latency_ms != null ? `${run.total_latency_ms.toFixed(0)}ms` : "—"}
                </td>
                <td className="px-3 py-3">
                  {run.error_count > 0
                    ? <span className="text-xs font-semibold text-red-600">{run.error_count}</span>
                    : <span className="text-xs text-gray-300">—</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="px-3 py-1.5 rounded border text-sm disabled:opacity-40 hover:bg-gray-50">Prev</button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="px-3 py-1.5 rounded border text-sm disabled:opacity-40 hover:bg-gray-50">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
