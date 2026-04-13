import { useState } from "react";
import { ChevronDown, ChevronRight, Clock } from "lucide-react";
import { TraceEvent } from "../services/observabilityApi";
import { StatusBadge } from "./StatusBadge";
import { JsonViewer } from "./JsonViewer";
import { cn } from "@/lib/utils";

const STAGE_COLORS: Record<string, string> = {
  request_start:    "bg-gray-400",
  cache:            "bg-blue-400",
  condense:         "bg-sky-400",
  router:           "bg-indigo-400",
  sql_retrieval:    "bg-cyan-400",
  vector_retrieval: "bg-teal-400",
  reranking:        "bg-emerald-400",
  normalization:    "bg-green-400",
  user_profiler:    "bg-lime-400",
  market_analyzer:  "bg-yellow-400",
  asset_profiler:   "bg-amber-400",
  portfolio_fit:    "bg-orange-400",
  scoring:          "bg-rose-400",
  recommendation:   "bg-pink-400",
  validation:       "bg-purple-400",
  intelligence:     "bg-violet-400",
  llm_prompt_build: "bg-orange-400",
  llm_execution:    "bg-red-500",
  response:         "bg-gray-400",
};

const STAGE_LABELS: Record<string, string> = {
  request_start:    "Request Start",
  cache:            "Cache",
  condense:         "Condense",
  router:           "Router",
  sql_retrieval:    "SQL Retrieval",
  vector_retrieval: "Vector Retrieval",
  reranking:        "Reranking",
  normalization:    "Normalization",
  user_profiler:    "User Profiler",
  market_analyzer:  "Market Analyzer",
  asset_profiler:   "Asset Profiler",
  portfolio_fit:    "Portfolio Fit",
  scoring:          "Scoring",
  recommendation:   "Recommendation",
  validation:       "Validation",
  llm_prompt_build: "Prompt Build",
  llm_execution:    "LLM Execution",
  response:         "Response",
};

// Fallback summaries when the pipeline didn't set one
const EVENT_SUMMARIES: Record<string, string> = {
  request_received:            "Request received",
  request_complete:            "Request completed",
  cache_miss:                  "Cache miss — full pipeline will run",
  cache_hit:                   "Cache hit — response served from cache",
  semantic_cache_hit:          "Semantic cache hit — similar query matched",
  router_plan_built:           "Router selected execution plan",
  retrieval_complete:          "Retrieved relevant context",
  intelligence_layer_complete: "Intelligence analysis complete",
  prompt_assembled:            "Prompt assembled for LLM",
  llm_call_done:               "LLM response received",
  response_finalized:          "Response finalized and sent",
};

interface TimelineItemProps {
  event: TraceEvent;
  index: number;
  isLast: boolean;
}

export function TimelineItem({ event, isLast }: TimelineItemProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = (event.data && Object.keys(event.data).length > 0) || event.debug;
  const dotColor = STAGE_COLORS[event.stage] ?? "bg-gray-300";

  const statusBg = {
    warning: "border-amber-200 bg-amber-50/40",
    failed:  "border-red-200 bg-red-50/40",
  }[event.status] ?? "";

  const displaySummary = event.summary || EVENT_SUMMARIES[event.event_name] || event.event_name.replace(/_/g, " ");
  const stageLabel = STAGE_LABELS[event.stage] ?? event.stage;

  return (
    <div className="flex gap-3">
      {/* Spine */}
      <div className="flex flex-col items-center">
        <div className={cn("w-2.5 h-2.5 rounded-full mt-1.5 flex-shrink-0 ring-2 ring-white shadow-sm", dotColor)} />
        {!isLast && <div className="w-0.5 bg-gray-200 flex-1 mt-1" />}
      </div>

      {/* Card */}
      <div className={cn("flex-1 mb-3 rounded-lg border p-3 bg-white", statusBg)}>
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            {/* Stage › event_name */}
            <div className="flex items-center gap-1.5 flex-wrap mb-1">
              <span className="text-xs text-gray-400 font-mono">{stageLabel}</span>
              <span className="text-xs text-gray-300">›</span>
              <span className="text-xs font-mono text-gray-500">{event.event_name}</span>
              <StatusBadge status={event.status} />
            </div>

            {/* Summary — the human-readable headline */}
            <p className="text-sm font-semibold text-gray-900 leading-snug">{displaySummary}</p>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
            {event.latency_ms != null && (
              <span className="flex items-center gap-1 text-xs text-gray-400">
                <Clock className="w-3 h-3" />
                {event.latency_ms.toFixed(0)}ms
              </span>
            )}
            {hasDetails && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title="Show raw data"
              >
                {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>
            )}
          </div>
        </div>

        {expanded && (
          <div className="mt-2 pt-2 border-t border-gray-100 space-y-2">
            <JsonViewer data={event.data} label="data" defaultOpen />
            {event.debug && <JsonViewer data={event.debug} label="debug" />}
          </div>
        )}
      </div>
    </div>
  );
}
