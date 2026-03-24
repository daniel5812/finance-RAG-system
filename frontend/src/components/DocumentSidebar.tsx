import { useCallback, useRef, useState } from "react";
import { FileText, Upload, CheckCircle2, Loader2, AlertCircle, Trash2, Layers, ChevronLeft, ChevronRight, Cpu, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { UploadedDocument } from "@/lib/api";
import { uploadDocument } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";

interface Props {
  documents: UploadedDocument[];
  onDocumentUploaded: (doc: UploadedDocument) => void;
  onDocumentStatusChange: (id: string, status: UploadedDocument["status"]) => void;
  onDocumentDelete: (id: string) => void;
  onViewChunks?: (doc: UploadedDocument) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  isInsideSidebar?: boolean;
  selectedIds?: string[];
  onToggleSelection?: (id: string) => void;
}

const statusConfig: Record<UploadedDocument["status"], { icon: typeof Loader2; label: string; colorClass: string }> = {
  uploading: { icon: Loader2, label: "Uploading", colorClass: "text-primary" },
  extracting: { icon: Cpu, label: "Extracting", colorClass: "text-primary" },
  embedding: { icon: Sparkles, label: "Embedding", colorClass: "text-primary" },
  indexed: { icon: CheckCircle2, label: "Indexed", colorClass: "text-primary" },
  error: { icon: AlertCircle, label: "Failed", colorClass: "text-destructive" },
};

export function DocumentSidebar({
  documents,
  onDocumentUploaded,
  onDocumentStatusChange,
  onDocumentDelete,
  onViewChunks,
  collapsed,
  onToggleCollapse,
  isInsideSidebar,
  selectedIds = [],
  onToggleSelection,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const simulateIndexing = useCallback(async (id: string) => {
    const stages: UploadedDocument["status"][] = ["extracting", "embedding", "indexed"];
    for (const stage of stages) {
      await new Promise((r) => setTimeout(r, 800 + Math.random() * 600));
      onDocumentStatusChange(id, stage);
    }
  }, [onDocumentStatusChange]);

  const handleFiles = useCallback(async (files: FileList) => {
    for (const file of Array.from(files)) {
      const isAllowed = file.name.endsWith(".pdf") || file.name.endsWith(".txt");
      if (!isAllowed) continue;
      const id = crypto.randomUUID();
      const doc: UploadedDocument = { id, name: file.name, uploadedAt: new Date(), status: "uploading" };
      onDocumentUploaded(doc);
      try {
        await uploadDocument(file);
        simulateIndexing(id);
      } catch {
        onDocumentStatusChange(id, "error");
      }
    }
  }, [onDocumentUploaded, onDocumentStatusChange, simulateIndexing]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const content = (
    <div className="flex-1 scroll-stable p-3 space-y-2">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border border-dashed rounded p-6 flex flex-col items-center gap-2 cursor-pointer transition-colors duration-100 ${isDragging ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground"
          }`}
      >
        <Upload className="h-5 w-5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground text-center">Drop PDF/TXT or click to upload</span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt"
          multiple
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </div>

      <AnimatePresence>
        {documents.map((doc) => {
          const cfg = statusConfig[doc.status] || statusConfig.error;
          const StatusIcon = cfg.icon;
          const isAnimating = ["uploading", "extracting", "embedding"].includes(doc.status);

          return (
            <motion.div
              key={doc.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="surface-card p-3 border border-border/50 rounded-lg bg-background/50"
            >
              <div className="flex items-start gap-4">
                {onToggleSelection && (
                  <div className="mt-1">
                    <Checkbox
                      checked={selectedIds.includes(doc.id)}
                      onCheckedChange={() => onToggleSelection(doc.id)}
                      disabled={doc.status !== "indexed"}
                      className="h-4 w-4 rounded-sm border-muted-foreground/30 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                    />
                  </div>
                )}
                <FileText className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm truncate text-foreground font-medium">{doc.name}</p>
                    {doc.summary && (
                      <Popover>
                        <PopoverTrigger asChild>
                          <button className="p-1 rounded-full hover:bg-primary/10 text-primary transition-all active:scale-90">
                            <Sparkles className="h-3.5 w-3.5" />
                          </button>
                        </PopoverTrigger>
                        <PopoverContent className="w-80 shadow-2xl border-primary/20 bg-card/95 backdrop-blur-md p-4" side="right" align="start">
                          <div className="space-y-3">
                            <h4 className="text-xs font-mono uppercase tracking-widest text-primary flex items-center gap-2">
                              <Sparkles className="h-3 w-3" />
                              Source Overview
                            </h4>
                            <p className="text-sm leading-relaxed text-foreground/90 bg-muted/30 p-2 rounded-md border border-border/50 italic">
                              "{doc.summary}"
                            </p>
                            {doc.key_topics && doc.key_topics.length > 0 && (
                              <div className="space-y-2">
                                <p className="text-[10px] font-mono text-muted-foreground tracking-wide uppercase">Key Topics</p>
                                <div className="flex flex-wrap gap-1.5">
                                  {doc.key_topics.map((topic, idx) => (
                                    <Badge key={idx} variant="secondary" className="text-[10px] font-medium bg-primary/10 text-primary border-none hover:bg-primary/20">
                                      {topic}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            )}
                            {doc.suggested_questions && doc.suggested_questions.length > 0 && (
                              <div className="space-y-2 pt-2 border-t border-border/50">
                                <p className="text-[10px] font-mono text-muted-foreground tracking-wide uppercase">Suggested Questions</p>
                                <ul className="space-y-1.5">
                                  {doc.suggested_questions.map((q, idx) => (
                                    <li key={idx} className="text-[11px] text-muted-foreground hover:text-foreground cursor-pointer transition-colors bg-muted/20 p-1.5 rounded border border-border/30 hover:border-primary/30">
                                      {q}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                        </PopoverContent>
                      </Popover>
                    )}
                  </div>
                  <p className="text-[10px] font-mono text-muted-foreground/60 mt-0.5">
                    {doc.uploadedAt.toLocaleDateString()}
                  </p>
                  <div className="flex items-center gap-1.5 mt-1">
                    <StatusIcon className={`h-3 w-3 ${cfg.colorClass} ${isAnimating ? "animate-spin" : ""}`} />
                    <span className={`text-[10px] font-mono font-medium uppercase tracking-tighter ${cfg.colorClass}`}>{cfg.label}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1 mt-2 pt-2 border-t border-border/50">
                {doc.status === "indexed" && onViewChunks && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        onClick={() => onViewChunks(doc)}
                        className="p-1 rounded hover:bg-muted transition-colors"
                      >
                        <Layers className="h-3.5 w-3.5 text-muted-foreground" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>View chunks</TooltipContent>
                  </Tooltip>
                )}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={() => onDocumentDelete(doc.id)}
                      className="p-1 rounded hover:bg-destructive/10 transition-colors ml-auto"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive/70" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Delete document</TooltipContent>
                </Tooltip>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );

  if (isInsideSidebar) return content;

  if (collapsed) {
    return (
      <aside className="w-12 flex-shrink-0 border-r border-border flex flex-col bg-background items-center py-3 gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <button onClick={onToggleCollapse} className="p-2 rounded hover:bg-muted transition-colors">
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Expand Documents</TooltipContent>
        </Tooltip>
        {documents.map((doc) => {
          const cfg = statusConfig[doc.status] || statusConfig.error;
          return (
            <Tooltip key={doc.id}>
              <TooltipTrigger asChild>
                <div className="p-1.5 rounded hover:bg-muted transition-colors cursor-default">
                  <FileText className={`h-4 w-4 ${cfg.colorClass}`} />
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">{doc.name} — {cfg.label}</TooltipContent>
            </Tooltip>
          );
        })}
      </aside>
    );
  }

  return (
    <aside className="w-[280px] flex-shrink-0 border-r border-border flex flex-col bg-background">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">Documents</span>
        <button onClick={onToggleCollapse} className="p-1 rounded hover:bg-muted transition-colors">
          <ChevronLeft className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </div>
      {content}
    </aside>
  );
}
