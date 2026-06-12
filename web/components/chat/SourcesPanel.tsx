"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Source } from "@/lib/types";

const SUPERSCRIPTS = ["¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"];

function sup(i: number): string {
  return SUPERSCRIPTS[i] ?? `(${i + 1})`;
}

/**
 * Footnote-style source annotations under an answer: superscript number,
 * filename, match score, and an expandable chunk preview — like the
 * references block at the bottom of an article page.
 */
export default function SourcesPanel({ sources }: { sources: Source[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (sources.length === 0) return null;

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="border-t border-rule pt-2.5">
      <p className="font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/45">
        Sources
      </p>
      <ol className="mt-1.5 space-y-1">
        {sources.map((source, i) => {
          const isOpen = expanded.has(source.document_id);
          const preview = source.chunks[0]?.chunk_text ?? "";
          return (
            <li key={source.document_id}>
              <button
                type="button"
                onClick={() => toggle(source.document_id)}
                aria-expanded={isOpen}
                className="group flex w-full items-baseline gap-1.5 text-left font-mono text-[11px] leading-relaxed"
              >
                <span className="text-accent" aria-hidden>
                  {sup(i)}
                </span>
                <span className="min-w-0 truncate text-ink underline decoration-dotted decoration-ink/30 underline-offset-2 group-hover:decoration-accent">
                  {source.filename}
                </span>
                <span className="shrink-0 tabular-nums text-ink/45">
                  {Math.round(source.score * 100)}%
                </span>
                <span className="shrink-0 text-ink/40" aria-hidden>
                  {isOpen ? (
                    <ChevronDown size={11} strokeWidth={2} />
                  ) : (
                    <ChevronRight size={11} strokeWidth={2} />
                  )}
                </span>
              </button>

              {isOpen && preview && (
                <blockquote className="mt-1 mb-1.5 ml-4 border-l-2 border-rule pl-2.5 font-body text-xs leading-relaxed text-ink/65">
                  {preview.length > 420 ? `${preview.slice(0, 420)}…` : preview}
                  {source.chunks.length > 1 && (
                    <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-[0.1em] text-ink/40">
                      +{source.chunks.length - 1} more passage
                      {source.chunks.length > 2 ? "s" : ""} matched
                    </span>
                  )}
                </blockquote>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
