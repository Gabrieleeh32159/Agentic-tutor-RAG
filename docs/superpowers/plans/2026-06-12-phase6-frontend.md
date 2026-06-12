# Phase 6: Next.js Frontend — Landing Page + Ask-your-PDFs App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public-facing Next.js app in `/web`: an animated landing page that explains the pipeline (upload → parse/OCR → chunks → embeddings → agent loop → streamed answer) and the actual app — drag-drop upload with live ingestion status, streaming chat with an agent-step timeline, sources panel, and grounding badge.

**Architecture:** Next.js App Router + TypeScript + Tailwind v4 in `web/` (same repo; Vercel project rooted there in Phase 7). A thin typed `lib/` layer owns ALL backend contact: `api.ts` (REST client, `NEXT_PUBLIC_API_URL`), `sse.ts` (fetch + ReadableStream + a hand-rolled SSE line parser → discriminated-union events), `session.ts` (localStorage session id; 404/410 → create fresh). Components never fetch directly. The landing page is fully static (no API calls). Backend gets a `FRONTEND_ORIGIN` setting replacing the CORS wildcard.

**Design direction (committed — do not water down):** *Paper & ink, editorial-archival.* The product is about documents, so the UI feels like working with annotated paper:
- **Palette (CSS variables):** paper field `#F6F1E7` (slightly warm), ink `#1C1814`, faint rule lines `#E2D9C8`, one accent: vermilion `#D8431F` (stamps, active states, the grounding badge, links). Dark is NOT used — commit to the light paper world; depth comes from layered paper cards (`#FFFDF7`) with hard 1px ink borders and small offset shadows (`2px 2px 0 rgba(28,24,20,0.12)`), not blur-heavy elevation.
- **Type:** `Fraunces` (Google, variable — use high optical size + soft "wonk" for display headlines), `IBM Plex Mono` for technical labels/step names/scores/file metadata, `IBM Plex Sans` for UI body. Loaded via `next/font/google`. NEVER Inter/system stacks.
- **Texture & details:** subtle paper-grain (tiny SVG noise as a data-URI overlay at low opacity), hairline horizontal rules like ruled paper in section backgrounds, "stamped" status chips (mono uppercase, 1px border, slight rotation −1° to 1°), dotted-underline links, a vermilion margin-line on the active chat answer like an editor's mark.
- **Motion:** the `motion` package (Framer Motion). One orchestrated landing experience > scattered effects: staggered hero reveal, then a scroll-driven pipeline walkthrough where each stage "assembles" (a page sheet slides in → gets sliced into chunk strips → strips fan into a vector grid → the agent loop draws itself as a circular path with retrieve/grade/rewrite stops → an answer streams in letter-by-letter). In the app: tokens appear without per-token animation (just append), but step-timeline entries slide-stamp in, and the grounding badge stamps with a tiny rotate+scale spring.
- **Spanish-friendly microcopy**: UI copy in English (portfolio reach) but no idioms that break for ES speakers.

**Backend protocol contract (the source of truth for `lib/` types):**
- REST: `POST /sessions` → `{id,...}`; `GET /sessions/{id}` → `{..., documents: Document[]}` (410 `SESSION_EXPIRED` / 404 `SESSION_NOT_FOUND` envelopes → drop the stored id, create fresh); `POST /sessions/{id}/documents` multipart → 202 Document; `GET /sessions/{id}/documents` → Document[]; `DELETE /sessions/{id}/documents/{docId}`; `GET /sessions/{id}/messages` → Message[] (`grounded` nullable on ai rows); `DELETE /sessions/{id}`.
- `Document = { id, filename, mime_type, size_bytes, page_count: number|null, chunk_count, status: "pending"|"processing"|"ready"|"failed", stage: "parsing"|"ocr"|"embedding"|"saving"|null, progress: number, error_code: string|null, error_message: string|null, created_at }`. Poll the list every 1.5s while any doc is non-terminal.
- Errors: `{ error: { code, message, request_id } }` — codes seen by the UI: SESSION_NOT_FOUND, SESSION_EXPIRED, UNSUPPORTED_FILE_TYPE, FILE_TOO_LARGE, PARSE_FAILED, SESSION_DOCUMENT_LIMIT, INGESTION_BUSY, GUARDRAIL_BLOCKED, RATE_LIMITED. Row-level codes are lowercase (`parse_failed`, `interrupted`, `page_limit_exceeded`).
- Chat SSE: `POST /chat {question, session_id}` → `text/event-stream`, lines `data: <json>` ending `data: [DONE]`. Union:
  `{session_id: string}` | `{step: "retrieve"|"grade_documents"|"rewrite_query", detail: string, is_relevant?: boolean, query?: string, retry?: number, new_question?: string}` | `{sources: Source[]}` | `{token: string}` | `{grounding: {verdict: "grounded"|"ungrounded"|"unverified"}}` | `{error: {code: string, message: string}}`.
  `Source = { document_id, filename, score, chunks: [{chunk_id, chunk_text, score}] }`. A 400 GUARDRAIL_BLOCKED arrives as a plain JSON error response (not SSE) — handle non-200 before reading the stream.
- Upload limits worth surfacing in UI copy: 10 MB, types .pdf/.docx/.xlsx/.png/.jpg/.jpeg/.webp/.txt/.md, 20 docs/session.

**JS deps:** `motion`, `react-markdown`, `remark-gfm`, `remark-math`, `rehype-katex`, `katex`, `lucide-react`. No shadcn (hand-rolled, small component count). No `eventsource-parser` (the SSE format here is simple `data:` lines — a ~30-line parser keeps deps lean; implementer may add the lib if edge cases demand).

**This is plan 6 of 7.** Backend: 119 tests green; run it locally during development (`docker start challenge_postgres && uv run fastapi dev app/main.py`). Browser verification uses the Playwright MCP tools from the controller side; implementers verify with `npm run build` + `npx tsc --noEmit` + curl-level checks and hand the controller a running stack.

---

### Task 1: Scaffold + lib layer + backend CORS

**Files:** create `web/` via scaffold; `web/lib/api.ts`, `web/lib/sse.ts`, `web/lib/session.ts`, `web/lib/types.ts`; theme in `web/app/globals.css` + `web/app/layout.tsx`; modify `app/shared/config.py`, `app/main.py`, `.env.example`.

- [ ] Scaffold: from repo root, `npx create-next-app@latest web --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm` (accept defaults otherwise; if prompted about Turbopack accept). Remove boilerplate page content. Add `.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000` and commit a `web/.env.example` mirroring it.
- [ ] Fonts + theme: `next/font/google` for Fraunces, IBM Plex Mono, IBM Plex Sans wired as CSS variables in `layout.tsx`; `globals.css` defines the palette tokens (`--paper`, `--ink`, `--rule`, `--accent`, `--card`), the grain overlay utility, stamped-chip and offset-shadow utilities (Tailwind v4 `@theme` / plain CSS custom properties — match whatever the scaffold generated).
- [ ] `web/lib/types.ts`: the full contract above as TS types (Document, Source, ChatEvent discriminated union, ApiError envelope).
- [ ] `web/lib/api.ts`: `createSession()`, `getSession(id)`, `listDocuments(id)`, `uploadDocument(id, file)`, `deleteDocument(id, docId)`, `getMessages(id)`, `deleteSession(id)` — all returning typed results; non-2xx parsed into a thrown `ApiError {code, message, status}`.
- [ ] `web/lib/sse.ts`: `streamChat(question, sessionId, callbacks)` — POST via fetch, non-200 → parse envelope and throw ApiError BEFORE streaming; otherwise read body via ReadableStream, split on newlines, parse `data: ` lines, dispatch through `onEvent(event: ChatEvent)`, resolve on `[DONE]` or stream end; abortable via AbortController.
- [ ] `web/lib/session.ts`: `getOrCreateSession()` — localStorage key `aypdf.session`, validate via `getSession`, on 404/410 (or network parse of those codes) create fresh and overwrite. Pure functions; React hooks live in components.
- [ ] Backend CORS: `app/shared/config.py` gains `FRONTEND_ORIGIN: str = "http://localhost:3000"`; `app/main.py` CORS `allow_origins=list({settings.FRONTEND_ORIGIN, "http://localhost:3000"})` (set-dedup), keep `expose_headers=["X-Request-ID"]`, methods/headers as-is. `.env.example` documents FRONTEND_ORIGIN. Run `uv run pytest -q` (must stay green — CORS change is config-only) + `uv run ruff check .`.
- [ ] Gates: `cd web && npm run build` succeeds; `npx tsc --noEmit` clean; `npm run lint` clean. Commit: `feat(web): scaffold Next.js app - paper-and-ink theme, typed API/SSE layer; backend CORS origin setting`.

### Task 2: The app page (`/chat`)

**Files:** `web/app/chat/page.tsx` (+ client components under `web/components/chat/`): `UploadZone`, `DocumentList`, `DocumentRow` (status chip + stage/progress + error message), `ChatPanel`, `MessageBubble` (react-markdown + remark-gfm + remark-math/rehype-katex; KaTeX CSS imported), `AgentStepsTimeline`, `SourcesPanel`, `GroundingBadge`, `ServerWakingNotice`.

- [ ] Layout: left rail (320px) = session block (id, "New session" action) + UploadZone + DocumentList; main column = chat thread + composer. Mobile: rail collapses to a top sheet. Paper aesthetic per the committed direction — ruled lines, stamped chips (`READY` in ink, `FAILED` in vermilion, `PROCESSING…` with the stage in mono), offset-shadow cards.
- [ ] Upload: drag-drop + file picker; client-side type/size pre-check mirroring backend limits with honest copy; per-file lifecycle from the polling loop (poll `listDocuments` every 1.5s while any doc non-terminal, stop when all terminal); failed docs show `error_message` and a retry-as-new-upload affordance; delete per row.
- [ ] Chat: history loads from `getMessages` on mount (render `grounded` badges from rows); composer disabled while streaming; the live turn renders: step timeline entries as they arrive (retrieve/grade/rewrite with detail text, grade shows ✓/✗, rewrite shows the new query), sources as a collapsible annotated-footnote block (filename + score% + first chunk preview), streamed tokens appended into the markdown bubble (re-render throttled ~30ms), grounding badge stamped at the end (`✓ verified against your documents` / vermilion `⚠ not fully supported` / muted `unverified`), SSE `{error}` events as an inline system note. ApiError from non-200 (GUARDRAIL_BLOCKED, RATE_LIMITED, SESSION_EXPIRED) rendered as a distinct "stamped notice" — for SESSION_EXPIRED also rotate the session.
- [ ] Cold start: on mount ping `${API}/health` with a 3s timeout; while unreachable show ServerWakingNotice ("free hosting wakes up in ~30s") and retry with backoff.
- [ ] Gates: `npm run build`, `tsc --noEmit`, lint; manual flow against the live local backend (implementer: curl-level + build; controller does the browser pass in Task 4). Commit: `feat(web): chat app - upload with live status, streaming chat with agent timeline, sources, grounding badge`.

### Task 3: The landing page (`/`)

**Files:** `web/app/page.tsx` + `web/components/landing/`: `Hero`, `PipelineWalkthrough` (the scroll-driven centerpiece), `AgentLoopDiagram`, `TechFootnotes`, `Cta`.

- [ ] Hero: Fraunces display headline (e.g. "Ask your PDFs. Get cited answers."), one-line subhead, two CTAs ("Open the app" → /chat, "How it works" → scroll). Staggered reveal on load; a floating "specimen" paper card with a mock cited answer.
- [ ] PipelineWalkthrough: scroll-driven (`useScroll` + `useTransform`, sticky viewport section) six stages with mono step labels (01 UPLOAD → 02 PARSE/OCR → 03 CHUNK → 04 EMBED → 05 AGENT LOOP → 06 ANSWER): page sheet slides in; OCR scan-line sweeps it; sheet slices into chunk strips; strips fan into a dot-grid (vectors); the agent loop as an SVG circular path that draws itself with three stops (retrieve → grade → rewrite, with a vermilion retry arc); final stage streams a short answer with a citation chip and a stamped `✓ grounded` badge. Each stage also gets a one-sentence plain-language caption + a mono technical footnote (e.g. `text-embedding-3-small · 1536d · pgvector`). MUST degrade gracefully: `prefers-reduced-motion` → static stacked figures.
- [ ] TechFootnotes strip: honest small-print stack badges (FastAPI · LangGraph · pgvector · gpt-4o-mini vision OCR · Langfuse) in mono with dotted rules. Cta: closing section repeating the app link.
- [ ] Landing makes zero API calls; fully static/prerendered. Gates: build/tsc/lint + Lighthouse-sane (no layout shift from font loading — use `display: swap` + size-adjust via next/font defaults). Commit: `feat(web): animated landing page - scroll-driven pipeline walkthrough`.

### Task 4: Browser verification + polish (controller-led)

- [ ] Controller starts the stack (Postgres + API on :8000, `npm run dev` on :3000) and drives Playwright MCP: landing renders + scroll animation works; /chat full flow — create session, upload `tests/fixtures/sample.pdf`, watch status chips to READY, ask "What does the Calvin cycle do?", observe steps timeline + sources + streamed answer + grounded badge; upload a `.exe` → stamped 415 notice; screenshot key states.
- [ ] Fix whatever the browser pass surfaces (dispatch fix subagents as needed). Final: `npm run build` + backend suite still green. Commit: `fix(web): browser-pass polish`.

## Verification (end of Phase 6)

1. `cd web && npm run build && npx tsc --noEmit && npm run lint` clean; backend `uv run pytest -q` green.
2. The Task-4 browser flow, screenshotted.
3. SSE tokens render incrementally in the real browser (not buffered).

## Out of scope

Vercel project creation + production env wiring + README/docs (Phase 7). Auth, i18n, dark mode (never — the paper aesthetic is light by design).
