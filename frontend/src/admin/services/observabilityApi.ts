import { authenticatedFetch, API_BASE } from "@/lib/api";

// ─── Data Models ───────────────────────────────────────────────────────────

export interface RequestRun {
  req_id: string;
  user_id: string;
  path: string;
  method: string;
  status_code: number;
  total_latency_ms: number;
  stage_count: number;
  error_count: number;
  cache_hit: boolean;
  cache_type: string | null;
  intent: string | null;
  intelligence_confidence: string | null;
  llm_behavior_classification: string | null;
  sources_retrieved: number;
  request_type: string;   // "user" | "admin"
  timestamp: string;
}

export interface TraceEvent {
  req_id: string;
  stage: string;
  event_name: string;
  status: "success" | "warning" | "failed" | "running";
  severity: "info" | "warning" | "error" | "debug";
  latency_ms: number | null;
  summary: string;
  data: Record<string, unknown>;
  debug: Record<string, unknown> | null;
  timestamp: number;
}

export interface LLMInputBlocks {
  has_normalized_portfolio: boolean;
  has_market_context: boolean;
  has_validation_block: boolean;
  has_vector_context: boolean;
  has_sql_context: boolean;
  has_portfolio_context: boolean;
  intelligence_block_chars: number;
  context_block_chars: number;
  estimated_prompt_tokens: number;
}

export interface LLMConstraints {
  forbidden_operations_applied: boolean;
  no_arithmetic_mode: boolean;
  cite_only_directive: boolean;
  intelligence_block_injected: boolean;
}

export interface LLMOutputStructure {
  has_explainability_block: boolean;
  has_suggested_questions: boolean;
  recommendation_action: string | null;
  confidence_source: string;
  confidence_level: string | null;
  response_length_chars: number;
  suggested_questions_count: number;
}

export interface LLMBehaviorAnalysis {
  classification: "followed_system" | "deviated" | "added_unsupported_claims";
  flags: string[];            // e.g. ["confidence_mismatch", "arithmetic_attempted"]
  validation_flags: string[];
  arithmetic_markers: string[];
  notes: string;
}

export interface LLMTrace {
  req_id: string;
  input_blocks: LLMInputBlocks;
  constraints: LLMConstraints;
  output_structure: LLMOutputStructure;
  behavior: LLMBehaviorAnalysis;
  latency_ms: number;
  timestamp: string;
}

export interface ObservabilityError {
  id: number;
  req_id: string;
  stage: string;
  error_category: "INFRA" | "PIPELINE" | "DATA" | "BUSINESS" | "SECURITY";
  error_code: string;
  message: string;
  traceback: string | null;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface RequestDetail {
  req_id: string;
  timeline: TraceEvent[];
  llm_trace: LLMTrace | null;
  errors: TraceEvent[];   // failed TraceEvents filtered from timeline
  stage_count: number;
  error_count: number;
}

export interface MetricsSummary {
  total_requests: number;
  cache_hits: number;
  cache_hit_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  error_count: number;
  error_rate: number;
  llm_behavior: {
    followed_system: number;
    deviated: number;
    added_unsupported_claims: number;
  };
  reasoning_quality: {
    high_quality: number;
    surface_level: number;
    incomplete: number;
  };
  errors_by_category: Record<string, number>;
  validation_downgrades: number;
}

export interface PaginatedRequests {
  items: RequestRun[];
  total: number;
  page: number;
  page_size: number;
}

// ─── API Functions ──────────────────────────────────────────────────────────

export async function fetchRequests(params?: {
  page?: number;
  page_size?: number;
  user_id?: string;
  cache_hit?: boolean;
  request_type?: string;  // "user" | "admin" | "all"
  errors_only?: boolean;
}): Promise<PaginatedRequests> {
  const page = params?.page ?? 1;
  const page_size = params?.page_size ?? 20;
  const offset = (page - 1) * page_size;
  const q = new URLSearchParams();
  q.set("limit", String(page_size));
  q.set("offset", String(offset));
  if (params?.user_id) q.set("user_id", params.user_id);
  if (params?.cache_hit !== undefined) q.set("cache_hit", String(params.cache_hit));
  if (params?.request_type) q.set("request_type", params.request_type);
  if (params?.errors_only) q.set("errors_only", "true");
  const res = await authenticatedFetch(`${API_BASE}/admin/observability/requests?${q}`);
  if (!res.ok) throw new Error("Failed to fetch requests");
  const items: RequestRun[] = await res.json();
  return { items, total: items.length < page_size ? offset + items.length : offset + items.length + 1, page, page_size };
}

export async function fetchRequestDetail(req_id: string): Promise<RequestDetail> {
  const res = await authenticatedFetch(`${API_BASE}/admin/observability/requests/${req_id}`);
  if (!res.ok) throw new Error("Failed to fetch request detail");
  return res.json();
}

export async function fetchErrors(params?: {
  category?: string;
  req_id?: string;
  limit?: number;
}): Promise<ObservabilityError[]> {
  const q = new URLSearchParams();
  if (params?.category) q.set("category", params.category);
  if (params?.req_id) q.set("req_id", params.req_id);
  if (params?.limit) q.set("limit", String(params.limit));
  const res = await authenticatedFetch(`${API_BASE}/admin/observability/errors?${q}`);
  if (!res.ok) throw new Error("Failed to fetch errors");
  return res.json();
}

// Backend returns nested shape; we flatten it here for page components.
interface _BackendMetrics {
  window?: string;
  requests?: { total_requests?: number; cache_hits?: number; avg_latency_ms?: number; p95_latency_ms?: number; requests_with_errors?: number };
  errors?: { total?: number; infra?: number; pipeline?: number; data?: number; business?: number; security?: number };
  llm?: {
    total?: number; followed?: number; deviated?: number; unsupported?: number;
    high_quality?: number; surface_level?: number; incomplete?: number;
  };
}

export async function fetchObsMetrics(): Promise<MetricsSummary> {
  const res = await authenticatedFetch(`${API_BASE}/admin/observability/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  const raw: _BackendMetrics = await res.json();
  const r = raw.requests ?? {};
  const e = raw.errors ?? {};
  const l = raw.llm ?? {};
  const total = r.total_requests ?? 0;
  const cacheHits = r.cache_hits ?? 0;
  const errCount = e.total ?? 0;
  return {
    total_requests: total,
    cache_hits: cacheHits,
    cache_hit_rate: total > 0 ? cacheHits / total : 0,
    avg_latency_ms: r.avg_latency_ms ?? 0,
    p95_latency_ms: r.p95_latency_ms ?? 0,
    error_count: errCount,
    error_rate: total > 0 ? errCount / total : 0,
    llm_behavior: {
      followed_system: l.followed ?? 0,
      deviated: l.deviated ?? 0,
      added_unsupported_claims: l.unsupported ?? 0,
    },
    reasoning_quality: {
      high_quality: l.high_quality ?? 0,
      surface_level: l.surface_level ?? 0,
      incomplete: l.incomplete ?? 0,
    },
    errors_by_category: {
      ...(e.infra ? { INFRA: e.infra } : {}),
      ...(e.pipeline ? { PIPELINE: e.pipeline } : {}),
      ...(e.data ? { DATA: e.data } : {}),
      ...(e.business ? { BUSINESS: e.business } : {}),
      ...(e.security ? { SECURITY: e.security } : {}),
    },
    validation_downgrades: 0,
  };
}

export interface ObservabilityStatus {
  redis: { connected: boolean; error: string | null };
  postgres: { connected: boolean; error: string | null };
}

export async function fetchObsStatus(): Promise<ObservabilityStatus> {
  const res = await authenticatedFetch(`${API_BASE}/admin/observability/status`);
  if (!res.ok) throw new Error("Failed to fetch observability status");
  return res.json();
}

export async function fetchAdminUsers(): Promise<unknown[]> {
  const res = await authenticatedFetch(`${API_BASE}/admin/users`);
  if (!res.ok) throw new Error("Failed to fetch users");
  return res.json();
}
