import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Clock, AlertTriangle, Info } from "lucide-react";
import { fetchRequestDetail, RequestDetail, TraceEvent } from "../services/observabilityApi";
import { TimelineItem } from "../components/TimelineItem";
import { LLMBehaviorPanel, LLMSkipReason } from "../components/LLMBehaviorPanel";
import { StatusBadge, ConfidenceBadge } from "../components/StatusBadge";

export function RequestDetailPage() {
  const { req_id } = useParams<{ req_id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!req_id) return;
    fetchRequestDetail(req_id)
      .then(setDetail)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [req_id]);

  if (loading) return <div className="p-8 text-gray-400">Loading trace...</div>;
  if (error) return <div className="p-8 text-red-500">{error}</div>;
  if (!detail) return <div className="p-8 text-gray-400">Not found</div>;

  // Extract metadata from timeline events
  const requestStartEvent = detail.timeline.find(e => e.event_name === "request_received");
  const responseEvent = detail.timeline.find(e => e.event_name === "request_complete");
  const intelligenceEvent = detail.timeline.find(e => e.event_name === "intelligence_layer_complete");
  const latencyMs = responseEvent?.latency_ms ?? null;
  const path = (requestStartEvent?.data?.path as string) ?? req_id ?? "—";
  const userId = (requestStartEvent?.data?.user_id as string) ?? "—";
  const confidence = (intelligenceEvent?.data?.confidence as string) ?? null;
  const cacheHit = detail.timeline.some(e => e.event_name === "cache_hit" || e.event_name === "semantic_cache_hit");
  const cacheType = detail.timeline.find(e => e.data?.cache_type)?.data?.cache_type as string | undefined;

  // Determine why LLM was skipped (for LLMBehaviorPanel)
  const llmSkipReason: LLMSkipReason = detail.llm_trace ? null
    : cacheHit ? "cache_hit"
    : detail.timeline.some(e => e.event_name.includes("validation") && e.status === "failed") ? "validation_failure"
    : detail.timeline.length > 0 ? "early_exit"
    : null;

  return (
    <div className="flex h-full min-h-screen">
      {/* Main */}
      <div className="flex-1 overflow-auto p-6">
        <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-5">
          <ArrowLeft className="w-4 h-4" /> Back to Requests
        </button>

        {/* Header card */}
        <div className="bg-white rounded-lg border p-5 mb-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="text-xs font-mono text-gray-400 mb-1">{req_id}</div>
              <div className="text-lg font-semibold text-gray-900 truncate">{path}</div>
              {userId !== "—" && (
                <div className="mt-1 text-sm text-gray-500">User: <span className="font-mono text-gray-700">{userId}</span></div>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              {confidence && <ConfidenceBadge level={confidence} />}
              <StatusBadge status={detail.error_count > 0 ? "failed" : "success"} size="md" />
            </div>
          </div>

          <div className="flex gap-6 mt-4 pt-4 border-t text-sm text-gray-500 flex-wrap">
            {latencyMs != null && (
              <div className="flex items-center gap-1.5">
                <Clock className="w-4 h-4" />
                <span className="font-medium text-gray-800">{latencyMs.toFixed(0)}ms</span> total
              </div>
            )}
            {cacheHit && (
              <div className="text-blue-600 font-medium">Cache hit {cacheType ? `(${cacheType})` : ""}</div>
            )}
            <div>{detail.stage_count} stages</div>
            {detail.error_count > 0 && (
              <div className="text-red-600 font-medium">{detail.error_count} error{detail.error_count > 1 ? "s" : ""}</div>
            )}
          </div>
        </div>

        {/* Failed stages highlight */}
        {detail.errors.length > 0 && (
          <div className="mb-5 p-4 bg-red-50 rounded-lg border border-red-200">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-red-600" />
              <span className="font-semibold text-red-700 text-sm">
                {detail.errors.length} Failed Stage{detail.errors.length > 1 ? "s" : ""}
              </span>
            </div>
            <div className="space-y-2">
              {detail.errors.map((err: TraceEvent, i) => (
                <div key={i} className="bg-white rounded border border-red-100 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">{err.stage}</span>
                    <span className="text-xs font-medium text-gray-700">{err.event_name}</span>
                  </div>
                  <div className="text-sm text-red-700">{err.summary}</div>
                  {err.data?.error_code && (
                    <div className="mt-1 text-xs font-mono text-red-500">{err.data.error_code as string}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Timeline */}
        <div>
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-4">
            Stage Timeline — {detail.timeline.length} events
          </h2>
          {detail.timeline.length === 0 ? (
            <div className="text-gray-400 text-sm p-4 bg-white rounded border">
              No timeline events (Redis TTL may have expired — LLM trace and run summary still available)
            </div>
          ) : (
            <div>
              {detail.timeline.map((event, i) => (
                <TimelineItem
                  key={`${event.stage}-${event.event_name}-${i}`}
                  event={event}
                  index={i}
                  isLast={i === detail.timeline.length - 1}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Sidebar */}
      <aside className="w-80 border-l bg-white overflow-auto p-5 flex-shrink-0">
        {/* Request Summary (Part 6) */}
        <RequestSummaryPanel detail={detail} cacheHit={cacheHit} cacheType={cacheType} path={path} />

        {/* Recommendation from LLM trace */}
        {detail.llm_trace && (
          <div className="mb-6">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Recommendation</h3>
            <div className="rounded border p-3 bg-gray-50 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">Action</span>
                <span className="text-sm font-semibold text-gray-800 font-mono">
                  {detail.llm_trace.output_structure?.recommendation_action || "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">Confidence</span>
                <ConfidenceBadge level={confidence} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">LLM Latency</span>
                <span className="text-xs font-mono text-gray-700">{detail.llm_trace.latency_ms?.toFixed(0)}ms</span>
              </div>
            </div>
          </div>
        )}

        {/* LLM Introspection */}
        <div>
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">LLM Introspection</h3>
          <LLMBehaviorPanel trace={detail.llm_trace} skipReason={llmSkipReason} />
        </div>
      </aside>
    </div>
  );
}

// ── Request Summary Panel ─────────────────────────────────────────────────────

interface SummaryPanelProps {
  detail: RequestDetail;
  cacheHit: boolean;
  cacheType?: string;
  path: string;
}

function RequestSummaryPanel({ detail, cacheHit, cacheType, path }: SummaryPanelProps) {
  const { summary, issues, llm_status } = useMemo(() => {
    const routerEvent = detail.timeline.find(e => e.event_name === "router_plan_built");
    const intelligenceEvent = detail.timeline.find(e => e.event_name === "intelligence_layer_complete");
    const intent = (routerEvent?.data?.intent as string) ?? (intelligenceEvent?.data?.intent as string) ?? null;
    const action = detail.llm_trace?.output_structure?.recommendation_action ?? null;
    const llm_status = detail.llm_trace?.behavior?.classification ?? null;
    const flags = detail.llm_trace?.behavior?.flags ?? [];

    const issues: string[] = [];
    if (detail.error_count > 0) issues.push(`${detail.error_count} stage error${detail.error_count > 1 ? "s" : ""}`);
    if (llm_status === "deviated") issues.push("llm_deviated");
    if (llm_status === "added_unsupported_claims") issues.push("unsupported_claims");
    if (flags.includes("hallucination_risk")) issues.push("hallucination_risk");
    if (flags.includes("confidence_mismatch")) issues.push("confidence_mismatch");
    if (cacheHit) issues.push(`cache_${cacheType ?? "hit"}`);

    let summary = "";
    if (cacheHit) {
      summary = `Cache hit (${cacheType ?? "exact"}) — pipeline skipped.`;
    } else if (intent && action) {
      summary = `Intent: ${intent}. Recommendation: ${action}.`;
    } else if (intent) {
      summary = `Intent: ${intent}.`;
    } else if (action) {
      summary = `Recommendation: ${action}.`;
    } else {
      summary = `${path} — ${detail.stage_count} stages completed.`;
    }

    return { summary, issues, llm_status };
  }, [detail, cacheHit, cacheType, path]);

  return (
    <div className="mb-6">
      <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Request Summary</h3>
      <div className="rounded border p-3 bg-gray-50 space-y-2">
        <div className="flex items-start gap-2">
          <Info className="w-3.5 h-3.5 text-gray-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-gray-700 leading-relaxed">{summary}</p>
        </div>
        {issues.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {issues.map(issue => (
              <span key={issue} className="text-xs font-mono px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200">
                {issue}
              </span>
            ))}
          </div>
        )}
        {llm_status && (
          <div className="text-xs text-gray-500 pt-0.5">
            LLM: <span className="font-mono text-gray-700">{llm_status}</span>
          </div>
        )}
      </div>
    </div>
  );
}
