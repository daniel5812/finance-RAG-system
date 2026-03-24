import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { SourceViewer } from "@/components/SourceViewer";
import { toast } from "sonner";
import { DocumentSidebar } from "@/components/DocumentSidebar";
import { ChatMessage } from "@/components/ChatMessage";
import { ChatInput } from "@/components/ChatInput";
import { SourcePanel } from "@/components/SourcePanel";
import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import { SuggestedQueries } from "@/components/SuggestedQueries";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Sidebar } from "@/components/Sidebar";
import { SettingsModal } from "@/components/SettingsModal";
import { sendChat, fetchDocuments, fetchUserSettings, updateUserSettings, listSessions, getSessionMessages, deleteSession, createSession } from "@/lib/api";
import type { Citation, LatencyBreakdown, UploadedDocument, QueryExecution, EngineMode, UserSettings, ChatSession } from "@/lib/api";
import { Settings as SettingsIcon, MessageSquare } from "lucide-react";

interface ChatEntry {
  role: "user" | "assistant";
  content: string;
  citations?: Record<string, Citation>;
  latency?: LatencyBreakdown;
  queryExecution?: QueryExecution;
  suggestedQuestions?: string[];
}

export default function Index() {
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeCitations, setActiveCitations] = useState<Record<string, Citation>>({});
  const [focusedCitation, setFocusedCitation] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [engineMode, setEngineMode] = useState<EngineMode | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [userSettings, setUserSettings] = useState<UserSettings>({ user_id: "test_advisor_user", custom_persona: null });
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [viewingSource, setViewingSource] = useState<{ id: string, name: string, citation: Citation | null } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolled = useRef(false);

  // Smart auto-scroll: only auto-scroll if user hasn't scrolled up
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      userScrolled.current = !atBottom;
    };
    el.addEventListener("scroll", handleScroll);
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (scrollRef.current && !userScrolled.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  useEffect(() => {
    const loadDocs = async () => {
      try {
        const docs = await fetchDocuments();
        setDocuments(docs);
      } catch (err) {
        console.error("Failed to load documents:", err);
      }
    };
    loadDocs();
  }, []);

  const loadSessions = async () => {
    try {
      const data = await listSessions("test_advisor_user");
      if (Array.isArray(data)) {
        setSessions(data);
      } else {
        console.error("Received non-array sessions data:", data);
        setSessions([]);
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await fetchUserSettings("test_advisor_user");
        setUserSettings(settings);
      } catch (err) {
        console.error("Failed to load user settings:", err);
      }
    };
    loadSettings();
  }, []);

  const handleSaveSettings = async (persona: string) => {
    try {
      const updated = await updateUserSettings({ user_id: "test_advisor_user", custom_persona: persona });
      setUserSettings(updated);
    } catch (err) {
      console.error("Failed to update settings:", err);
    }
  };

  const handleSessionSelect = async (id: string) => {
    setActiveSessionId(id);
    setIsLoading(true);
    try {
      const data = await getSessionMessages(id);
      const mappedMessages: ChatEntry[] = data.messages.map(m => {
        let parsedCitations = m.citations;
        if (typeof parsedCitations === "string") {
          try { parsedCitations = JSON.parse(parsedCitations); } catch { parsedCitations = {}; }
        }
        let parsedLatency = m.latency;
        if (typeof parsedLatency === "string") {
          try { parsedLatency = JSON.parse(parsedLatency); } catch { parsedLatency = {}; }
        }

        return {
          role: m.role,
          content: m.content,
          citations: parsedCitations,
          latency: parsedLatency
        };
      });
      setMessages(mappedMessages);
    } catch (err) {
      console.error("Failed to load session messages:", err);
      toast.error("Failed to load conversation.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewChat = () => {
    setMessages([]);
    setActiveSessionId(null);
    setEngineMode(null);
    setSelectedDocumentIds([]); // Clear selected documents for new chat
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await deleteSession(id);
      setSessions(prev => prev.filter(s => s.id !== id));
      if (activeSessionId === id) {
        handleNewChat();
      }
    } catch (err) {
      console.error("Failed to delete session:", err);
    }
  };

  const handleSend = useCallback(async (content: string) => {
    userScrolled.current = false;
    const userEntry: ChatEntry = { role: "user", content };
    setMessages((prev) => [...prev, userEntry]);
    setIsLoading(true);

    try {
      // 🔹 0. Create session if it doesn't exist
      let sessionId = activeSessionId;
      if (!sessionId) {
        const newSession = await createSession("test_advisor_user");
        sessionId = newSession.id;
        setActiveSessionId(sessionId);
        setSessions(prev => [newSession, ...prev]);
      }

      const history = messages.map(m => ({ role: m.role, content: m.content }));
      const res = await sendChat(
        content,
        history,
        "test_advisor_user",
        sessionId,
        selectedDocumentIds.length > 0 ? selectedDocumentIds : undefined
      );

      // Update sessions list to reflect title change or updated_at
      loadSessions();
      const assistantEntry: ChatEntry = {
        role: "assistant",
        content: res.answer,
        citations: res.citations,
        latency: res.latency_breakdown,
        queryExecution: res.query_execution,
        suggestedQuestions: res.suggested_questions,
      };
      setMessages((prev) => [...prev, assistantEntry]);

      if (res.source_type) {
        setEngineMode(res.source_type);
      }

      if (res.citations && Object.keys(res.citations).length > 0) {
        setActiveCitations(res.citations);
        setShowSources(true);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Connection error. Ensure the backend is running on localhost:8000." },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [messages, activeSessionId, selectedDocumentIds]);

  const handleCitationClick = useCallback((_key: string, citation: Citation) => {
    if (citation.source_type === "document") {
      setViewingSource({
        id: citation.id,
        name: citation.display_name,
        citation: citation
      });
    } else {
      setFocusedCitation(_key);
      setShowSources(true);
    }
  }, []);

  const handleDocumentUploaded = useCallback((doc: UploadedDocument) => {
    setDocuments((prev) => [doc, ...prev]);
  }, []);

  const handleDocumentStatusChange = useCallback((id: string, status: UploadedDocument["status"]) => {
    setDocuments((prev) =>
      prev.map((d) => (d.id === id ? { ...d, status } : d))
    );
  }, []);

  const handleDocumentDelete = useCallback((id: string) => {
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    setSelectedDocumentIds((prev) => prev.filter((docId) => docId !== id)); // Also remove from selected
  }, []);

  const handleToggleDocumentSelection = useCallback((id: string) => {
    setSelectedDocumentIds((prev) =>
      prev.includes(id) ? prev.filter((docId) => docId !== id) : [...prev, id]
    );
  }, []);

  const engineModeLabel: Record<EngineMode, string> = {
    generated: "AI Analysis",
    cache: "Result Cache",
    semantic_cache: "Semantic Knowledge",
  };

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSessionSelect={handleSessionSelect}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        documents={documents}
        onDocumentUploaded={handleDocumentUploaded}
        onDocumentStatusChange={handleDocumentStatusChange}
        onDocumentDelete={handleDocumentDelete}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        selectedDocumentIds={selectedDocumentIds}
        onToggleDocumentSelection={handleToggleDocumentSelection}
      />

      <main className="flex-1 flex flex-col min-w-0 bg-background/50 relative">
        <header className="h-14 border-b border-border/50 flex items-center justify-between px-6 bg-background/80 backdrop-blur-md z-10">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <MessageSquare className="h-4 w-4" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-sm font-semibold truncate max-w-[200px] sm:max-w-md">
                {activeSessionId ? sessions.find(s => s.id === activeSessionId)?.title : "New Conversation"}
              </h1>
              <div className="flex items-center gap-1.5">
                <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Live Engine</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {engineMode && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
                {engineModeLabel[engineMode]}
              </span>
            )}
            <button
              onClick={() => setShowSettings(true)}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-all flex items-center gap-2"
              title="AI Persona Settings"
            >
              <SettingsIcon className="h-4 w-4" />
              <span className="text-[10px] font-mono uppercase tracking-wider hidden sm:inline">Persona</span>
            </button>
            <ThemeToggle />
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 scroll-stable px-6">
          <div className="max-w-3xl mx-auto divide-y divide-border">
            {messages.length === 0 && !isLoading && (
              <SuggestedQueries onSelect={handleSend} />
            )}
            {messages.map((msg, i) => (
              <div key={i} className="py-6">
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  citations={msg.citations}
                  latency={msg.latency}
                  queryExecution={msg.queryExecution}
                  onCitationClick={handleCitationClick}
                />
                {msg.role === "assistant" && msg.suggestedQuestions && msg.suggestedQuestions.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2 duration-500 delay-300 fill-mode-both">
                    {msg.suggestedQuestions.map((q, j) => (
                      <button
                        key={j}
                        onClick={() => handleSend(q)}
                        className="text-xs px-3 py-1.5 rounded-full border border-primary/20 bg-primary/5 text-primary hover:bg-primary/10 transition-colors"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <AnimatePresence>
              {isLoading && <ThinkingIndicator />}
            </AnimatePresence>
          </div>
        </div>

        <ChatInput onSend={handleSend} isLoading={isLoading} />

        <SettingsModal
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
          settings={userSettings}
          onSave={handleSaveSettings}
        />
      </main>

      <AnimatePresence>
        {false && ( // Removed original standalone sources drawer since it's now in the sidebar
          <motion.div
            initial={{ opacity: 0, x: 300 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 300 }}
            className="fixed inset-y-0 right-0 w-80 bg-card border-l border-border shadow-2xl z-50 p-6"
          >
            {/* ... */}
          </motion.div>
        )}
      </AnimatePresence>
      <SourceViewer
        isOpen={!!viewingSource}
        onClose={() => setViewingSource(null)}
        documentId={viewingSource?.id || null}
        documentName={viewingSource?.name || ""}
        citation={viewingSource?.citation || null}
      />
    </div>
  );
}
