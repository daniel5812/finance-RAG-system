import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { fetchObsMetrics, MetricsSummary } from "../services/observabilityApi";

const PIE_COLORS = ["#22c55e", "#ef4444", "#f59e0b"];

export function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchObsMetrics()
      .then(setMetrics)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-gray-400">Loading metrics...</div>;
  if (error) return <div className="p-8 text-red-500">{error}</div>;
  if (!metrics) return null;

  const llm = metrics.llm_behavior;
  const llmPieData = [
    { name: "Followed System", value: llm.followed_system },
    { name: "Deviated", value: llm.deviated },
    { name: "Unsupported Claims", value: llm.added_unsupported_claims },
  ].filter(d => d.value > 0);

  const errCatData = Object.entries(metrics.errors_by_category ?? {}).map(([cat, count]) => ({ cat, count }));

  const latencyData = [
    { name: "Avg", value: metrics.avg_latency_ms ?? 0 },
    { name: "P95", value: metrics.p95_latency_ms ?? 0 },
  ];

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Metrics Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">Aggregated over last 1 hour</p>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Latency */}
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Latency (ms)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={latencyData}>
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* LLM Behavior Pie */}
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">LLM Behavior</h2>
          {llmPieData.length === 0 ? (
            <div className="text-sm text-gray-400">No LLM data yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={llmPieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label={({ name, percent }) => `${(percent * 100).toFixed(0)}%`}>
                  {llmPieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Legend iconSize={10} wrapperStyle={{ fontSize: "11px" }} />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Reasoning Quality Bar Chart */}
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Reasoning Quality</h2>
          {Object.values(metrics.reasoning_quality).every(v => v === 0) ? (
            <div className="text-sm text-gray-400">No reasoning data yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={[
                { name: "High", value: metrics.reasoning_quality.high_quality },
                { name: "Surface", value: metrics.reasoning_quality.surface_level },
                { name: "Incomplete", value: metrics.reasoning_quality.incomplete },
              ]}>
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Errors by Category */}
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Errors by Category</h2>
          {errCatData.length === 0 ? (
            <div className="text-sm text-green-600 font-medium">No errors in this period</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={errCatData} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="cat" tick={{ fontSize: 11 }} width={80} />
                <Tooltip />
                <Bar dataKey="count" fill="#ef4444" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Cache + Requests Summary */}
        <div className="bg-white rounded-lg border p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Request Summary</h2>
          <div className="space-y-3">
            {[
              { label: "Total Requests", value: metrics.total_requests },
              { label: "Cache Hits", value: metrics.cache_hits },
              { label: "Cache Hit Rate", value: `${(metrics.cache_hit_rate * 100).toFixed(1)}%` },
              { label: "Total Errors", value: metrics.error_count },
              { label: "Error Rate", value: `${(metrics.error_rate * 100).toFixed(2)}%` },
              { label: "Validation Downgrades", value: metrics.validation_downgrades ?? 0 },
            ].map(({ label, value }) => (
              <div key={label} className="flex justify-between text-sm border-b border-gray-50 pb-2">
                <span className="text-gray-500">{label}</span>
                <span className="font-semibold text-gray-800">{value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
