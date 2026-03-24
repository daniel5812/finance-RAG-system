import { useState } from "react";
import { ChevronDown, ChevronRight, Database, FileSearch, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { QueryExecution } from "@/lib/api";

interface Props {
  execution: QueryExecution;
}

export function QueryExecutionPanel({ execution }: Props) {
  const [open, setOpen] = useState(false);

  const lines: { icon: typeof Database; label: string; value: string }[] = [];

  if (execution.entity) {
    lines.push({ icon: Zap, label: "Entity detected", value: execution.entity });
  }
  if (execution.query_type) {
    const typeMap = { sql: "Structured Data (SQL)", vector: "Document Search (Vector)", hybrid: "Hybrid (SQL + Documents)" };
    lines.push({ icon: Database, label: "Query type", value: typeMap[execution.query_type] });
  }
  if (execution.tables_accessed?.length) {
    lines.push({ icon: Database, label: "Tables accessed", value: execution.tables_accessed.join(", ") });
  }
  if (execution.documents_used?.length) {
    lines.push({ icon: FileSearch, label: "Documents used", value: execution.documents_used.join(", ") });
  }
  lines.push({ icon: Zap, label: "Cache", value: execution.cache_hit ? "Hit" : "Miss" });

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 label-mono hover:text-foreground transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Query Execution
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="mt-2 surface-card p-3 space-y-1.5">
              {lines.map((line, i) => (
                <div key={i} className="flex items-start gap-2">
                  <line.icon className="h-3 w-3 text-primary mt-0.5 flex-shrink-0" />
                  <span className="text-xs text-muted-foreground">{line.label}:</span>
                  <span className="text-xs text-foreground font-mono">{line.value}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
