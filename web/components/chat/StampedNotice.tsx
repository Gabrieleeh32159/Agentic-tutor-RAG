"use client";

import { motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";

/**
 * An official-looking stamped notice — used for guardrail blocks, rate limits,
 * expired sessions, and other request-level refusals. Vermilion double border,
 * mono letterhead, slight tilt: bureaucracy on paper.
 */
export default function StampedNotice({
  title,
  message,
  onDismiss,
}: {
  /** Mono uppercase letterhead, e.g. "NOTICE — RATE LIMITED" */
  title: string;
  message: string;
  onDismiss?: () => void;
}) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, scale: 1.12, rotate: -2.5 }}
      animate={{ opacity: 1, scale: 1, rotate: -0.6 }}
      transition={{ type: "spring", stiffness: 380, damping: 24 }}
      role="alert"
      className="relative mx-auto w-full max-w-md border-2 border-accent bg-card p-3 shadow-ink"
    >
      {/* Inner hairline — double-rule letterhead frame */}
      <div className="pointer-events-none absolute inset-1 border border-accent/40" />

      <div className="relative flex items-start justify-between gap-3 px-1 py-0.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-accent">
            {title}
          </p>
          <p className="mt-1.5 font-body text-sm leading-relaxed text-ink/80">
            {message}
          </p>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss notice"
            className="shrink-0 p-0.5 text-ink/50 hover:text-accent"
          >
            <X size={14} strokeWidth={2} aria-hidden />
          </button>
        )}
      </div>
    </motion.div>
  );
}
