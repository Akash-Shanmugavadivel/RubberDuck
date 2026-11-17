import type {
  AuthResponse, ChatMessage, ConversationDetail, ConversationSummary, Document, ExecutionJob, Health, HintResponse, IngestionJob,
  MonitoringSummary, Readiness, TestCase, TutorAnswer, User,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function getToken() { return sessionStorage.getItem("rubberduck_token"); }
export function setToken(token: string | null) {
  if (token) sessionStorage.setItem("rubberduck_token", token);
  else sessionStorage.removeItem("rubberduck_token");
}

async function request<T>(path: string, options: RequestInit = {}, authenticated = true): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (authenticated && token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail ?? body.message ?? message;
      if (Array.isArray(message)) message = message.map((item: { msg?: string }) => item.msg).join(", ");
    } catch { /* keep status message */ }
    if (response.status === 401) {
      setToken(null);
      window.dispatchEvent(new Event("rubberduck:unauthorized"));
    }
    throw new ApiError(response.status, String(message));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  register: (email: string, password: string) => request<User>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }, false),
  login: (email: string, password: string) => request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false),
  me: () => request<User>("/auth/me"),
  logout: () => request<{ message: string }>("/auth/logout", { method: "POST" }),
  health: () => request<Health>("/health", {}, false),
  readiness: () => request<Readiness>("/ready", {}, false),
  documents: () => request<Document[]>("/documents"),
  upload: (file: File) => { const body = new FormData(); body.append("file", file); return request<IngestionJob>("/documents/upload", { method: "POST", body }); },
  addYouTube: (reference: string, languages: string[]) => request<IngestionJob>("/documents/youtube", { method: "POST", body: JSON.stringify({ reference, languages }) }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  ingestionJob: (id: string) => request<IngestionJob>(`/ingestion-jobs/${id}`),
  cancelIngestion: (id: string) => request<IngestionJob>(`/ingestion-jobs/${id}/cancel`, { method: "POST" }),
  tutor: (query: string, mode: string, document_ids: string[], history: ChatMessage[], conversation_id: string | null = null) => request<TutorAnswer>("/tutor/answer", { method: "POST", body: JSON.stringify({ query, mode, document_ids, history, conversation_id }) }),
  conversations: () => request<ConversationSummary[]>("/tutor/conversations"),
  conversation: (id: string) => request<ConversationDetail>(`/tutor/conversations/${id}`),
  deleteConversation: (id: string) => request<void>(`/tutor/conversations/${id}`, { method: "DELETE" }),
  hint: (problem: string, history: ChatMessage[], previous_hints: string[]) => request<HintResponse>("/tutor/hint", { method: "POST", body: JSON.stringify({ problem, history, previous_hints }) }),
  executeProject: (files: Record<string, string>, entrypoint: string, tests: TestCase[]) => request<ExecutionJob>("/executions/project", { method: "POST", body: JSON.stringify({ files, entrypoint, tests }) }),
  executionJob: (id: string) => request<ExecutionJob>(`/executions/${id}`),
  cancelExecution: (id: string) => request<ExecutionJob>(`/executions/${id}/cancel`, { method: "POST" }),
  monitoring: (windowSeconds = 86400) => request<MonitoringSummary>(`/monitoring/summary?window_seconds=${windowSeconds}`),
};

export function errorMessage(error: unknown) { return error instanceof Error ? error.message : "Something went wrong"; }
