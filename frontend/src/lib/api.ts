import { getToken } from "./auth";

export const API_BASE = "http://localhost:8000";


export async function authenticatedFetch(url: string, options: RequestInit = {}) {

  const token = getToken();
  const headers = {
    ...options.headers,
    "Content-Type": options.body instanceof FormData ? undefined : "application/json",
    "Authorization": token ? `Bearer ${token}` : "",
  };

  // Remove Content-Type if it's FormData (browser sets it with boundary)
  if (options.body instanceof FormData) {
    delete (headers as any)["Content-Type"];
  }

  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    // Optional: handle unauthorized (e.g., redirect to login)
    localStorage.removeItem("advisor_token");
    window.location.href = "/login";
  }
  return res;
}

export interface Citation {
  source_type: "sql" | "document";
  id: string;
  display_name: string;
  context: string;
}

export interface LatencyBreakdown {
  planning: number;
  sql: number;
  embedding: number;
  routing: number;
  retrieval: number;
  rerank: number;
  generation: number;
  total: number;
}

export type EngineMode = "generated" | "cache" | "semantic_cache";

export interface QueryExecution {
  type: "sql" | "vector" | "hybrid";
  queries: string[];
  documents_used?: string[];
}

export interface ChatResponse {
  answer: string;
  sources: any[];
  citations: Record<string, Citation>;
  latency_breakdown: LatencyBreakdown;
  source_type: EngineMode;
  query_execution?: QueryExecution;
  suggested_questions?: string[];
  session_id?: string;
  // Explainability
  reasoning_summary?: string;
  confidence_level?: "low" | "medium" | "high";
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessagesResponse {
  messages: any[];
}

export interface UserSettings {
  user_id: string;
  custom_persona: string | null;
  updated_at?: string;
}

export interface UserProfile extends UserSettings {
  risk_tolerance: "low" | "medium" | "high";
  preferred_style: string;
  interests: string[];
  experience_level?: string;
}

export interface Insight {
  id: number;
  insight_text: string;
  relevance_score: number;
  timestamp: string;
}

export type DocumentIndexingStatus = "uploading" | "extracting" | "embedding" | "indexed" | "error";

export interface Folder {
  id: number;
  name: string;
  owner_id: string;
  created_at: string;
}

export interface UploadedDocument {
  id: string;
  name: string;
  uploadedAt: Date;
  status: DocumentIndexingStatus;
  summary?: string;
  key_topics?: string[];
  suggested_questions?: string[];
  folder_id?: number | null;
}

export interface DocumentChunk {
  document_id: string;
  chunk_text: string;
  vector_score: number;
}

export async function sendChat(question: string, history: { role: string, content: string }[] = [], ownerId?: string, sessionId?: string, documentIds?: string[]): Promise<ChatResponse> {
  const res = await authenticatedFetch(`${API_BASE}/chat`, {
    method: "POST",
    body: JSON.stringify({
      question,
      history,
      user_role: "employee",
      owner_id: ownerId,
      session_id: sessionId,
      document_ids: documentIds
    }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`);
  return res.json();
}

export async function sendChatStream(
  question: string,
  onToken: (token: string) => void,
  onMeta: (meta: any) => void,
  onTitle: (title: string) => void,
  history: { role: string, content: string }[] = [],
  ownerId?: string,
  sessionId?: string,
  documentIds?: string[]
): Promise<void> {
  const response = await authenticatedFetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    body: JSON.stringify({
      question,
      history,
      user_role: "employee",
      owner_id: ownerId,
      session_id: sessionId,
      document_ids: documentIds
    }),
  });

  if (!response.ok) throw new Error("Stream failed");

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.substring(6));
          if (data.type === "token") {
            onToken(data.content);
          } else if (data.type === "meta") {
            onMeta(data);
          } else if (data.type === "title") {
            onTitle(data.content);
          }
        } catch (e) {
          console.warn("JSON parse error in stream:", e, line);
        }
      }
    }
  }
}

export async function fetchUserSettings(): Promise<UserSettings> {
  const res = await authenticatedFetch(`${API_BASE}/user/profile`);
  if (!res.ok) throw new Error(`Fetch user settings failed: ${res.statusText}`);
  return res.json();
}

export interface UserProfileUpdatePayload {
  risk_tolerance?: "low" | "medium" | "high";
  preferred_style?: "simple" | "deep";
  experience_level?: "beginner" | "intermediate" | "expert";
  custom_persona?: string | null;
  interests?: string[];
}

export async function updateUserSettings(settings: UserSettings): Promise<UserSettings> {
  const res = await authenticatedFetch(`${API_BASE}/user/settings`, {
    method: "POST",
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error(`Update user settings failed: ${res.statusText}`);
  return res.json();
}

export async function updateUserProfile(updates: UserProfileUpdatePayload): Promise<UserProfile> {
  const res = await authenticatedFetch(`${API_BASE}/user/profile`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error(`Update user profile failed: ${res.statusText}`);
  return res.json();
}

export async function createSession(): Promise<ChatSession> {
  const res = await authenticatedFetch(`${API_BASE}/chat/sessions/`, {
    method: "POST",
  });
  return res.json();
}

export async function listSessions(): Promise<ChatSession[]> {
  const res = await authenticatedFetch(`${API_BASE}/chat/sessions/`);
  return res.json();
}

export async function getSessionMessages(sessionId: string): Promise<ChatMessagesResponse> {
  const res = await authenticatedFetch(`${API_BASE}/chat/sessions/${sessionId}/messages`);
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  await authenticatedFetch(`${API_BASE}/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export async function uploadDocument(file: File, folderId?: number, documentId?: string): Promise<{ document_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  if (folderId !== undefined) {
    formData.append("folder_id", folderId.toString());
  }
  if (documentId !== undefined) {
    formData.append("document_id", documentId);
  }
  const res = await authenticatedFetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json();
}

export async function fetchDocumentStatus(documentId: string): Promise<UploadedDocument | null> {
  const res = await authenticatedFetch(`${API_BASE}/documents/${documentId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Fetch status failed: ${res.statusText}`);
  const doc = await res.json();
  const statusMap: Record<string, DocumentIndexingStatus> = {
    "pending_processing": "uploading",
    "processing": "extracting",
    "completed": "indexed",
    "failed": "error",
  };
  return {
    id: doc.document_id,
    name: doc.original_filename,
    uploadedAt: new Date(doc.created_at),
    status: statusMap[doc.status] || "error",
    summary: doc.summary,
    key_topics: doc.key_topics,
    suggested_questions: doc.suggested_questions,
    folder_id: doc.folder_id ?? null,
  };
}

export async function fetchDocuments(): Promise<UploadedDocument[]> {
  const res = await authenticatedFetch(`${API_BASE}/documents/`);
  if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`);
  const data = await res.json();

  const statusMap: Record<string, DocumentIndexingStatus> = {
    "pending_processing": "uploading",
    "processing": "extracting",
    "completed": "indexed",
    "failed": "error"
  };

  return data.map((doc: any) => ({
    id: doc.document_id,
    name: doc.original_filename,
    uploadedAt: new Date(doc.created_at),
    status: statusMap[doc.status] || "error",
    summary: doc.summary,
    key_topics: doc.key_topics,
    suggested_questions: doc.suggested_questions,
    folder_id: doc.folder_id ?? null,
  }));
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await authenticatedFetch(`${API_BASE}/documents/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.statusText}`);
}

export async function fetchDocumentText(id: string): Promise<{ document_id: string, content: string }> {
  const res = await authenticatedFetch(`${API_BASE}/documents/${id}/text`);
  if (!res.ok) throw new Error(`Fetch text failed: ${res.statusText}`);
  return res.json();
}

export async function fetchInsights(): Promise<Insight[]> {
  const res = await authenticatedFetch(`${API_BASE}/insights/`);
  if (!res.ok) throw new Error("Failed to fetch insights");
  const data = await res.json();
  return Array.isArray(data.insights) ? data.insights : [];
}

export async function fetchUserProfile(): Promise<UserProfile> {
  const res = await authenticatedFetch(`${API_BASE}/user/profile`);
  if (!res.ok) throw new Error("Failed to fetch user profile");
  return res.json();
}
export async function fetchMetrics(): Promise<any> {
  const res = await authenticatedFetch(`${API_BASE}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}

// ── Portfolio Management ──────────────────────────────────────────────────────

export interface PortfolioPosition {
  id: number;
  user_id: string;
  symbol: string;
  quantity: number;
  cost_basis: number | null;
  currency: string;
  account: string;
  date: string;
  source: string;
  created_at?: string;
}

export interface PortfolioPositionCreate {
  symbol: string;
  quantity: number;
  cost_basis?: number | null;
  currency?: string;
  account?: string;
  date: string; // ISO format YYYY-MM-DD
}

export async function fetchPortfolioPositions(): Promise<PortfolioPosition[]> {
  const res = await authenticatedFetch(`${API_BASE}/portfolio/positions`);
  if (!res.ok) throw new Error("Failed to fetch portfolio positions");
  return res.json();
}

export async function addPortfolioPosition(payload: PortfolioPositionCreate): Promise<{ status: string; rows_ingested: number }> {
  const res = await authenticatedFetch(`${API_BASE}/portfolio/positions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to add position: ${res.statusText}`);
  return res.json();
}

export async function deletePortfolioPosition(symbol: string, account = "default"): Promise<void> {
  const res = await authenticatedFetch(
    `${API_BASE}/portfolio/positions/${encodeURIComponent(symbol)}?account=${encodeURIComponent(account)}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(`Failed to delete position: ${res.statusText}`);
}

export async function importPortfolioFile(file: File): Promise<{ status: string; rows_ingested: number; parse_errors: string[] }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await authenticatedFetch(`${API_BASE}/portfolio/positions/import`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Import failed: ${res.statusText}`);
  return res.json();
}

// ── Document Folders ──────────────────────────────────────────────────────────

export async function fetchFolders(): Promise<Folder[]> {
  const res = await authenticatedFetch(`${API_BASE}/folders/`);
  if (!res.ok) throw new Error(`Failed to fetch folders: ${res.statusText}`);
  return res.json();
}

export async function createFolder(name: string): Promise<Folder> {
  const res = await authenticatedFetch(`${API_BASE}/folders/`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`Failed to create folder: ${res.statusText}`);
  return res.json();
}

export async function deleteFolder(id: number): Promise<void> {
  const res = await authenticatedFetch(`${API_BASE}/folders/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete folder: ${res.statusText}`);
}

export async function setDocumentFolder(documentId: string, folderId: number | null): Promise<void> {
  const res = await authenticatedFetch(`${API_BASE}/documents/${documentId}/folder`, {
    method: "PATCH",
    body: JSON.stringify({ folder_id: folderId }),
  });
  if (!res.ok) throw new Error(`Failed to set document folder: ${res.statusText}`);
}
