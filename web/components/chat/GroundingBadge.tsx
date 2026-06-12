"use client";

import { motion, useReducedMotion } from "motion/react";

export type GroundingVerdict = "grounded" | "ungrounded" | "unverified";

const VERDICT_COPY: Record<GroundingVerdict, string> = {
  grounded: "✓ verified against your documents",
  ungrounded: "⚠ not fully supported by your documents",
  unverified: "unverified",
};

/**
 * Stamped grounding verdict — slams in with a small spring rotate, like an
 * inspector's mark at the bottom of the page.
 */
export default function GroundingBadge({
  verdict,
  animate = false,
}: {
  verdict: GroundingVerdict;
  /** true for the live turn (stamp animation); false for history rows */
  animate?: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const shouldAnimate = animate && !reducedMotion;

  const tone =
    verdict === "grounded"
      ? "border-ink text-ink"
      : verdict === "ungrounded"
        ? "border-accent text-accent"
        : "border-rule text-ink/45";

  return (
    <motion.span
      initial={
        shouldAnimate ? { opacity: 0, scale: 1.45, rotate: -7 } : false
      }
      animate={{ opacity: 1, scale: 1, rotate: -1.2 }}
      transition={{ type: "spring", stiffness: 420, damping: 22 }}
      className={`inline-block border bg-transparent px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.12em] ${tone}`}
      style={{ transformOrigin: "center" }}
      data-verdict={verdict}
    >
      {VERDICT_COPY[verdict]}
    </motion.span>
  );
}
