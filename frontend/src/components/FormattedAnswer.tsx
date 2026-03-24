import ReactMarkdown from "react-markdown";
import type { Citation } from "@/lib/api";

interface Props {
  text: string;
  citations: Record<string, Citation>;
  onCitationClick: (key: string, citation: Citation) => void;
}

export function FormattedAnswer({ text, citations, onCitationClick }: Props) {
  // Split text into parts: regular text and citation tags
  const parts = text.split(/(\[[SD]\d+\])/g);

  // Reassemble: render markdown for text parts, interactive badges for citations
  const elements = parts.map((part, i) => {
    const match = part.match(/^\[([SD]\d+)\]$/);
    if (match && citations[part]) {
      return (
        <button
          key={i}
          onClick={() => onCitationClick(part, citations[part])}
          className="citation-badge"
        >
          {part}
        </button>
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
