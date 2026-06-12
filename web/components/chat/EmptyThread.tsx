"use client";

/** Hand-drawn paper sheet with a folded corner, ruled lines, vermilion seal */
function PaperSheetIllustration() {
  return (
    <svg
      width="120"
      height="148"
      viewBox="0 0 120 148"
      fill="none"
      aria-hidden
      className="mx-auto"
      style={{ transform: "rotate(-2deg)" }}
    >
      {/* Back sheet, offset like the card shadows */}
      <rect x="14" y="14" width="92" height="120" fill="rgba(28,24,20,0.10)" />
      {/* Front sheet with a folded top-right corner */}
      <path
        d="M10 10 H 84 L 102 28 V 130 H 10 Z"
        fill="var(--card)"
        stroke="var(--ink)"
        strokeWidth="1.5"
      />
      <path
        d="M84 10 V 28 H 102 Z"
        fill="var(--rule)"
        stroke="var(--ink)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* Ruled lines */}
      {[44, 58, 72, 86, 100].map((y) => (
        <line
          key={y}
          x1="22"
          y1={y}
          x2={y === 100 ? 64 : 90}
          y2={y}
          stroke="var(--rule)"
          strokeWidth="1.5"
        />
      ))}
      {/* Vermilion seal */}
      <circle
        cx="82"
        cy="108"
        r="11"
        stroke="var(--accent)"
        strokeWidth="1.5"
        fill="none"
        transform="rotate(-8 82 108)"
      />
      <text
        x="82"
        y="111"
        textAnchor="middle"
        fontSize="7"
        fill="var(--accent)"
        fontFamily="var(--font-ibm-plex-mono), monospace"
        letterSpacing="0.5"
        transform="rotate(-8 82 108)"
      >
        RAG
      </text>
    </svg>
  );
}

const SAMPLE_QUESTIONS = [
  "Summarize the key points of this document.",
  "What are the main conclusions?",
  "Explain the hardest concept in here simply.",
];

/**
 * The empty session moment. Two variants: no documents yet (invite the first
 * upload) or documents ready but no questions asked (offer starters).
 */
export default function EmptyThread({
  hasReadyDocs,
  onRequestUpload,
  onPickSample,
}: {
  hasReadyDocs: boolean;
  onRequestUpload: () => void;
  onPickSample: (question: string) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
      <PaperSheetIllustration />

      {hasReadyDocs ? (
        <>
          <h2
            className="font-display mt-5 text-2xl leading-snug"
            style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 1" }}
          >
            The desk is set. Ask away.
          </h2>
          <p className="mt-2 max-w-sm font-body text-sm leading-relaxed text-ink/60">
            Your documents are indexed. Every answer cites the passages it came
            from — and gets stamped if it holds up.
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            {SAMPLE_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => onPickSample(q)}
                className="card-paper px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-ink/70 transition-shadow hover:text-accent hover:shadow-ink-md"
              >
                {q}
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <h2
            className="font-display mt-5 text-2xl leading-snug"
            style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 1" }}
          >
            Drop your first document
          </h2>
          <p className="mt-2 max-w-sm font-body text-sm leading-relaxed text-ink/60">
            PDFs, scans, spreadsheets, plain notes — the agent reads them,
            indexes every passage, and answers with citations.
          </p>
          <button
            type="button"
            onClick={onRequestUpload}
            className="card-paper mt-5 px-5 py-2 font-body text-sm font-semibold transition-shadow hover:shadow-ink-md"
            style={{ background: "var(--ink)", color: "var(--paper)" }}
          >
            Choose a file →
          </button>
          <p className="mt-3 font-mono text-[9px] uppercase tracking-[0.12em] text-ink/35">
            or drag it onto the upload panel
          </p>
        </>
      )}
    </div>
  );
}
