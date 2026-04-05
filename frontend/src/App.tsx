import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Index from "./pages/Index.tsx";
import NotFound from "./pages/NotFound.tsx";
import Admin from "./pages/Admin";
import Portfolio from "./pages/Portfolio.tsx";
import Insights from "./pages/Insights.tsx";

import { GoogleOAuthProvider } from "@react-oauth/google";
import { Navigate } from "react-router-dom";
import { isAuthenticated, getUser } from "@/lib/auth";
import Login from "./pages/Login.tsx";
import { InsightsProvider, useInsights } from "@/lib/insights";

const queryClient = new QueryClient();

const ProtectedRoute = ({ children, requireAdmin = false }: { children: React.ReactNode; requireAdmin?: boolean }) => {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  if (requireAdmin && getUser()?.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
};

// Fetches insights once on mount if the user is already authenticated.
// Must be rendered inside InsightsProvider and BrowserRouter.
function InsightsFetcher() {
  const { refresh } = useInsights();
  useEffect(() => {
    if (isAuthenticated()) {
      refresh();
    }
  }, [refresh]); // refresh is stable (useCallback with [] deps) — no infinite loop risk
  return null;
}

const App = () => {
  const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  if (!GOOGLE_CLIENT_ID) {
    console.warn("VITE_GOOGLE_CLIENT_ID not found in .env. Google Login will not work.");
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <InsightsProvider>
            <Toaster />
            <Sonner />
            <BrowserRouter>
              <InsightsFetcher />
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <Index />
                    </ProtectedRoute>
                  }
                />
                {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
                {/* Admin Route */}
                <Route
                  path="/admin"
                  element={
                    <ProtectedRoute requireAdmin>
                      <Admin />
                    </ProtectedRoute>
                  }
                />

                {/* Portfolio Route */}
                <Route
                  path="/portfolio"
                  element={
                    <ProtectedRoute>
                      <Portfolio />
                    </ProtectedRoute>
                  }
                />

                {/* Insights Route */}
                <Route
                  path="/insights"
                  element={
                    <ProtectedRoute>
                      <Insights />
                    </ProtectedRoute>
                  }
                />

                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </BrowserRouter>
          </InsightsProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </GoogleOAuthProvider>
  );
};

export default App;
