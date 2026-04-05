import { useState } from "react";
import type { LatencyBreakdown } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChevronDown, ChevronUp, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

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
  const [showDetails, setShowDetails] = useState(false);
  if (!breakdown) return null;

  // If total is missing, we are still streaming/measuring
  const isMeasuring = !breakdown.total || breakdown.total === 0;
  const total = (breakdown.total as number) || 0;
  const isFastTrack = (breakdown.planning || 0) < 0.01 && !isMeasuring;

  return (
    <div className="mt-3 pt-3 border-t border-border/50">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="label-mono flex items-center gap-1.5">
            <Zap className={`h-3 w-3 ${isMeasuring ? 'text-muted-foreground animate-pulse' : 'text-primary'}`} />
            {isMeasuring ? "Measuring Performance..." : "Engine Latency"}
          </span>
          {isFastTrack && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-mono uppercase tracking-wider bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
              Instant Cache
            </span>
          )}
        </div>
        {!isMeasuring && (
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted-foreground">{total.toFixed(2)}s</span>
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
            >
              {showDetails ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
          </div>
        )}
      </div>

      {!isMeasuring && (
        <>
          <div className="h-1 w-full flex rounded-full overflow-hidden bg-muted/30">
            {segments.map(({ key, color }) => {
              const val = breakdown[key] || 0;
              const pct = total > 0 ? (val / total) * 100 : 0;
              if (pct === 0) return null;

              return (
                <Tooltip key={key}>
                  <TooltipTrigger asChild>
                    <div className={`latency-segment ${color}`} style={{ width: `${pct}%` }} />
                  </TooltipTrigger>
                  <TooltipContent className="text-[10px] font-mono">
                    {segments.find(s => s.key === key)?.label}: {val.toFixed(2)}s
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </div>

          <AnimatePresence>
            {showDetails && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 mt-3 p-2 rounded-lg bg-muted/20 border border-border/30">
                  {segments.map(({ key, label, color, description }) => {
                    const val = breakdown[key] || 0;
                    return (
                      <div key={key} className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1.5">
                          <div className={`h-1.5 w-1.5 rounded-full ${color}`} />
                          <span className="label-mono text-[8px]">{label}</span>
                        </div>
                        <span className="font-mono text-[10px] ml-3">{val.toFixed(3)}s</span>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      {isMeasuring && (
        <div className="latency-loading" />
      )}
    </div>
  );
}
