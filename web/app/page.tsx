import Link from "next/link";

/**
 * Landing page placeholder.
 * Task 3 replaces this with the full animated landing experience.
 */
export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center min-h-screen px-6">
      {/* Specimen card */}
      <div
        className="card-paper w-full max-w-lg p-10 space-y-6"
        style={{ transform: "rotate(-0.4deg)" }}
      >
        {/* Vermilion margin line */}
        <div className="margin-line">
          <h1
            className="font-display text-4xl leading-tight tracking-tight"
            style={{ fontVariationSettings: "'opsz' 72, 'SOFT' 100, 'WONK' 1" }}
          >
            Ask your PDFs.
          </h1>
          <p
            className="font-display text-2xl leading-snug mt-1"
            style={{
              fontVariationSettings: "'opsz' 72, 'SOFT' 100, 'WONK' 0",
              color: "var(--accent)",
            }}
          >
            Get cited answers.
          </p>
        </div>

        {/* Hairline rule */}
        <hr style={{ borderColor: "var(--rule)" }} />

        <p className="font-body text-sm leading-relaxed" style={{ color: "color-mix(in srgb, var(--ink) 70%, transparent)" }}>
          Upload your documents and ask questions. An agentic RAG pipeline
          retrieves, grades, and grounds every answer in your own files.
        </p>

        <div className="flex items-center gap-4 pt-2">
          <Link
            href="/chat"
            className="inline-block card-paper px-5 py-2 font-body text-sm font-semibold transition-shadow hover:shadow-ink-md"
            style={{ background: "var(--ink)", color: "var(--paper)" }}
          >
            Open the app →
          </Link>

          <span
            className="chip"
            style={{ transform: "rotate(1deg)" }}
          >
            Beta
          </span>
        </div>
      </div>

      {/* Tech footnote */}
      <p
        className="mt-8 font-mono text-xs"
        style={{ color: "color-mix(in srgb, var(--ink) 40%, transparent)" }}
      >
        FastAPI · LangGraph · pgvector · gpt-4o-mini · Next.js
      </p>
    </main>
  );
}
