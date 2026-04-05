import { createContext, useContext, useState, useCallback, createElement } from "react";
import type { ReactNode } from "react";
import { fetchInsights, type Insight } from "./api";

interface InsightsContextValue {
  insights: Insight[];
  hasNewInsights: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
  markSeen: () => void;
}

export const InsightsContext = createContext<InsightsContextValue | null>(null);

export function InsightsProvider({ children }: { children: ReactNode }) {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [hasNewInsights, setHasNewInsights] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchInsights();
      setInsights(data ?? []);
      if ((data ?? []).length > 0) setHasNewInsights(true);
    } catch (e) {
      console.error("Failed to fetch insights:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const markSeen = useCallback(() => {
    setHasNewInsights(false);
  }, []);

  return createElement(
    InsightsContext.Provider,
    { value: { insights, hasNewInsights, loading, refresh, markSeen } },
    children
  );
}

export function useInsights(): InsightsContextValue {
  const ctx = useContext(InsightsContext);
  if (!ctx) throw new Error("useInsights must be used within InsightsProvider");
  return ctx;
}
