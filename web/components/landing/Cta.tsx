"use client";

import Link from "next/link";
import { motion, MotionConfig } from "motion/react";

/** Closing paper section: the app link again, plus the honesty stamp. */
export default function Cta() {
  return (
    <MotionConfig reducedMotion="user">
      <section className="relative overflow-hidden px-6 py-24">
        {/* Ruled paper backdrop */}
        <div className="ruled-bg absolute inset-0 -z-10 opacity-60" aria-hidden />

        <div
          className="card-paper-md mx-auto max-w-2xl px-8 py-12 text-center sm:px-12"
          style={{ transform: "rotate(-0.3deg)" }}
        >
          <h2
            className="font-display text-3xl leading-tight tracking-tight sm:text-4xl"
            style={{ fontVariationSettings: "'opsz' 96, 'SOFT' 100, 'WONK' 1" }}
          >
            Bring a document.
            <br />
            Leave with <span style={{ color: "var(--accent)" }}>cited</span>{" "}
            answers.
          </h2>

          <p className="mx-auto mt-4 max-w-md font-body text-sm leading-relaxed text-ink/65">
            Upload something you are actually studying and ask the hard
            question. You will see the agent retrieve, grade, and rewrite — and
            the verdict stamped on every answer.
          </p>

          <div className="mt-8 flex flex-col items-center gap-5">
            <Link
              href="/chat"
              className="card-paper inline-block px-7 py-3 font-body text-sm font-semibold transition-shadow hover:shadow-ink-md"
              style={{ background: "var(--ink)", color: "var(--paper)" }}
            >
              Open the app →
            </Link>

            <motion.span
              initial={{ opacity: 0, scale: 1.5, rotate: -7 }}
              whileInView={{ opacity: 1, scale: 1, rotate: 1 }}
              viewport={{ once: true, amount: 0.8 }}
              transition={{ type: "spring", stiffness: 380, damping: 22 }}
              className="chip chip--accent"
            >
              No sign-up · sessions expire in 24h
            </motion.span>

            <p className="font-mono text-[10px] text-ink/40">
              Free-tier hosting — the API may take ~30s to wake up.
            </p>
          </div>
        </div>

        <footer className="mx-auto mt-14 flex max-w-2xl items-baseline justify-center gap-2 font-mono text-[10px] text-ink/35">
          <span>ask·your·pdfs</span>
          <span aria-hidden>·</span>
          <span>an agentic-RAG portfolio build</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">2026</span>
        </footer>
      </section>
    </MotionConfig>
  );
}
