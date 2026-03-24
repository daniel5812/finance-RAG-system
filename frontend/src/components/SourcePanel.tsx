import { useState } from "react";
import { Table2, FileText, X, Eye } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { Citation } from "@/lib/api";
import { DocumentContextModal } from "./DocumentContextModal";

interface Props {
  citations: Record<string, Citation>;
  focusedCitation: string | null;
  onClose: () => void;
}

export function SourcePanel({ citations, focusedCitation, onClose }: Props) {
  const entries = Object.entries(citations);
  const [contextModal, setContextModal] = useState<{ key: string; citation: Citation } | null>(null);

  if (entries.length === 0) return null;

  return (
    <>
      <aside className="w-[320px] flex-shrink-0 border-l border-border flex flex-col bg-background">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <span className="label-mono">Sources</span>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex-1 scroll-stable p-3 space-y-2">
          <AnimatePresence>
            {entries.map(([key, citation]) => (
              <motion.div
                key={key}
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2 }}
                className={`surface-card p-3 transition-colors duration-100 ${
                  focusedCitation === key ? "border-primary/50" : "hover:border-muted-foreground/30"
                }`}
              >
                <div className="flex items-start gap-2.5">
                  {citation.source_type === "sql" ? (
                    <Table2 className="h-4 w-4 text-primary mt-0.5 flex-shrink-0" />
                  ) : (
                    <FileText className="h-4 w-4 text-primary mt-0.5 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-primary">{key}</span>
                      <span className="label-mono">
                        {citation.source_type === "sql" ? "SQL" : "DOCUMENT"}
                      </span>
                    </div>
                    <p className="text-sm text-foreground mt-1 truncate">{citation.display_name}</p>
                  </div>
                </div>
                {citation.source_type === "document" && (
                  <button
                    onClick={() => setContextModal({ key, citation })}
                    className="flex items-center gap-1 mt-2 pt-2 border-t border-border label-mono hover:text-primary transition-colors"
                  >
                    <Eye className="h-3 w-3" />
                    View Context
                  </button>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </aside>

      {contextModal && (
        <DocumentContextModal
          open={!!contextModal}
          onOpenChange={(open) => !open && setContextModal(null)}
          citationKey={contextModal.key}
          citation={contextModal.citation}
        />
      )}
    </>
  );
}
