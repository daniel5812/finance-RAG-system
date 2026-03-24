import { motion } from "framer-motion";
import { TrendingUp, DollarSign, FileText, BarChart3 } from "lucide-react";

const suggestions = [
  { text: "What are the top holdings of SPY?", icon: TrendingUp },
  { text: "What is the current USD/ILS exchange rate?", icon: DollarSign },
  { text: "Summarize the inflation report I uploaded", icon: FileText },
  { text: "Compare SPY and QQQ performance", icon: BarChart3 },
];

interface Props {
  onSelect: (query: string) => void;
}

export function SuggestedQueries({ onSelect }: Props) {
  return (
    <div className="flex flex-col items-center justify-center h-full py-24">
      <span className="font-mono text-xs text-muted-foreground tracking-widest mb-2">
        HYBRID_FINANCE_v1.0
      </span>
      <p className="text-sm text-muted-foreground text-center max-w-md mb-8">
        Upload documents and ask questions about your portfolio. The engine combines SQL analytics with vector search for precise, cited answers.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full">
        {suggestions.map((s, i) => (
          <motion.button
            key={i}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, duration: 0.2 }}
            onClick={() => onSelect(s.text)}
            className="surface-card p-3 text-left flex items-start gap-2.5 hover:border-primary/40 transition-colors group cursor-pointer"
          >
            <s.icon className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors mt-0.5 flex-shrink-0" />
            <span className="text-xs text-muted-foreground group-hover:text-foreground transition-colors leading-relaxed">
              {s.text}
            </span>
          </motion.button>
        ))}
      </div>
    </div>
  );
}
