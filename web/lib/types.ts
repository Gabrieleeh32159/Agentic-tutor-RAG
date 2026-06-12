/**
 * Shared TypeScript types mirroring the backend protocol contract.
 * This is the single source of truth for the frontend type system.
 */

// ─── Document ────────────────────────────────────────────────────────────────

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type DocumentStage = "parsing" | "ocr" | "embedding" | "saving" | null;

export interface Document {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  chunk_count: number;
  status: DocumentStatus;
  stage: DocumentStage;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

// ─── Session ─────────────────────────────────────────────────────────────────

export interface Session {
  id: string;
  title: string | null;
  created_at: string;
  last_activity_at: string;
  documents: Document[];
}

// ─── Messages ────────────────────────────────────────────────────────────────

export type MessageRole = "human" | "ai";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  grounded: "grounded" | "ungrounded" | "unverified" | null;
  created_at: string;
}

// ─── Sources (returned by the agent during a chat turn) ──────────────────────

export interface SourceChunk {
  chunk_id: string;
  chunk_text: string;
  score: number;
}

export interface Source {
  document_id: string;
  filename: string;
  score: number;
  chunks: SourceChunk[];
}

// ─── Chat SSE events (discriminated union) ───────────────────────────────────
// Backend streams `data: <json>` lines ending with `data: [DONE]`.

/** First event — carries the session id for newly created sessions */
export interface SessionIdEvent {
  session_id: string;
}

/** Agent step progress event */
export interface StepEvent {
  step: "retrieve" | "grade_documents" | "rewrite_query";
  detail: string;
  is_relevant?: boolean;
  query?: string;
  retry?: number;
  new_question?: string;
}

/** Retrieved source documents */
export interface SourcesEvent {
  sources: Source[];
}

/** A single streamed answer token */
export interface TokenEvent {
  token: string;
}

/** Final grounding verdict for the answer */
export interface GroundingEvent {
  grounding: {
    verdict: "grounded" | "ungrounded" | "unverified";
  };
}

/** Inline SSE error (non-200 responses come as a plain JSON envelope, not SSE) */
export interface SseErrorEvent {
  error: {
    code: string;
    message: string;
  };
}

export type ChatEvent =
  | SessionIdEvent
  | StepEvent
  | SourcesEvent
  | TokenEvent
  | GroundingEvent
  | SseErrorEvent;

// ─── Type guards for ChatEvent discrimination ─────────────────────────────────

export function isSessionIdEvent(e: ChatEvent): e is SessionIdEvent {
  return "session_id" in e;
}

export function isStepEvent(e: ChatEvent): e is StepEvent {
  return "step" in e;
}

export function isSourcesEvent(e: ChatEvent): e is SourcesEvent {
  return "sources" in e;
}

export function isTokenEvent(e: ChatEvent): e is TokenEvent {
  return "token" in e;
}

export function isGroundingEvent(e: ChatEvent): e is GroundingEvent {
  return "grounding" in e;
}

export function isSseErrorEvent(e: ChatEvent): e is SseErrorEvent {
  return "error" in e;
}

// ─── API error envelope ───────────────────────────────────────────────────────

/**
 * Error codes surfaced to the UI.
 * Row-level codes (e.g. "parse_failed") are lowercase strings on Document.error_code.
 */
export type ApiErrorCode =
  | "SESSION_NOT_FOUND"
  | "SESSION_EXPIRED"
  | "UNSUPPORTED_FILE_TYPE"
  | "FILE_TOO_LARGE"
  | "PARSE_FAILED"
  | "SESSION_DOCUMENT_LIMIT"
  | "INGESTION_BUSY"
  | "GUARDRAIL_BLOCKED"
  | "RATE_LIMITED"
  | string; // allow unknown codes without breaking narrowing

export interface ApiErrorEnvelope {
  error: {
    code: ApiErrorCode;
    message: string;
    request_id?: string;
  };
}

/** Thrown by lib/api.ts and lib/sse.ts on non-2xx responses */
export class ApiError extends Error {
  constructor(
    public readonly code: ApiErrorCode,
    message: string,
    public readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}
