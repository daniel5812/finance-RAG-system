import { useEffect } from "react";
import { Lightbulb, RefreshCw, AlertCircle } from "lucide-react";
import { useInsights } from "@/lib/insights";
import { useNavigate } from "react-router-dom";

function formatDate(iso: string) {
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
}

function relevanceBadge(score: number) {
    if (score >= 0.75) return "bg-green-500/10 text-green-600 border-green-500/20";
    if (score >= 0.4) return "bg-amber-500/10 text-amber-600 border-amber-500/20";
    return "bg-muted text-muted-foreground border-border";
}

export default function Insights() {
    const { insights, loading, refresh, markSeen } = useInsights();
    const navigate = useNavigate();

    useEffect(() => {
        if (insights.length > 0) markSeen();
    }, [insights.length, markSeen]);

    return (
        <div className="flex-1 overflow-auto bg-background p-6">
            <div className="max-w-3xl mx-auto">
                {/* Header */}
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-xl bg-primary/10 text-primary">
                            <Lightbulb className="h-5 w-5" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-foreground">Proactive Insights</h1>
                            <p className="text-xs text-muted-foreground font-mono">
                                {insights.length} insight{insights.length !== 1 ? "s" : ""} · AI-generated from your portfolio &amp; macro data
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => navigate("/")}
                            className="px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-muted transition-colors"
                        >
                            ← Back
                        </button>
                        <button
                            onClick={refresh}
                            disabled={loading}
                            className="p-2 rounded-lg hover:bg-muted transition-colors text-muted-foreground"
                            title="Refresh insights"
                        >
                            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        </button>
                    </div>
                </div>

                {/* Content */}
                {loading && insights.length === 0 ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
                        Loading insights…
                    </div>
                ) : insights.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-3 text-muted-foreground">
                        <AlertCircle className="h-10 w-10 opacity-20" />
                        <p className="text-sm">No insights yet. Make sure your portfolio is populated.</p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {insights.map((insight) => (
                            <div
                                key={insight.id}
                                className="p-4 rounded-xl border border-border/60 bg-card/60 backdrop-blur-sm"
                            >
                                <p
                                    className="text-sm text-foreground leading-relaxed"
                                    dir="auto"
                                >
                                    {insight.insight_text}
                                </p>
                                <div className="mt-3 flex items-center gap-3">
                                    <span
                                        className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-mono ${relevanceBadge(insight.relevance_score)}`}
                                    >
                                        relevance {(insight.relevance_score * 100).toFixed(0)}%
                                    </span>
                                    <span className="text-[10px] text-muted-foreground font-mono">
                                        {formatDate(insight.timestamp)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
