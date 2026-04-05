import ReactMarkdown from "react-markdown";
import type { Citation } from "@/lib/api";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { FileText, Table2 } from "lucide-react";

interface Props {
  text: string;
  citations: Record<string, Citation>;
  onCitationClick: (key: string, citation: Citation) => void;
}

export function FormattedAnswer({ text, citations, onCitationClick }: Props) {
  // 🛡️ Strip internal metadata blocks that might have leaked into the stream
  const cleanText = text.replace(/\[\[Explainability:.*?\]\]/g, "").replace(/\[\[SuggestedQuestions:.*?\]\]/g, "").trim();

  // Split text into parts: regular text and citation tags
  const parts = cleanText.split(/(\[[SD]\d+\])/g);

  // Reassemble: render markdown for text parts, interactive badges for citations
  const elements = parts.map((part, i) => {
    const match = part.match(/^\[([SD]\d+)\]$/);
    const citation = match ? citations[part] : null;

    if (citation) {
      return (
        <HoverCard key={i} openDelay={200} closeDelay={100}>
          <HoverCardTrigger asChild>
            <button
              onClick={() => onCitationClick(part, citation)}
              className="citation-badge"
            >
              {part.replace(/[\[\]]/g, '')}
            </button>
          </HoverCardTrigger>
          <HoverCardContent className="w-80 p-3 bg-card border-border shadow-xl z-[100]">
            <div className="flex gap-3">
              <div className="mt-1">
                {citation.source_type === "sql" ? (
                  <Table2 className="h-4 w-4 text-primary" />
                ) : (
                  <FileText className="h-4 w-4 text-primary" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="label-mono text-[8px]">{part}</span>
                  <span className="text-[10px] font-semibold truncate text-foreground">
                    {citation.display_name}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground line-clamp-3 leading-relaxed">
                  {citation.context}
                </p>
                <div className="mt-2 text-[9px] font-mono text-primary/70">
                  Click to see full source →
                </div>
              </div>
            </div>
          </HoverCardContent>
        </HoverCard>
      );
    }
    // Render markdown for text segments
    return (
      <ReactMarkdown
        key={i}
        components={{
          p: ({ children }) => <span>{children}</span>,
          code: ({ children, className }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <pre className="surface-card p-3 rounded my-2 overflow-x-auto">
                  <code className="text-xs font-mono text-foreground">{children}</code>
                </pre>
              );
            }
            return <code className="px-1 py-0.5 rounded bg-muted text-xs font-mono text-primary">{children}</code>;
          },
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="text-xs border-collapse w-full">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1 text-left label-mono bg-muted/30">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1 text-foreground">{children}</td>
          ),
          strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
          em: ({ children }) => <em className="text-muted-foreground">{children}</em>,
          ul: ({ children }) => <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal list-inside my-1 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="text-sm text-foreground">{children}</li>,
        }}
      >
        {part}
      </ReactMarkdown>
    );
  });

  return (
    <div className="text-sm leading-relaxed text-foreground prose-compact" style={{ maxWidth: "65ch" }}>
      {elements}
    </div>
  );
}
