import type { LatencyBreakdown } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  breakdown: LatencyBreakdown;
}

const segments: { key: keyof LatencyBreakdown; label: string; color: string; description: string }[] = [
  { key: "planning", label: "Plan", color: "bg-muted-foreground/40", description: "Query planning & intent detection" },
  { key: "embedding", label: "Embed", color: "bg-blue-400/60", description: "Text embedding & vectorization" },
  { key: "retrieval", label: "Retrieval", color: "bg-primary/60", description: "Document search & context retrieval" },
  { key: "sql", label: "SQL", color: "bg-primary/40", description: "Structured SQL execution" },
  { key: "generation", label: "LLM", color: "bg-primary", description: "AI synthesis & generation" },
];

export function LatencyBar({ breakdown }: Props) {
  if (!breakdown || Object.keys(breakdown).length === 0) return null;
  const total = (breakdown.total as number) || Object.values(breakdown).reduce((a, b) => (typeof b === 'number' ? a + b : a), 0);
  const isFastTrack = breakdown.planning < 0.01;

  return (
    <div className="mt-3 pt-3 border-t border-border">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="label-mono">Latency</span>
          {isFastTrack && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider bg-primary/15 text-primary border border-primary/20">
              Fast Track Cache Hit
            </span>
          )}
        </div>
        <span className="font-mono text-xs text-muted-foreground">{total.toFixed(2)}s</span>
      </div>
      <div className="h-1 w-full flex rounded-full overflow-hidden bg-muted/30">
        {segments.map(({ key, color }) => {
          const pct = (breakdown[key] / total) * 100;
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <div className={`latency-segment ${color}`} style={{ width: `${pct}%` }} />
              </TooltipTrigger>
              <TooltipContent>
                {segments.find(s => s.key === key)?.description}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
      <div className="flex gap-3 mt-1.5 flex-wrap">
        {segments.map(({ key, label, color, description }) => (
          <Tooltip key={key}>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1 cursor-default">
                <div className={`h-1.5 w-1.5 rounded-full ${color}`} />
                <span className="label-mono">{label} {breakdown[key].toFixed(2)}s</span>
              </div>
            </TooltipTrigger>
            <TooltipContent>{description}</TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}
