"use client";

import "katex/dist/katex.min.css";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, RefreshCw } from "lucide-react";
import {
  checkHealth,
  deleteDocument,
  deleteSession,
  listDocuments,
  uploadDocument,
} from "@/lib/api";
import { clearStoredSession, getOrCreateSession } from "@/lib/session";
import { ApiError, type Document, type Session } from "@/lib/types";
import ServerWakingNotice from "./ServerWakingNotice";
import UploadZone, { ALLOWED_EXTENSIONS } from "./UploadZone";
import DocumentList from "./DocumentList";
import ChatPanel from "./ChatPanel";

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB — mirrors the backend limit
const MAX_DOCS = 20; // per-session document cap — mirrors the backend limit

interface UploadIssue {
  key: string;
  filename: string;
  reason: string;
}

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export default function ChatApp() {
  // ── Cold-start health gate ──
  const [serverUp, setServerUp] = useState(false);
  const [wakeAttempts, setWakeAttempts] = useState(0);

  // ── Session + documents ──
  const [session, setSession] = useState<Session | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootNonce, setBootNonce] = useState(0);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadIssues, setUploadIssues] = useState<UploadIssue[]>([]);
  const [railOpen, setRailOpen] = useState(false);

  const openPickerRef = useRef<(() => void) | null>(null);

  // ── Health probe with backoff until the backend answers ──
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function probe(attempt: number) {
      const ok = await checkHealth(3000);
      if (cancelled) return;
      if (ok) {
        setServerUp(true);
        return;
      }
      setWakeAttempts(attempt + 1);
      const delay = Math.min(1500 * 2 ** attempt, 10_000);
      timer = window.setTimeout(() => void probe(attempt + 1), delay);
    }

    void probe(0);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  // ── Session bootstrap once the server is up ──
  useEffect(() => {
    if (!serverUp) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await getOrCreateSession();
        if (cancelled) return;
        setSession(s);
        setDocuments(s.documents ?? []);
      } catch {
        if (!cancelled) {
          setBootError("Could not open a session. The server may still be waking up.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [serverUp, bootNonce]);

  const sessionId = session?.id ?? null;

  // ── Poll documents every 1.5s while any is non-terminal ──
  const hasNonTerminal = documents.some(
    (d) => d.status === "pending" || d.status === "processing"
  );

  useEffect(() => {
    if (!sessionId || !hasNonTerminal) return;
    const timer = window.setInterval(async () => {
      try {
        const docs = await listDocuments(sessionId);
        setDocuments(docs);
      } catch {
        // Transient network hiccup — the next tick retries
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [sessionId, hasNonTerminal]);

  // ── Upload with client-side pre-checks mirroring backend limits ──
  const handleFiles = useCallback(
    async (files: File[]) => {
      if (!sessionId) return;
      const issues: UploadIssue[] = [];
      const accepted: File[] = [];
      let slots = MAX_DOCS - documents.length;

      for (const file of files) {
        const ext = fileExtension(file.name);
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
          issues.push({
            key: `${file.name}-${Date.now()}-type`,
            filename: file.name,
            reason: `Unsupported type "${ext || "none"}" — accepted: ${ALLOWED_EXTENSIONS.join(" ")}`,
          });
        } else if (file.size > MAX_FILE_BYTES) {
          issues.push({
            key: `${file.name}-${Date.now()}-size`,
            filename: file.name,
            reason: `${(file.size / (1024 * 1024)).toFixed(1)} MB exceeds the 10 MB limit`,
          });
        } else if (slots <= 0) {
          issues.push({
            key: `${file.name}-${Date.now()}-limit`,
            filename: file.name,
            reason: `Session is full — ${MAX_DOCS} documents max. Delete one to make room.`,
          });
        } else {
          accepted.push(file);
          slots -= 1;
        }
      }

      if (accepted.length > 0) {
        setUploading(true);
        for (const file of accepted) {
          try {
            const doc = await uploadDocument(sessionId, file);
            setDocuments((prev) => [
              ...prev.filter((d) => d.id !== doc.id),
              doc,
            ]);
          } catch (err) {
            issues.push({
              key: `${file.name}-${Date.now()}-api`,
              filename: file.name,
              reason:
                err instanceof ApiError
                  ? err.message
                  : "Upload failed — please try again.",
            });
          }
        }
        setUploading(false);
      }

      if (issues.length > 0) setUploadIssues((prev) => [...prev, ...issues]);
    },
    [sessionId, documents.length]
  );

  const handleDeleteDocument = useCallback(
    async (docId: string) => {
      if (!sessionId) return;
      // Optimistic remove; restore on failure via re-list
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      try {
        await deleteDocument(sessionId, docId);
      } catch {
        try {
          setDocuments(await listDocuments(sessionId));
        } catch {
          // Leave the optimistic state — polling/refresh will reconcile
        }
      }
    },
    [sessionId]
  );

  // ── New session: best-effort delete, drop storage, re-create ──
  const handleNewSession = useCallback(async () => {
    if (!session) return;
    const dirty = documents.length > 0;
    if (
      dirty &&
      !window.confirm(
        "Start a new session? Uploaded documents and chat history will be discarded."
      )
    ) {
      return;
    }
    try {
      await deleteSession(session.id);
    } catch {
      // Best-effort — expired sessions are cleaned up server-side anyway
    }
    clearStoredSession();
    setSession(null);
    setDocuments([]);
    setUploadIssues([]);
    try {
      const fresh = await getOrCreateSession();
      setSession(fresh);
      setDocuments(fresh.documents ?? []);
    } catch {
      setBootError("Could not open a new session. Retry in a moment.");
    }
  }, [session, documents.length]);

  // ── ChatPanel reports a rotated session (e.g. after SESSION_EXPIRED) ──
  const handleSessionRotated = useCallback((fresh: Session) => {
    setSession(fresh);
    setDocuments(fresh.documents ?? []);
    setUploadIssues([]);
  }, []);

  const hasReadyDocs = documents.some((d) => d.status === "ready");

  // ─────────────────────────────────────────────────────────────────────
  if (!serverUp) {
    return (
      <main className="flex min-h-dvh flex-col">
        <Header />
        <ServerWakingNotice attempts={wakeAttempts} />
      </main>
    );
  }

  if (!session) {
    return (
      <main className="flex min-h-dvh flex-col">
        <Header />
        <div className="flex flex-1 items-center justify-center px-6">
          <div className="card-paper max-w-sm p-6 text-center">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink/45">
              {bootError ? "Session error" : "Opening session…"}
            </p>
            {bootError && (
              <>
                <p className="mt-3 font-body text-sm text-ink/70">{bootError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setBootError(null);
                    setBootNonce((n) => n + 1);
                  }}
                  className="chip chip--accent mt-4 cursor-pointer"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        </div>
      </main>
    );
  }

  const rail = (
    <div className="space-y-5 p-4">
      {/* Session block */}
      <section aria-label="Session">
        <h2 className="font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/50">
          Session
        </h2>
        <div className="card-paper mt-2 flex items-center justify-between gap-2 px-3 py-2">
          <span
            className="truncate font-mono text-[11px] text-ink/70"
            title={session.id}
          >
            № {session.id.slice(0, 8)}
          </span>
          <button
            type="button"
            onClick={() => void handleNewSession()}
            className="flex shrink-0 items-center gap-1 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-accent hover:underline"
          >
            <RefreshCw size={10} strokeWidth={2} aria-hidden />
            New session
          </button>
        </div>
      </section>

      {/* Upload */}
      <section aria-label="Upload">
        <UploadZone
          disabled={uploading}
          uploading={uploading}
          onFiles={(files) => void handleFiles(files)}
          openPickerRef={openPickerRef}
        />

        {uploadIssues.length > 0 && (
          <ul className="mt-2 space-y-1.5" aria-label="Upload problems">
            {uploadIssues.map((issue) => (
              <li
                key={issue.key}
                className="border border-accent/60 bg-card px-2.5 py-1.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-[10px] font-medium text-accent">
                      ✗ {issue.filename}
                    </p>
                    <p className="mt-0.5 font-body text-[11px] leading-snug text-ink/65">
                      {issue.reason}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Dismiss problem with ${issue.filename}`}
                    onClick={() =>
                      setUploadIssues((prev) =>
                        prev.filter((i) => i.key !== issue.key)
                      )
                    }
                    className="shrink-0 font-mono text-[10px] text-ink/40 hover:text-accent"
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <DocumentList
        documents={documents}
        maxDocs={MAX_DOCS}
        onDelete={(docId) => void handleDeleteDocument(docId)}
        onRetry={() => openPickerRef.current?.()}
      />
    </div>
  );

  return (
    <main className="flex h-dvh flex-col">
      <Header />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* ── Left rail: 320px on desktop, collapsible sheet on mobile ── */}
        <aside className="shrink-0 border-b border-rule lg:w-80 lg:overflow-y-auto lg:border-b-0 lg:border-r">
          {/* Mobile disclosure */}
          <button
            type="button"
            onClick={() => setRailOpen((o) => !o)}
            aria-expanded={railOpen}
            className="flex w-full items-center justify-between px-4 py-2.5 lg:hidden"
          >
            <span className="font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/60">
              Session & documents
              <span className="ml-2 tabular-nums text-ink/40">
                {documents.length}/{MAX_DOCS}
              </span>
            </span>
            <ChevronDown
              size={14}
              strokeWidth={2}
              aria-hidden
              className={`text-ink/50 transition-transform ${railOpen ? "rotate-180" : ""}`}
            />
          </button>
          <div className={`${railOpen ? "block" : "hidden"} max-h-[45dvh] overflow-y-auto lg:block lg:max-h-none lg:overflow-visible`}>
            {rail}
          </div>
        </aside>

        {/* ── Main chat column ── */}
        <ChatPanel
          key={session.id}
          sessionId={session.id}
          hasReadyDocs={hasReadyDocs}
          onSessionRotated={handleSessionRotated}
          onRequestUpload={() => {
            setRailOpen(true);
            openPickerRef.current?.();
          }}
        />
      </div>
    </main>
  );
}

/** Slim masthead shared by every app state */
function Header() {
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-ink/80 px-4 py-2.5 sm:px-5">
      <Link href="/" className="flex items-baseline gap-2.5">
        <span
          className="font-display text-base font-semibold leading-none"
          style={{ fontVariationSettings: "'opsz' 40, 'SOFT' 80, 'WONK' 0" }}
        >
          Ask your PDFs
        </span>
        <span className="chip chip--accent hidden sm:inline-block" style={{ transform: "rotate(-1deg)" }}>
          Workbench
        </span>
      </Link>
      <Link
        href="/"
        className="dotted-link font-mono text-[10px] uppercase tracking-[0.12em]"
      >
        ← Index
      </Link>
    </header>
  );
}
