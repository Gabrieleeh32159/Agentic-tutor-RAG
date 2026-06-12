"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Source, StepEvent } from "@/lib/types";
import AgentStepsTimeline from "./AgentStepsTimeline";
import SourcesPanel from "./SourcesPanel";
import GroundingBadge, { type GroundingVerdict } from "./GroundingBadge";

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS}>
      {content}
    </ReactMarkdown>
  );
});

/**
 * One row of the Q&A ledger.
 *
 * Questions are set in Fraunces like pull-quotes; answers are paper cards
 * with the agent trail, footnote sources, and the grounding stamp. The live
 * (streaming) answer carries the vermilion editor's margin-line.
 */
export default function MessageBubble({
  role,
  content,
  index,
  grounded,
  sources,
  steps,
  streaming = false,
  animateBadge = false,
}: {
  role: "human" | "ai";
  content: string;
  /** 1-based Q/A pair number for the gutter marker */
  index: number;
  grounded?: GroundingVerdict | null;
  sources?: Source[];
  steps?: StepEvent[];
  streaming?: boolean;
  /** stamp the grounding badge with the spring animation (live turn only) */
  animateBadge?: boolean;
}) {
  const marker = `${role === "human" ? "Q" : "A"}.${String(index).padStart(2, "0")}`;

  if (role === "human") {
    return (
      <div className="flex gap-3">
        <span className="w-10 shrink-0 pt-1.5 text-right font-mono text-[10px] tabular-nums text-ink/40">
          {marker}
        </span>
        <p
          className="font-display min-w-0 flex-1 text-lg leading-snug text-ink"
          style={{ fontVariationSettings: "'opsz' 32, 'SOFT' 60, 'WONK' 0" }}
        >
          {content}
        </p>
      </div>
    );
  }

  const hasSteps = (steps?.length ?? 0) > 0;
  const hasSources = (sources?.length ?? 0) > 0;
  const waitingForFirstToken = streaming && content.length === 0;

  return (
    <div className="flex gap-3">
      <span className="w-10 shrink-0 pt-3 text-right font-mono text-[10px] tabular-nums text-accent/70">
        {marker}
      </span>

      <div className="card-paper min-w-0 flex-1 space-y-3 p-3.5 sm:p-4">
        {/* Live agent trail (always open while streaming) */}
        {streaming && hasSteps && (
          <div className="border-b border-rule pb-2.5">
            <p className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/45">
              Agent trail
            </p>
            <AgentStepsTimeline steps={steps!} animate />
          </div>
        )}

        {/* Collapsed agent trail on finished turns */}
        {!streaming && hasSteps && (
          <details className="group border-b border-rule pb-2.5">
            <summary className="cursor-pointer list-none font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/45 hover:text-accent">
              <span aria-hidden className="mr-1 inline-block transition-transform group-open:rotate-90">
                ▸
              </span>
              Agent trail · {steps!.length} step{steps!.length === 1 ? "" : "s"}
            </summary>
            <div className="mt-2">
              <AgentStepsTimeline steps={steps!} />
            </div>
          </details>
        )}

        {/* Answer body */}
        {waitingForFirstToken ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.15em] text-ink/40">
            Composing…
          </p>
        ) : (
          <div
            className={`md-body font-body text-ink/90 ${
              streaming ? "margin-line stream-caret" : ""
            }`}
          >
            <Markdown content={content} />
          </div>
        )}

        {/* Footnote sources */}
        {hasSources && <SourcesPanel sources={sources!} />}

        {/* Grounding stamp */}
        {grounded && (
          <div className="flex justify-end pt-0.5">
            <GroundingBadge verdict={grounded} animate={animateBadge} />
          </div>
        )}
      </div>
    </div>
  );
}
