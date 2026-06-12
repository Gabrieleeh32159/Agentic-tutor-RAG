"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CornerDownLeft } from "lucide-react";
import { getMessages } from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { clearStoredSession, getOrCreateSession } from "@/lib/session";
import {
  ApiError,
  isGroundingEvent,
  isSourcesEvent,
  isSseErrorEvent,
  isStepEvent,
  isTokenEvent,
  type Session,
  type Source,
  type StepEvent,
} from "@/lib/types";
import MessageBubble from "./MessageBubble";
import EmptyThread from "./EmptyThread";
import StampedNotice from "./StampedNotice";
import type { GroundingVerdict } from "./GroundingBadge";

/** Re-render throttle for streamed tokens (ms) */
const TOKEN_FLUSH_MS = 30;

type ThreadItem =
  | {
      kind: "msg";
      key: string;
      role: "human" | "ai";
      content: string;
      grounded: GroundingVerdict | null;
      sources?: Source[];
      steps?: StepEvent[];
    }
  | { kind: "note"; key: string; code: string; message: string };

interface LiveTurn {
  steps: StepEvent[];
  sources: Source[] | null;
  grounding: GroundingVerdict | null;
  text: string;
  error: { code: string; message: string } | null;
}

function emptyTurn(): LiveTurn {
  return { steps: [], sources: null, grounding: null, text: "", error: null };
}

/** Inline system note for SSE-level errors (stream timeout / failure) */
function SystemNote({ code, message }: { code: string; message: string }) {
  return (
    <div className="ml-13 flex items-baseline gap-2 border-l-2 border-accent pl-3" role="status">
      <span className="font-mono text-[10px] font-medium uppercase tracking-[0.15em] text-accent">
        ⚠ {code.replace(/_/g, " ")}
      </span>
      <span className="font-body text-xs text-ink/60">{message}</span>
    </div>
  );
}

export default function ChatPanel({
  sessionId,
  hasReadyDocs,
  onSessionRotated,
  onRequestUpload,
}: {
  sessionId: string;
  hasReadyDocs: boolean;
  onSessionRotated: (session: Session) => void;
  onRequestUpload: () => void;
}) {
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  const [streaming, setStreaming] = useState(false);
  const [liveText, setLiveText] = useState("");
  const [liveSteps, setLiveSteps] = useState<StepEvent[]>([]);
  const [liveSources, setLiveSources] = useState<Source[] | null>(null);
  const [liveGrounding, setLiveGrounding] = useState<GroundingVerdict | null>(null);

  const [notice, setNotice] = useState<{ title: string; message: string } | null>(null);
  const [input, setInput] = useState("");

  const turnRef = useRef<LiveTurn>(emptyTurn());
  const flushTimerRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  // ── History: load persisted human/ai rows on mount.
  // ChatApp remounts this panel (key={session.id}) on rotation, so initial
  // state is already a clean slate — this effect only fetches. ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const messages = await getMessages(sessionId);
        if (cancelled) return;
        const items: ThreadItem[] = [];
        for (const m of messages) {
          // Skip tool/system rows and ai rows persisted with empty content
          if (m.role !== "human" && m.role !== "ai") continue;
          if (m.role === "ai" && !m.content.trim()) continue;
          items.push({
            kind: "msg",
            key: m.id,
            role: m.role,
            content: m.content,
            grounded: m.grounded,
          });
        }
        setThread(items);
      } catch {
        // Fresh or expired sessions simply start with an empty thread
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // ── Abort an in-flight stream on unmount ──
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (flushTimerRef.current != null) clearTimeout(flushTimerRef.current);
    };
  }, []);

  // ── Keep the thread pinned to the bottom unless the reader scrolled up ──
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [thread, liveText, liveSteps, liveSources, liveGrounding, streaming]);

  const send = useCallback(
    async (raw: string) => {
      const question = raw.trim();
      if (!question || streaming) return;

      setNotice(null);
      setInput("");
      if (composerRef.current) composerRef.current.style.height = "auto";
      stickToBottomRef.current = true;

      setThread((prev) => [
        ...prev,
        {
          kind: "msg",
          key: `q-${Date.now()}`,
          role: "human",
          content: question,
          grounded: null,
        },
      ]);

      turnRef.current = emptyTurn();
      setLiveText("");
      setLiveSteps([]);
      setLiveSources(null);
      setLiveGrounding(null);
      setStreaming(true);

      const abort = new AbortController();
      abortRef.current = abort;

      const flushText = () => {
        flushTimerRef.current = null;
        setLiveText(turnRef.current.text);
      };

      try {
        await streamChat(question, sessionId, {
          signal: abort.signal,
          onEvent: (event) => {
            const turn = turnRef.current;
            if (isTokenEvent(event)) {
              turn.text += event.token;
              if (flushTimerRef.current == null) {
                flushTimerRef.current = window.setTimeout(flushText, TOKEN_FLUSH_MS);
              }
            } else if (isStepEvent(event)) {
              turn.steps = [...turn.steps, event];
              setLiveSteps(turn.steps);
            } else if (isSourcesEvent(event)) {
              // One sources event per retrieve attempt — the last one wins
              if (event.sources.length > 0) {
                turn.sources = event.sources;
                setLiveSources(event.sources);
              }
            } else if (isGroundingEvent(event)) {
              turn.grounding = event.grounding.verdict;
              setLiveGrounding(event.grounding.verdict);
            } else if (isSseErrorEvent(event)) {
              turn.error = event.error;
            }
            // SessionIdEvent: informational — our session id is already known
          },
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // Cancelled (unmount/navigation) — keep whatever already streamed
        } else if (err instanceof ApiError) {
          if (err.code === "SESSION_EXPIRED" || err.code === "SESSION_NOT_FOUND") {
            setNotice({
              title: "Notice — Session expired",
              message:
                "Your session expired, so we opened a fresh one. Uploaded documents were cleared with it — re-upload to keep asking.",
            });
            clearStoredSession();
            try {
              const fresh = await getOrCreateSession();
              onSessionRotated(fresh);
            } catch {
              // Backend unreachable — the health gate handles the next visit
            }
          } else if (err.code === "GUARDRAIL_BLOCKED") {
            setNotice({ title: "Notice — Question declined", message: err.message });
          } else if (err.code === "RATE_LIMITED") {
            setNotice({ title: "Notice — Rate limited", message: err.message });
          } else {
            setNotice({
              title: `Notice — ${err.code.replace(/_/g, " ")}`,
              message: err.message,
            });
          }
        } else {
          setNotice({
            title: "Notice — Connection lost",
            message: "The stream was interrupted before finishing. Please try again.",
          });
        }
      } finally {
        if (flushTimerRef.current != null) {
          clearTimeout(flushTimerRef.current);
          flushTimerRef.current = null;
        }
        const turn = turnRef.current;
        const finished: ThreadItem[] = [];
        if (turn.text.trim() || turn.steps.length > 0) {
          finished.push({
            kind: "msg",
            key: `a-${Date.now()}`,
            role: "ai",
            content: turn.text,
            grounded: turn.grounding,
            sources: turn.sources ?? undefined,
            steps: turn.steps.length > 0 ? turn.steps : undefined,
          });
        }
        if (turn.error) {
          finished.push({
            kind: "note",
            key: `e-${Date.now()}`,
            code: turn.error.code,
            message: turn.error.message,
          });
        }
        if (finished.length > 0) setThread((prev) => [...prev, ...finished]);
        setStreaming(false);
        setLiveText("");
        setLiveSteps([]);
        setLiveSources(null);
        setLiveGrounding(null);
        abortRef.current = null;
      }
    },
    [sessionId, streaming, onSessionRotated]
  );

  function handleComposerKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  function autoResize(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  // Q/A gutter numbering
  let qCount = 0;
  let aCount = 0;
  const liveIndex =
    thread.filter((t) => t.kind === "msg" && t.role === "ai").length + 1;
  const isEmpty = !historyLoading && thread.length === 0 && !streaming;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ── Thread ── */}
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottomRef.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 py-6 sm:px-6">
          {historyLoading && (
            <p className="py-8 text-center font-mono text-[10px] uppercase tracking-[0.18em] text-ink/35">
              Opening the ledger…
            </p>
          )}

          {isEmpty && (
            <EmptyThread
              hasReadyDocs={hasReadyDocs}
              onRequestUpload={onRequestUpload}
              onPickSample={(q) => {
                setInput(q);
                composerRef.current?.focus();
              }}
            />
          )}

          <div className="space-y-6">
            {thread.map((item) => {
              if (item.kind === "note") {
                return (
                  <SystemNote key={item.key} code={item.code} message={item.message} />
                );
              }
              const index = item.role === "human" ? ++qCount : ++aCount;
              return (
                <MessageBubble
                  key={item.key}
                  role={item.role}
                  content={item.content}
                  index={index}
                  grounded={item.grounded}
                  sources={item.sources}
                  steps={item.steps}
                />
              );
            })}

            {/* ── Live streaming turn ── */}
            {streaming && (
              <div aria-live="polite" aria-busy="true">
                <MessageBubble
                  role="ai"
                  content={liveText}
                  index={liveIndex}
                  grounded={liveGrounding}
                  sources={liveSources ?? undefined}
                  steps={liveSteps}
                  streaming
                  animateBadge
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Stamped notices (guardrail / rate limit / expiry) ── */}
      {notice && (
        <div className="mx-auto w-full max-w-3xl px-4 pb-3 sm:px-6">
          <StampedNotice
            title={notice.title}
            message={notice.message}
            onDismiss={() => setNotice(null)}
          />
        </div>
      )}

      {/* ── Composer: a clean writing line on paper ── */}
      <div className="border-t border-rule bg-paper/85 backdrop-blur-[1px]">
        <form
          className="mx-auto w-full max-w-3xl px-4 py-3 sm:px-6"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <div className="card-paper flex items-end gap-2 px-3 py-2">
            <label htmlFor="composer" className="sr-only">
              Ask a question about your documents
            </label>
            <textarea
              id="composer"
              ref={composerRef}
              rows={1}
              value={input}
              disabled={streaming}
              placeholder={
                hasReadyDocs
                  ? "Ask about your documents…"
                  : "Upload a document, then ask about it…"
              }
              onChange={(e) => {
                setInput(e.target.value);
                autoResize(e.target);
              }}
              onKeyDown={handleComposerKeyDown}
              className="max-h-40 min-h-[1.6rem] flex-1 resize-none bg-transparent font-body text-sm leading-relaxed text-ink outline-none placeholder:text-ink/35 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              aria-label="Send question"
              className="mb-0.5 flex shrink-0 items-center gap-1.5 border border-ink bg-ink px-2.5 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-paper transition-colors disabled:border-rule disabled:bg-transparent disabled:text-ink/30"
            >
              Send
              <CornerDownLeft size={11} strokeWidth={2} aria-hidden />
            </button>
          </div>
          <p className="mt-1.5 text-right font-mono text-[9px] uppercase tracking-[0.12em] text-ink/35">
            {streaming ? "The agent is writing…" : "Enter ↵ send · Shift+Enter new line"}
          </p>
        </form>
      </div>
    </div>
  );
}
