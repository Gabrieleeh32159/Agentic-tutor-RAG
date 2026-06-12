/**
 * Typed REST client for the FastAPI backend.
 * All backend contact goes through this module — components never fetch directly.
 *
 * Base URL: process.env.NEXT_PUBLIC_API_URL (default: http://localhost:8000)
 * Non-2xx responses are parsed and thrown as ApiError.
 */

import { ApiError, type ApiErrorEnvelope, type Document, type Message, type Session } from "./types";

const BASE_URL =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ─── Internal helpers ─────────────────────────────────────────────────────────

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return new ApiError("UNKNOWN", res.statusText || "Request failed", res.status);
  }

  const envelope = body as Partial<ApiErrorEnvelope>;
  const code = envelope?.error?.code ?? "UNKNOWN";
  const message = envelope?.error?.message ?? "Request failed";
  return new ApiError(code, message, res.status);
}

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!res.ok) {
    throw await parseError(res);
  }

  // 204 No Content — return undefined cast to T
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ─── Health ───────────────────────────────────────────────────────────────────

/**
 * Ping the backend health endpoint.
 * Resolves true when the server answers 2xx within `timeoutMs`; false otherwise
 * (timeout, network failure, or non-2xx). Never throws — used as a cold-start gate.
 */
export async function checkHealth(timeoutMs = 3000): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE_URL}/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Sessions ─────────────────────────────────────────────────────────────────

/**
 * Create a new session.
 * Returns the full Session object (including an empty `documents` array).
 */
export async function createSession(): Promise<Session> {
  return request<Session>("/sessions", { method: "POST" });
}

/**
 * Fetch an existing session by id.
 * Throws ApiError with code SESSION_NOT_FOUND or SESSION_EXPIRED on 404/410.
 */
export async function getSession(id: string): Promise<Session> {
  return request<Session>(`/sessions/${encodeURIComponent(id)}`);
}

/**
 * Delete a session and all its documents.
 */
export async function deleteSession(id: string): Promise<void> {
  return request<void>(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ─── Documents ────────────────────────────────────────────────────────────────

/**
 * Upload a single document to a session.
 * Returns a Document in "pending" or "processing" status (202 Accepted).
 */
export async function uploadDocument(
  sessionId: string,
  file: File
): Promise<Document> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(
    `${BASE_URL}/sessions/${encodeURIComponent(sessionId)}/documents`,
    {
      method: "POST",
      body: formData,
      // Do NOT set Content-Type — let the browser set multipart boundary
    }
  );

  if (!res.ok) {
    throw await parseError(res);
  }

  return res.json() as Promise<Document>;
}

/**
 * List all documents in a session.
 * Poll this every 1.5s while any doc is non-terminal (pending/processing).
 */
export async function listDocuments(sessionId: string): Promise<Document[]> {
  return request<Document[]>(
    `/sessions/${encodeURIComponent(sessionId)}/documents`
  );
}

/**
 * Delete a single document from a session.
 */
export async function deleteDocument(
  sessionId: string,
  docId: string
): Promise<void> {
  return request<void>(
    `/sessions/${encodeURIComponent(sessionId)}/documents/${encodeURIComponent(docId)}`,
    { method: "DELETE" }
  );
}

// ─── Messages ─────────────────────────────────────────────────────────────────

/**
 * Fetch the full message history for a session.
 * AI rows include a `grounded` verdict when available.
 */
export async function getMessages(sessionId: string): Promise<Message[]> {
  return request<Message[]>(
    `/sessions/${encodeURIComponent(sessionId)}/messages`
  );
}
