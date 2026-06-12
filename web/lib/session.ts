/**
 * Session management — localStorage-backed session id with auto-create on miss/expiry.
 *
 * Storage key: "aypdf.session"
 *
 * On 404 SESSION_NOT_FOUND or 410 SESSION_EXPIRED (detected by ApiError.code),
 * the stored id is dropped and a fresh session is created.
 *
 * This module only exports pure async functions.
 * React hooks live in components; this is framework-agnostic.
 */

import { createSession, getSession } from "./api";
import { ApiError, type Session } from "./types";

const STORAGE_KEY = "aypdf.session";

/** Read the stored session id from localStorage (or null if unavailable/absent) */
function readStoredId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Persist a session id to localStorage */
function writeStoredId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Ignore storage errors (private browsing, quota, etc.)
  }
}

/** Remove the stored session id (called on expiry / not-found) */
export function clearStoredSession(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore
  }
}

/**
 * Return a valid Session, creating a new one if:
 *  - no id is stored
 *  - the stored id returns 404 SESSION_NOT_FOUND
 *  - the stored id returns 410 SESSION_EXPIRED
 *
 * The returned session always has a valid (non-expired) id stored in localStorage.
 */
export async function getOrCreateSession(): Promise<Session> {
  const storedId = readStoredId();

  if (storedId) {
    try {
      const session = await getSession(storedId);
      return session;
    } catch (err) {
      // Drop the stale id and fall through to create a fresh session
      if (
        err instanceof ApiError &&
        (err.code === "SESSION_NOT_FOUND" || err.code === "SESSION_EXPIRED")
      ) {
        clearStoredSession();
        // fall through
      } else {
        // Network or other error — re-throw so the caller can handle it
        throw err;
      }
    }
  }

  const newSession = await createSession();
  writeStoredId(newSession.id);
  return newSession;
}
