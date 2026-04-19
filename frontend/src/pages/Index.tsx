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
import { UserProfile } from "@/components/UserProfile";

import { sendChat, sendChatStream, sendChatV2, fetchDocuments, fetchUserProfile, updateUserProfile, listSessions, getSessionMessages, deleteSession, createSession, deleteDocument, fetchFolders, createFolder, deleteFolder, setDocumentFolder } from "@/lib/api";
import type { Citation, LatencyBreakdown, UploadedDocument, QueryExecution, ChatMode, UserProfile as UserProfileType, ChatSession, UserProfileUpdatePayload, Folder } from "@/lib/api";
import { getUser } from "@/lib/auth";
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
  const [engineMode, setEngineMode] = useState<ChatMode | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [userSettings, setUserSettings] = useState<UserProfileType>({ user_id: getUser()?.id || "unknown", custom_persona: null, risk_tolerance: "medium", preferred_style: "deep", interests: [] });
  const [useRagV2TestMode, setUseRagV2TestMode] = useState(true);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [activeFolderId, setActiveFolderId] = useState<number | null>(null);
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
        // Auto-select all already-indexed documents on load
        const indexedIds = docs.filter((d) => d.status === "indexed").map((d) => d.id);
        if (indexedIds.length > 0) {
          setSelectedDocumentIds(indexedIds);
        }
      } catch (err) {
        console.error("Failed to load documents:", err);
      }
    };
    loadDocs();
  }, []);

  useEffect(() => {
    fetchFolders().then(setFolders).catch(err => console.error("Failed to load folders:", err));
  }, []);

  const handleFolderCreate = useCallback(async (name: string) => {
    try {
      const folder = await createFolder(name);
      setFolders(prev => [...prev, folder]);
    } catch (err) {
      console.error("Failed to create folder:", err);
    }
  }, []);

  const handleFolderDelete = useCallback(async (id: number) => {
    try {
      await deleteFolder(id);
      setFolders(prev => prev.filter(f => f.id !== id));
      if (activeFolderId === id) setActiveFolderId(null);
      // Clear folder_id on docs that were in the deleted folder
      setDocuments(prev => prev.map(d => d.folder_id === id ? { ...d, folder_id: null } : d));
    } catch (err) {
      console.error("Failed to delete folder:", err);
    }
  }, [activeFolderId]);

  const handleAssignFolder = useCallback(async (docId: string, folderId: number | null) => {
    try {
      await setDocumentFolder(docId, folderId);
      setDocuments(prev => prev.map(d => d.id === docId ? { ...d, folder_id: folderId } : d));
    } catch (err) {
      console.error("Failed to assign folder:", err);
    }
  }, []);

  const loadSessions = async () => {
    try {
      const data = await listSessions();
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
        const settings = await fetchUserProfile();
        setUserSettings(settings);
      } catch (err) {
        console.error("Failed to load user settings:", err);
      }
    };
    loadSettings();
  }, []);

  const handleSaveSettings = async (updates: UserProfileUpdatePayload) => {
    try {
      const updated = await updateUserProfile(updates);
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
        let parsedSuggestedQuestions = m.suggested_questions;
        if (typeof parsedSuggestedQuestions === "string") {
          try { parsedSuggestedQuestions = JSON.parse(parsedSuggestedQuestions); } catch { parsedSuggestedQuestions = []; }
        }

        return {
          role: m.role,
          content: m.content,
          citations: parsedCitations,
          latency: parsedLatency,
          suggestedQuestions: Array.isArray(parsedSuggestedQuestions) && parsedSuggestedQuestions.length > 0 ? parsedSuggestedQuestions : undefined,
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
      if (useRagV2TestMode) {
        console.info("[rag_v2] UI test mode enabled");
        const response = await sendChatV2(content);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: response.answer,
            citations: response.citations,
            latency: response.latency_breakdown,
            queryExecution: response.query_execution,
            suggestedQuestions: undefined,
          },
        ]);
        setEngineMode("rag_v2");
        if (response.citations && Object.keys(response.citations).length > 0) {
          setActiveCitations(response.citations);
          setShowSources(true);
        }
        return;
      }

      // 🔹 0. Create session if it doesn't exist
      let sessionId = activeSessionId;
      if (!sessionId) {
        const newSession = await createSession();
        sessionId = newSession.id;
        setActiveSessionId(sessionId);
        setSessions(prev => [newSession, ...prev]);
      }

      // Backend uses at most 6 messages (3 with summary, 6 without) — no need to send more
      const history = messages.slice(-6).map(m => ({ role: m.role, content: m.content }));

      // Initialize assistant entry for streaming
      let currentAssistantMessage = "";
      setMessages(prev => [...prev, { role: "assistant", content: "" }]);

      await sendChatStream(
        content,
        (token) => {
          setIsLoading(false); // Hide thinking once we start getting tokens
          currentAssistantMessage += token;
          setMessages(prev => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];
            if (lastMessage.role === "assistant") {
              lastMessage.content = currentAssistantMessage;
            }
            return newMessages;
          });
        },
        (meta) => {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];
            if (lastMessage.role === "assistant") {
              if (meta.citations) lastMessage.citations = meta.citations;
              if (meta.latency) lastMessage.latency = meta.latency;
              if (meta.suggested_questions) lastMessage.suggestedQuestions = meta.suggested_questions;
            }
            return newMessages;
          });
          if (meta.source_type) {
            setEngineMode(meta.source_type);
          }
          if (meta.citations && Object.keys(meta.citations).length > 0) {
            setActiveCitations(meta.citations);
            setShowSources(true);
          }
        },
        (title) => {
          setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s));
        },
        history,
        getUser()?.id || "unknown",

        sessionId,
        selectedDocumentIds.length > 0 ? selectedDocumentIds : undefined
      );

      // Update sessions list to reflect title change or updated_at
      loadSessions();
    } catch (err) {
      console.error("Stream error:", err);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Connection error. Ensure the backend is running on localhost:8000." },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [messages, activeSessionId, selectedDocumentIds, useRagV2TestMode]);

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
    // Auto-select document as soon as it becomes indexed
    if (status === "indexed") {
      setSelectedDocumentIds((prev) =>
        prev.includes(id) ? prev : [...prev, id]
      );
    }
  }, []);

  const handleDocumentDelete = useCallback(async (id: string) => {
    try {
      await deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSelectedDocumentIds((prev) => prev.filter((docId) => docId !== id)); // Also remove from selected
      toast.success("Document deleted successfully");
    } catch (err) {
      console.error("Failed to delete document:", err);
      toast.error("Failed to delete document");
    }
  }, []);

  const handleToggleDocumentSelection = useCallback((id: string) => {
    setSelectedDocumentIds((prev) =>
      prev.includes(id) ? prev.filter((docId) => docId !== id) : [...prev, id]
    );
  }, []);

  const engineModeLabel: Record<ChatMode, string> = {
    generated: "AI Analysis",
    cache: "Result Cache",
    semantic_cache: "Semantic Knowledge",
    rag_v2: "RAG V2 Test",
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
        folders={folders}
        activeFolderId={activeFolderId}
        onFolderSelect={setActiveFolderId}
        onFolderCreate={handleFolderCreate}
        onFolderDelete={handleFolderDelete}
        onAssignFolder={handleAssignFolder}
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
            <UserProfile onOpenSettings={() => setShowSettings(true)} />
          </div>
        </header>


        <div ref={scrollRef} className="flex-1 scroll-stable px-6">
          <div className="max-w-3xl mx-auto divide-y divide-border">
            {messages.length === 0 && !isLoading && (
              <SuggestedQueries onSelect={handleSend} />
            )}
            {(() => {
              // Only show follow-up buttons on the last assistant message
              const lastAssistantIdx = messages.reduce(
                (last, m, i) => (m.role === "assistant" ? i : last),
                -1
              );
              return messages.map((msg, i) => (
                <div key={i} className="py-6">
                  <ChatMessage
                    role={msg.role}
                    content={msg.content}
                    citations={msg.citations}
                    latency={msg.latency}
                    queryExecution={msg.queryExecution}
                    onCitationClick={handleCitationClick}
                  />
                  {msg.role === "assistant" && i === lastAssistantIdx && !isLoading && msg.suggestedQuestions && msg.suggestedQuestions.length > 0 && (
                    <div className="mt-4 flex flex-col gap-3">
                      <span className="label-mono flex items-center gap-2">
                        <div className="h-px w-4 bg-border" />
                        Follow-up Questions
                      </span>
                      <div className="flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2 duration-500 delay-300 fill-mode-both">
                        {msg.suggestedQuestions.map((q, j) => (
                          <button
                            key={j}
                            onClick={() => handleSend(q)}
                            className="suggested-question-chip"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ));
            })()}
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
        {showSources && (
          <motion.div
            initial={{ opacity: 0, x: 300 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 300 }}
            className="h-full border-l border-border bg-card z-20"
          >
            <SourcePanel
              citations={activeCitations}
              focusedCitation={focusedCitation}
              onClose={() => setShowSources(false)}
            />
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
