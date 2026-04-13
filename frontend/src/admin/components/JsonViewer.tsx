import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface JsonViewerProps {
  data: unknown;
  label?: string;
  defaultOpen?: boolean;
}

export function JsonViewer({ data, label = "data", defaultOpen = false }: JsonViewerProps) {
  const [open, setOpen] = useState(defaultOpen);

  if (data === null || data === undefined) return null;
  const isEmpty = typeof data === "object" && Object.keys(data as object).length === 0;
  if (isEmpty) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 font-mono"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {label}
      </button>
      {open && (
        <pre className={cn(
          "mt-1 p-3 rounded bg-gray-950 text-gray-100 text-xs overflow-auto max-h-64",
          "border border-gray-800 font-mono leading-relaxed"
        )}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}
