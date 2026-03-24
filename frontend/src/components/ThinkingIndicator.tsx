import { useEffect, useState } from "react";
import { motion } from "framer-motion";

const stages = [
  "Planning financial query...",
  "Searching structured data...",
  "Scanning uploaded documents...",
  "Generating answer...",
];

export function ThinkingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 50);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setStageIndex((prev) => (prev < stages.length - 1 ? prev + 1 : prev));
    }, 1200);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="py-4"
    >
      <span className="label-mono mb-2 block">AI</span>
      <div className="flex flex-col gap-1.5">
        {stages.slice(0, stageIndex + 1).map((stage, i) => (
          <motion.div
            key={stage}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: i === stageIndex ? 1 : 0.4, x: 0 }}
            className="flex items-center gap-2"
          >
            {i === stageIndex ? (
              <div className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            ) : (
              <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            )}
            <span className={`text-xs font-mono ${i === stageIndex ? "text-foreground" : "text-muted-foreground"}`}>
              {stage}
            </span>
          </motion.div>
        ))}
        <span className="font-mono text-[10px] text-muted-foreground tabular-nums mt-1">
          {elapsed.toFixed(1)}s
        </span>
      </div>
    </motion.div>
  );
}
