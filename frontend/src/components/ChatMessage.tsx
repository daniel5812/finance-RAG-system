import { motion } from "framer-motion";
import type { Citation, LatencyBreakdown, QueryExecution } from "@/lib/api";
import { FormattedAnswer } from "./FormattedAnswer";
import { LatencyBar } from "./LatencyBar";
import { QueryExecutionPanel } from "./QueryExecutionPanel";

interface Props {
  role: "user" | "assistant";
  content: string;
  citations?: Record<string, Citation>;
  latency?: LatencyBreakdown;
  queryExecution?: QueryExecution;
  onCitationClick: (key: string, citation: Citation) => void;
}

export function ChatMessage({ role, content, citations, latency, queryExecution, onCitationClick }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
      className="py-4"
    >
      <span className="label-mono mb-2 block">
        {role === "user" ? "USER" : "AI"}
      </span>
      {role === "assistant" && citations ? (
        <div>
          <FormattedAnswer
            text={content}
            citations={citations}
            onCitationClick={onCitationClick}
          />
          {queryExecution && <QueryExecutionPanel execution={queryExecution} />}
          {latency && <LatencyBar breakdown={latency} />}
        </div>
      ) : (
        <p className="text-sm leading-relaxed text-foreground" style={{ maxWidth: "65ch" }}>
          {content}
        </p>
      )}
    </motion.div>
  );
}
