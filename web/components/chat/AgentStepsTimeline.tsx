"use client";

import { motion, useReducedMotion } from "motion/react";
import type { StepEvent } from "@/lib/types";

interface RenderedStep {
  mark: string;
  label: string;
  detail: string;
  accent: boolean;
}

function renderStep(step: StepEvent): RenderedStep {
  switch (step.step) {
    case "retrieve":
      return {
        mark: "→",
        label: "RETRIEVE",
        detail: step.detail,
        accent: false,
      };
    case "grade_documents":
      return step.is_relevant
        ? { mark: "✓", label: "RELEVANT", detail: step.detail, accent: false }
        : {
            mark: "✗",
            label: "NOT RELEVANT",
            detail: step.detail,
            accent: true,
          };
    case "rewrite_query":
      return {
        mark: "↻",
        label: "REWRITE",
        detail: step.new_question ? `"${step.new_question}"` : step.detail,
        accent: true,
      };
  }
}

/**
 * The agent's working trail — retrieve / grade / rewrite entries that
 * slide-stamp in as the loop runs. Mono, ledger-like, numbered.
 */
export default function AgentStepsTimeline({
  steps,
  animate = false,
}: {
  steps: StepEvent[];
  /** true while streaming (entries animate in); false for collapsed history */
  animate?: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const shouldAnimate = animate && !reducedMotion;

  if (steps.length === 0) return null;

  return (
    <ol className="space-y-1" aria-label="Agent steps">
      {steps.map((step, i) => {
        const r = renderStep(step);
        return (
          <motion.li
            key={i}
            initial={shouldAnimate ? { opacity: 0, x: -10, rotate: -1 } : false}
            animate={{ opacity: 1, x: 0, rotate: 0 }}
            transition={{ type: "spring", stiffness: 460, damping: 30 }}
            className="flex items-baseline gap-2 font-mono text-[11px] leading-relaxed"
          >
            <span className="text-ink/35 tabular-nums">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span
              className={
                r.accent ? "shrink-0 text-accent" : "shrink-0 text-ink/70"
              }
              aria-hidden
            >
              {r.mark}
            </span>
            <span
              className={`shrink-0 font-medium uppercase tracking-[0.1em] ${
                r.accent ? "text-accent" : "text-ink"
              }`}
            >
              {r.label}
            </span>
            <span className="min-w-0 break-words text-ink/55">{r.detail}</span>
          </motion.li>
        );
      })}
    </ol>
  );
}
