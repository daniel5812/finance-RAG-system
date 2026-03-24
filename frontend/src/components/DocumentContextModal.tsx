import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { Citation } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  citationKey: string;
  citation: Citation;
}

export function DocumentContextModal({ open, onOpenChange, citationKey, citation }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg bg-card border-border">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm flex items-center gap-2">
            <span className="text-primary">{citationKey}</span>
            <span className="label-mono">
              {citation.type === "sql" ? "SQL SOURCE" : "DOCUMENT SOURCE"}
            </span>
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            {citation.source}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-3">
          {citation.page_number && (
            <div className="flex items-center gap-2">
              <span className="label-mono">Page</span>
              <span className="text-sm font-mono text-foreground">{citation.page_number}</span>
            </div>
          )}
          <div className="surface-elevated p-4 rounded max-h-[300px] overflow-y-auto">
            <p className="text-sm leading-relaxed text-foreground whitespace-pre-wrap">
              {citation.chunk_text || "Chunk text not available from the backend. The source reference is: " + citation.source}
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
