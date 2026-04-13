import { cn } from "@/lib/utils";

type Status = "success" | "warning" | "failed" | "running" | "unknown";

const STATUS_CONFIG: Record<Status, { label: string; classes: string }> = {
  success: { label: "Success", classes: "bg-green-100 text-green-800 border-green-200" },
  warning: { label: "Warning", classes: "bg-amber-100 text-amber-800 border-amber-200" },
  failed:  { label: "Failed",  classes: "bg-red-100 text-red-800 border-red-200" },
  running: { label: "Running", classes: "bg-blue-100 text-blue-800 border-blue-200" },
  unknown: { label: "Unknown", classes: "bg-gray-100 text-gray-600 border-gray-200" },
};

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md";
}

export function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const cfg = STATUS_CONFIG[(status as Status)] ?? STATUS_CONFIG.unknown;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-medium",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
        cfg.classes
      )}
    >
      {cfg.label}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  const colors: Record<string, string> = {
    INFRA:    "bg-purple-100 text-purple-800 border-purple-200",
    PIPELINE: "bg-blue-100 text-blue-800 border-blue-200",
    DATA:     "bg-yellow-100 text-yellow-800 border-yellow-200",
    BUSINESS: "bg-orange-100 text-orange-800 border-orange-200",
    SECURITY: "bg-red-100 text-red-800 border-red-200",
  };
  return (
    <span className={cn("inline-flex items-center rounded border px-2 py-0.5 text-xs font-mono font-medium", colors[category] ?? "bg-gray-100 text-gray-700 border-gray-200")}>
      {category}
    </span>
  );
}

export function ConfidenceBadge({ level }: { level: string | null }) {
  if (!level) return <span className="text-gray-400 text-xs">—</span>;
  const colors: Record<string, string> = {
    high:   "bg-green-100 text-green-800 border-green-200",
    medium: "bg-amber-100 text-amber-800 border-amber-200",
    low:    "bg-red-100 text-red-800 border-red-200",
  };
  return (
    <span className={cn("inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium capitalize", colors[level] ?? "bg-gray-100 text-gray-600 border-gray-200")}>
      {level}
    </span>
  );
}

export function LLMClassBadge({ cls }: { cls: string | null }) {
  if (!cls) return <span className="text-gray-400 text-xs">—</span>;
  const cfg: Record<string, { label: string; classes: string }> = {
    followed_system:          { label: "Followed System",    classes: "bg-green-100 text-green-800 border-green-200" },
    deviated:                  { label: "Deviated",           classes: "bg-red-100 text-red-800 border-red-200" },
    added_unsupported_claims: { label: "Unsupported Claims", classes: "bg-amber-100 text-amber-800 border-amber-200" },
  };
  const c = cfg[cls] ?? { label: cls, classes: "bg-gray-100 text-gray-700 border-gray-200" };
  return (
    <span className={cn("inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium", c.classes)}>
      {c.label}
    </span>
  );
}
