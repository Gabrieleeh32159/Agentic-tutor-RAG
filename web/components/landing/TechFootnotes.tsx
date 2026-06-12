const STACK: ReadonlyArray<readonly [string, string]> = [
  ["FastAPI", "async Python API"],
  ["LangGraph", "agent orchestration"],
  ["pgvector", "vector search in Postgres"],
  ["OpenAI", "embeddings · chat · vision OCR"],
  ["Langfuse", "tracing every run"],
];

/**
 * Colophon strip — honest small print about what actually runs underneath,
 * set like the footnotes block of an article.
 */
export default function TechFootnotes() {
  return (
    <section
      className="border-y border-rule"
      style={{ background: "color-mix(in srgb, var(--card) 60%, transparent)" }}
      aria-label="Technology stack"
    >
      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className="font-mono text-[10px] font-medium uppercase tracking-[0.28em] text-ink/50">
          Colophon · the stack
        </p>
        <ul className="mt-5 grid gap-x-10 gap-y-3 sm:grid-cols-2 lg:grid-cols-5">
          {STACK.map(([name, desc]) => (
            <li
              key={name}
              className="flex items-baseline gap-2 font-mono text-[11px] leading-relaxed"
            >
              <span className="shrink-0 font-medium text-ink">{name}</span>
              <span
                className="min-w-4 flex-1 border-b border-dotted border-ink/30"
                aria-hidden
              />
              <span className="text-right text-ink/50">{desc}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
