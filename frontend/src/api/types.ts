export type User = { id: string; email: string; is_active: boolean; created_at: string };
export type AuthResponse = { access_token: string; token_type: string; expires_in: number; user: User };

export type Document = {
  id: string; name: string; media_type: string; sha256: string; index_version: string;
  source_type: string; origin_uri: string | null; metadata: Record<string, unknown>;
};

export type JobState = "queued" | "running" | "retrying" | "completed" | "failed" | "cancelled" | "timed_out";
export type IngestionJob = {
  id: string; state: JobState; progress: number; message: string; attempt: number;
  max_attempts: number; error: string | null; error_code: string | null; result: Document | null;
};

export type ChatMessage = { role: "user" | "assistant"; content: string };
export type Citation = {
  document_id: string; source_name: string; excerpt: string; location: string | null;
  chunk_id: string | null; score: number | null; source_uri: string | null;
};
export type TutorAnswer = { answer: string; grounded: boolean; citations: Citation[] };
export type HintResponse = { problem: string; level: number; hint: string; hints: string[] };

export type Diagnostic = {
  exception_type: string; message: string; file_name: string; line_number: number | null;
  column_number: number | null; source_line: string | null;
  frames: { file_name: string; line_number: number; function_name: string; source_line: string | null }[];
};
export type TestResult = {
  name: string; passed: boolean; expected_output: string; actual_output: string; stderr: string;
  exit_code: number | null; duration_seconds: number; diagnostic: Diagnostic | null;
};
export type ExecutionResult = {
  execution_id: string | null; stdout: string; stderr: string; exit_code: number | null;
  duration_seconds: number; timed_out: boolean; cancelled: boolean; resource_limit_exceeded: boolean;
  truncated: boolean; disabled_reason: string | null; diagnostic: Diagnostic | null;
  traceback: string; test_results: TestResult[];
};
export type ExecutionJob = {
  id: string; state: JobState; result: ExecutionResult | null; error: string | null;
  error_code: string | null; progress: number; message: string; attempt: number; max_attempts: number;
};
export type TestCase = { name: string; stdin: string; expected_output: string };

export type Metric = {
  operation: string; calls: number; failures: number; failure_rate: number; average_latency_ms: number;
  p95_latency_ms: number; input_tokens: number; output_tokens: number; embedding_tokens: number;
  cost_usd: number; cost_configured: boolean;
};
export type MonitoringSummary = {
  window_seconds: number | null; total_calls: number; total_failures: number; total_cost_usd: number;
  cost_fully_configured: boolean; warning: string | null; operations: Metric[];
};
export type Health = { status: string; service: string };
export type Readiness = Health & { database: string; checks: Record<string, boolean> };
