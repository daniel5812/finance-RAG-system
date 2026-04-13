import { useState, useEffect } from "react";
import { Activity, AlertCircle, Clock, TrendingUp, Zap, Brain } from "lucide-react";
import { fetchObsMetrics, fetchObsStatus, MetricsSummary, ObservabilityStatus } from "../services/observabilityApi";

function StatCard({ label, value, sub, icon: Icon, color = "text-gray-800" }: {
  label: string; value: string | number; sub?: string;
  icon: React.ElementType; color?: string;
}) {
  return (
    <div className="bg-white rounded-lg border p-5">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-gray-400" />
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function SystemStatusBanner({ status }: { status: ObservabilityStatus | null }) {
  if (!status) return null;

  const services = [
    { name: "Redis (Cache/Trace)", ...status.redis },
    { name: "Postgres (Durable)", ...status.postgres },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
      {services.map((s) => (
        <div key={s.name} className={cn(
          "flex items-center justify-between p-3 rounded-lg border text-sm",
          s.connected ? "bg-green-50 border-green-200 text-green-800" : "bg-red-50 border-red-200 text-red-800"
        )}>
          <div className="flex items-center gap-2">
            <div className={cn("w-2 h-2 rounded-full", s.connected ? "bg-green-500" : "bg-red-500 animate-pulse")} />
            <span className="font-medium">{s.name}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs opacity-80">{s.connected ? "Connected" : "Disconnected"}</span>
            {!s.connected && s.error && (
              <div className="group relative">
                <AlertCircle className="w-4 h-4 text-red-400 cursor-help" />
                <div className="absolute right-0 top-6 w-64 p-2 bg-gray-900 text-white text-[10px] rounded shadow-xl opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none font-mono">
                  {s.error}
                </div>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

import { cn } from "@/lib/utils";

export function OverviewPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [status, setStatus] = useState<ObservabilityStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchObsMetrics(), fetchObsStatus()])
      .then(([m, s]) => {
        setMetrics(m);
        setStatus(s);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-gray-400">Loading metrics...</div>;
  if (error) return <div className="p-8 text-red-500">{error}</div>;
  if (!metrics) return null;

  const llm = metrics.llm_behavior;
  const totalLLM = (llm.followed_system + llm.deviated + llm.added_unsupported_claims) || 1;
  const deviationRate = ((llm.deviated + llm.added_unsupported_claims) / totalLLM * 100).toFixed(1);

  return (
    <div className="p-6">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">System Overview</h1>
          <p className="text-sm text-gray-500 mt-0.5">Last 1 hour — live snapshot</p>
        </div>
        <div className="text-[10px] font-mono text-gray-400 bg-gray-50 px-2 py-1 rounded border">
          LOGGING: UNIFIED_STRUCTURED
        </div>
      </div>

      <SystemStatusBanner status={status} />

      {/* Stat Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <StatCard label="Total Requests" value={metrics.total_requests.toLocaleString()} icon={Activity} />
        <StatCard label="Error Rate" value={`${(metrics.error_rate * 100).toFixed(1)}%`}
          sub={`${metrics.error_count} errors`} icon={AlertCircle}
          color={metrics.error_rate > 0.05 ? "text-red-600" : "text-gray-800"} />
        <StatCard label="Avg Latency" value={`${metrics.avg_latency_ms?.toFixed(0) ?? "—"}ms`}
          sub={`p95: ${metrics.p95_latency_ms?.toFixed(0) ?? "—"}ms`} icon={Clock} />
        <StatCard label="Cache Hit Rate" value={`${(metrics.cache_hit_rate * 100).toFixed(1)}%`}
          sub={`${metrics.cache_hits} hits`} icon={Zap} color="text-blue-600" />
        <StatCard label="LLM Deviation Rate" value={`${deviationRate}%`}
          sub="deviated + unsupported" icon={Brain}
          color={parseFloat(deviationRate) > 10 ? "text-red-600" : "text-gray-800"} />
        <StatCard label="Validation Downgrades" value={metrics.validation_downgrades ?? 0}
          icon={TrendingUp} />
      </div>

      {/* LLM Behavior Breakdown */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">LLM Behavior Distribution</h2>
          <div className="space-y-3">
            {[
              { label: "Followed System", value: llm.followed_system, color: "bg-green-500" },
              { label: "Deviated", value: llm.deviated, color: "bg-red-500" },
              { label: "Unsupported Claims", value: llm.added_unsupported_claims, color: "bg-amber-500" },
            ].map(({ label, value, color }) => {
              const pct = ((value / totalLLM) * 100).toFixed(0);
              return (
                <div key={label}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-600">{label}</span>
                    <span className="font-mono text-gray-700">{value} ({pct}%)</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-gray-100">
                    <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Errors by Category</h2>
          {Object.keys(metrics.errors_by_category ?? {}).length === 0 ? (
            <div className="text-sm text-green-600 font-medium">No errors in last hour</div>
          ) : (
            <div className="space-y-2">
              {Object.entries(metrics.errors_by_category ?? {}).map(([cat, count]) => (
                <div key={cat} className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 font-mono">{cat}</span>
                  <span className="font-bold text-gray-800">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
