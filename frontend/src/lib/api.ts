const API_BASE = "http://localhost:8000";

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

export type DocumentIndexingStatus = "uploading" | "extracting" | "embedding" | "indexed" | "error";

export interface UploadedDocument {
  id: string;
  name: string;
  uploadedAt: Date;
  status: DocumentIndexingStatus;
  summary?: string;
  key_topics?: string[];
  suggested_questions?: string[];
}

export interface DocumentChunk {
  document_id: string;
  chunk_text: string;
  vector_score: number;
}

export async function sendChat(question: string, history: { role: string, content: string }[] = [], ownerId?: string, sessionId?: string, documentIds?: string[]): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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

export async function fetchUserSettings(userId: string): Promise<UserSettings> {
  const res = await fetch(`${API_BASE}/user/settings/${userId}`);
  if (!res.ok) throw new Error(`Fetch user settings failed: ${res.statusText}`);
  return res.json();
}

export async function updateUserSettings(settings: UserSettings): Promise<UserSettings> {
  const res = await fetch(`${API_BASE}/user/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error(`Update user settings failed: ${res.statusText}`);
  return res.json();
}

export async function createSession(userId: string): Promise<ChatSession> {
  const res = await fetch(`${API_BASE}/chat/sessions/?user_id=${userId}`, {
    method: "POST",
  });
  return res.json();
}

export async function listSessions(userId: string): Promise<ChatSession[]> {
  const res = await fetch(`${API_BASE}/chat/sessions/${userId}`);
  return res.json();
}

export async function getSessionMessages(sessionId: string): Promise<ChatMessagesResponse> {
  const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`);
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export async function uploadDocument(file: File, ownerId: string = "test_advisor_user"): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    headers: {
      "X-Owner-Id": ownerId
    },
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
}

export async function fetchDocuments(ownerId: string = "test_advisor_user"): Promise<UploadedDocument[]> {
  const res = await fetch(`${API_BASE}/documents/?owner_id=${ownerId}`);
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
  }));
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.statusText}`);
}

export async function fetchDocumentText(id: string): Promise<{ document_id: string, content: string }> {
  const res = await fetch(`${API_BASE}/documents/${id}/text`);
  if (!res.ok) throw new Error(`Fetch text failed: ${res.statusText}`);
  return res.json();
}
