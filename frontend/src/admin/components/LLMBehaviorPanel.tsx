import { CheckCircle, AlertTriangle, XCircle, Brain, Shield, Eye, SkipForward } from "lucide-react";
import { LLMTrace } from "../services/observabilityApi";
import { LLMClassBadge } from "./StatusBadge";
import { cn } from "@/lib/utils";

export type LLMSkipReason = "cache_hit" | "early_exit" | "validation_failure" | "non_chat" | null;

interface LLMBehaviorPanelProps {
  trace: LLMTrace | null;
  skipReason?: LLMSkipReason;
}

function FlagRow({ label, active, danger = true }: { label: string; active: boolean; danger?: boolean }) {
  return (
    <div className={cn(
      "flex items-center gap-2 py-1 px-2 rounded text-xs",
      active
        ? (danger ? "bg-red-50 text-red-700 font-medium" : "bg-green-50 text-green-700 font-medium")
        : "text-gray-400"
    )}>
      {active
        ? <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
        : <CheckCircle className="w-3.5 h-3.5 flex-shrink-0 text-gray-300" />}
      <span>{label}</span>
      <span className="ml-auto font-mono text-xs">{active ? "YES" : "no"}</span>
    </div>
  );
}

function RiskFlagRow({ label, active }: { label: string; active: boolean }) {
  return (
    <div className={cn(
      "flex items-center gap-2 py-1 px-2 rounded text-xs",
      active ? "bg-red-50 text-red-700 font-medium" : "text-gray-400"
    )}>
      {active
        ? <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
        : <CheckCircle className="w-3.5 h-3.5 flex-shrink-0 text-gray-300" />}
      <span>{label}</span>
      <span className="ml-auto font-mono text-xs">{active ? "YES" : "no"}</span>
    </div>
  );
}

function BlockRow({ label, present }: { label: string; present: boolean }) {
  return (
    <div className={cn("flex items-center gap-2 py-0.5 text-xs", present ? "text-green-700" : "text-gray-400 line-through")}>
      <div className={cn("w-2 h-2 rounded-full flex-shrink-0", present ? "bg-green-500" : "bg-gray-300")} />
      {label}
    </div>
  );
}

const SKIP_REASON_TEXT: Record<NonNullable<LLMSkipReason>, string> = {
  cache_hit:          "Response served from cache — LLM call was skipped.",
  early_exit:         "Pipeline exited before reaching the intelligence layer.",
  validation_failure: "Request failed validation checks before LLM execution.",
  non_chat:           "This endpoint does not invoke the LLM intelligence layer.",
};

export function LLMBehaviorPanel({ trace, skipReason }: LLMBehaviorPanelProps) {
  if (!trace) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4">
        <div className="flex items-center gap-2 mb-2">
          <SkipForward className="w-4 h-4 text-gray-400" />
          <span className="text-sm font-semibold text-gray-600">LLM Not Executed</span>
        </div>
        <p className="text-xs text-gray-500 leading-relaxed">
          {skipReason ? SKIP_REASON_TEXT[skipReason] : "Intelligence layer did not run for this request."}
        </p>
      </div>
    );
  }

  const { behavior, input_blocks, constraints, output_structure } = trace;
  const flags = behavior.flags ?? [];
  const isDeviated = behavior.classification !== "followed_system";
  const hasRisk = flags.includes("hallucination_risk") || flags.includes("confidence_mismatch") || isDeviated;

  const classificationIcon = {
    followed_system:          <CheckCircle className="w-4 h-4 text-green-600" />,
    deviated:                  <XCircle className="w-4 h-4 text-red-600" />,
    added_unsupported_claims: <AlertTriangle className="w-4 h-4 text-amber-600" />,
  }[behavior.classification] ?? <Brain className="w-4 h-4 text-gray-400" />;

  return (
    <div className="space-y-4">
      {/* Classification */}
      <div className={cn("rounded-lg border p-3", isDeviated ? "border-red-200 bg-red-50" : "border-green-200 bg-green-50")}>
        <div className="flex items-center gap-2">
          {classificationIcon}
          <LLMClassBadge cls={behavior.classification} />
        </div>
        {behavior.notes && (
          <p className="text-xs text-gray-600 mt-1.5">{behavior.notes}</p>
        )}
      </div>

      {/* Risk Banner */}
      {hasRisk && (
        <div className="flex items-center gap-2 p-2 rounded bg-red-50 border border-red-200">
          <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0" />
          <span className="text-xs text-red-700 font-medium">Anomalies detected — review flags below</span>
        </div>
      )}

      {/* Behavior Flags */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Shield className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Behavior Flags</span>
        </div>
        <div className="space-y-0.5 rounded border p-2 bg-white">
          <RiskFlagRow label="Confidence Mismatch"    active={flags.includes("confidence_mismatch")} />
          <RiskFlagRow label="Arithmetic Attempted"   active={flags.includes("arithmetic_attempted")} />
          <RiskFlagRow label="Ignored Recommendation" active={flags.includes("ignored_recommendation")} />
          <RiskFlagRow label="Hallucination Risk"     active={flags.includes("hallucination_risk")} />
          <RiskFlagRow label="Unsupported Claims"     active={flags.includes("unsupported_claims")} />
        </div>
        {behavior.arithmetic_markers.length > 0 && (
          <div className="mt-1 text-xs font-mono text-red-600 bg-red-50 rounded px-2 py-1">
            Markers: {behavior.arithmetic_markers.join(" | ")}
          </div>
        )}
      </div>

      {/* What LLM Saw */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Eye className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">What LLM Saw</span>
        </div>
        <div className="space-y-0.5 rounded border p-2 bg-white">
          <BlockRow label="Normalized Portfolio" present={input_blocks.has_normalized_portfolio} />
          <BlockRow label="Market Context"       present={input_blocks.has_market_context} />
          <BlockRow label="Validation Block"     present={input_blocks.has_validation_block} />
          <BlockRow label="Vector Context"       present={input_blocks.has_vector_context} />
          <BlockRow label="SQL Context"          present={input_blocks.has_sql_context} />
        </div>
        <div className="mt-1 flex gap-3 text-xs text-gray-400 px-1">
          <span>~{input_blocks.estimated_prompt_tokens.toLocaleString()} tokens</span>
          <span>{input_blocks.intelligence_block_chars.toLocaleString()} chars intel block</span>
        </div>
      </div>

      {/* Constraints */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Shield className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Constraints Applied</span>
        </div>
        <div className="rounded border p-2 bg-white space-y-0.5">
          <FlagRow label="Forbidden Operations" active={constraints.forbidden_operations_applied} danger={false} />
          <FlagRow label="No Arithmetic Mode"   active={constraints.no_arithmetic_mode} danger={false} />
          <FlagRow label="Cite-Only Directive"  active={constraints.cite_only_directive} danger={false} />
          <FlagRow label="Intelligence Block"   active={constraints.intelligence_block_injected} danger={false} />
        </div>
      </div>

      {/* Output Structure */}
      <div>
        <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Output Structure</div>
        <div className="rounded border p-2 bg-white text-xs space-y-1.5 text-gray-600">
          {output_structure.recommendation_action && (
            <div className="font-semibold text-gray-800">
              Action: <span className="font-mono">{output_structure.recommendation_action}</span>
            </div>
          )}
          <div className="flex gap-3 text-gray-500 flex-wrap">
            <span>{output_structure.response_length_chars.toLocaleString()} chars</span>
            {output_structure.confidence_level && <span>confidence: {output_structure.confidence_level}</span>}
            <span>source: {output_structure.confidence_source}</span>
          </div>
          <div className="flex gap-2 flex-wrap pt-0.5">
            {output_structure.recommendation_action && <span className="text-green-600">✓ action</span>}
            {output_structure.has_explainability_block && <span className="text-green-600">✓ explainability</span>}
            {output_structure.has_suggested_questions && (
              <span className="text-green-600">✓ {output_structure.suggested_questions_count} questions</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
