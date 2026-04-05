import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription
} from "@/components/ui/dialog";
import { useEffect, useState } from "react";
import { fetchMetrics } from "@/lib/api";
import {
    BarChart3,
    Activity,
    Zap,
    ShieldCheck,
    Clock,
    RefreshCw,
    Search
} from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface MetricsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export function MetricsModal({ isOpen, onClose }: MetricsModalProps) {
    const [metrics, setMetrics] = useState<any>(null);
    const [loading, setLoading] = useState(false);

    const loadMetrics = async () => {
        setLoading(true);
        try {
            const data = await fetchMetrics();
            setMetrics(data);
        } catch (err) {
            console.error("Failed to load metrics:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (isOpen) {
            loadMetrics();
            const interval = setInterval(loadMetrics, 10000); // refresh every 10s
            return () => clearInterval(interval);
        }
    }, [isOpen]);

    if (!metrics) return null;

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="max-w-2xl bg-background/95 backdrop-blur-md border-border">
                <DialogHeader>
                    <div className="flex items-center gap-2 mb-1">
                        <Activity className="h-5 w-5 text-primary" />
                        <DialogTitle>System Intelligence Monitor</DialogTitle>
                    </div>
                    <DialogDescription className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                        Live infrastructure metrics and performance indicators
                    </DialogDescription>
                </DialogHeader>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
                    <MetricCard
                        title="Total Queries"
                        value={metrics.total_queries}
                        icon={<Search className="h-4 w-4" />}
                    />
                    <MetricCard
                        title="Cache Hit Rate"
                        value={`${(metrics.cache_hit_rate * 100).toFixed(1)}%`}
                        icon={<Zap className="h-4 w-4 text-amber-500" />}
                    />
                    <MetricCard
                        title="p95 Latency"
                        value={`${(metrics.latency.p95).toFixed(2)}s`}
                        icon={<Clock className="h-4 w-4 text-emerald-500" />}
                    />
                    <MetricCard
                        title="Active Streams"
                        value={metrics.active_streams_global}
                        icon={<Activity className="h-4 w-4 text-blue-500" />}
                    />
                </div>

                <div className="space-y-6 mt-8">
                    <div className="space-y-2">
                        <div className="flex items-center justify-between text-xs font-medium">
                            <span className="flex items-center gap-2">
                                <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                                Retrieval Confidence (Similarity)
                            </span>
                            <span className={metrics.drift_alert ? "text-destructive" : "text-emerald-500"}>
                                Avg: {(metrics.similarity.avg * 100).toFixed(1)}%
                            </span>
                        </div>
                        <Progress value={metrics.similarity.avg * 100} className="h-1.5" />
                        <p className="text-[10px] text-muted-foreground italic">
                            {metrics.drift_alert
                                ? "⚠️ Warning: Semantic drift detected in recent queries."
                                : "System is operating within optimal semantic boundaries."}
                        </p>
                    </div>

                    <div className="grid grid-cols-2 gap-8 pt-4 border-t border-border/50">
                        <div>
                            <h4 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2">
                                <BarChart3 className="h-3 w-3" />
                                Request Volume
                            </h4>
                            <div className="space-y-2">
                                <div className="flex justify-between text-xs">
                                    <span className="text-muted-foreground">Cache Hits</span>
                                    <span className="font-medium">{metrics.cache_hits}</span>
                                </div>
                                <div className="flex justify-between text-xs">
                                    <span className="text-muted-foreground">Cache Misses</span>
                                    <span className="font-medium">{metrics.cache_misses}</span>
                                </div>
                            </div>
                        </div>
                        <div>
                            <h4 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2">
                                <Clock className="h-3 w-3" />
                                Uptime
                            </h4>
                            <div className="flex items-baseline gap-1">
                                <span className="text-2xl font-bold">{(metrics.uptime_seconds / 3600).toFixed(1)}</span>
                                <span className="text-xs text-muted-foreground lowercase">hours</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="mt-4 flex justify-end">
                    <button
                        onClick={loadMetrics}
                        disabled={loading}
                        className="text-[10px] font-mono uppercase tracking-tight flex items-center gap-2 text-muted-foreground hover:text-primary transition-colors disabled:opacity-50"
                    >
                        <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
                        {loading ? "Refreshing..." : "Refresh Stats"}
                    </button>
                </div>
            </DialogContent>
        </Dialog>
    );
}

function MetricCard({ title, value, icon }: { title: string, value: any, icon: React.ReactNode }) {
    return (
        <div className="bg-muted/30 p-3 rounded-xl border border-border/50">
            <div className="flex items-center gap-2 text-muted-foreground mb-2">
                {icon}
                <span className="text-[10px] font-mono uppercase tracking-tighter truncate">{title}</span>
            </div>
            <div className="text-xl font-bold tracking-tight">{value}</div>
        </div>
    );
}

function cn(...classes: any[]) {
    return classes.filter(Boolean).join(" ");
}
