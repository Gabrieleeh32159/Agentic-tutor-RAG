"use client";

import Link from "next/link";
import { motion, MotionConfig, type Variants } from "motion/react";

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.09, delayChildren: 0.1 } },
};

const rise: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
  },
};

/** The floating specimen: a mock cited, stamped answer card. */
function SpecimenCard() {
  return (
    <motion.div
      animate={{ y: [0, -8, 0] }}
      transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
    >
      <div
        className="card-paper-md relative w-full max-w-sm p-5"
        style={{ transform: "rotate(1.4deg)" }}
      >
        <div className="flex items-baseline justify-between gap-3">
          <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink/50">
            Q · What does the Calvin cycle do?
          </p>
          <span className="font-mono text-[9px] tabular-nums text-ink/35">
            specimen
          </span>
        </div>
        <div className="my-3 h-px bg-rule" />
        <p className="margin-line font-body text-sm leading-relaxed text-ink/90">
          It uses the ATP and NADPH from the light reactions to fix CO₂ into
          glucose — the sugar-building half of photosynthesis.
          <sup className="text-accent">1</sup>
        </p>
        <p className="mt-3 font-mono text-[10px] text-ink/55">
          <span className="text-accent" aria-hidden>
            ¹
          </span>{" "}
          biology-notes.pdf · <span className="tabular-nums">92%</span> match
        </p>
        <span
          className="chip mt-3 inline-block"
          style={{ transform: "rotate(-1.5deg)" }}
        >
          ✓ grounded
        </span>
      </div>
    </motion.div>
  );
}

export default function Hero() {
  return (
    <MotionConfig reducedMotion="user">
      <header className="relative overflow-hidden">
        {/* Masthead */}
        <div className="mx-auto flex w-full max-w-6xl items-baseline justify-between px-6 pt-6">
          <p className="font-mono text-[11px] font-medium uppercase tracking-[0.22em]">
            Ask·your·PDFs
          </p>
          <Link
            href="/chat"
            className="dotted-link font-mono text-[11px] uppercase tracking-[0.12em]"
          >
            Open the app →
          </Link>
        </div>

        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="mx-auto grid w-full max-w-6xl items-center gap-12 px-6 pb-20 pt-16 sm:pt-24 lg:grid-cols-[1.15fr_1fr] lg:gap-8"
        >
          {/* Left: headline + CTAs */}
          <div>
            <motion.span
              variants={rise}
              className="chip inline-block"
              style={{ rotate: "-1deg" }}
            >
              Agentic RAG · portfolio build
            </motion.span>

            <motion.h1
              variants={rise}
              className="font-display mt-5 text-5xl leading-[1.05] tracking-tight sm:text-6xl lg:text-7xl"
              style={{ fontVariationSettings: "'opsz' 144, 'SOFT' 100, 'WONK' 1" }}
            >
              Ask your PDFs.
              <br />
              <span style={{ color: "var(--accent)" }}>Get cited answers.</span>
            </motion.h1>

            <motion.p
              variants={rise}
              className="mt-6 max-w-md font-body text-base leading-relaxed text-ink/70"
            >
              Drop in your documents and ask questions. An agent retrieves the
              right passages, grades its own evidence, and answers with
              citations — every claim checked against your files.
            </motion.p>

            <motion.div
              variants={rise}
              className="mt-8 flex flex-wrap items-center gap-5"
            >
              <Link
                href="/chat"
                className="card-paper inline-block px-6 py-2.5 font-body text-sm font-semibold transition-shadow hover:shadow-ink-md"
                style={{ background: "var(--ink)", color: "var(--paper)" }}
              >
                Open the app →
              </Link>
              <a
                href="#how-it-works"
                className="dotted-link font-mono text-xs uppercase tracking-[0.14em]"
              >
                How it works ↓
              </a>
            </motion.div>

            <motion.p
              variants={rise}
              className="mt-8 font-mono text-[10px] uppercase tracking-[0.14em] text-ink/40"
            >
              No sign-up · PDFs, scans, spreadsheets &amp; notes · up to 10 MB
            </motion.p>
          </div>

          {/* Right: floating specimen answer */}
          <motion.div
            variants={rise}
            className="relative flex justify-center lg:justify-end"
          >
            {/* Ruled backing sheet */}
            <div
              className="ruled-bg absolute -inset-x-4 -inset-y-6 -z-10 hidden border border-rule sm:block"
              style={{ transform: "rotate(-0.6deg)" }}
              aria-hidden
            />
            <SpecimenCard />
          </motion.div>
        </motion.div>

        {/* Scroll cue */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.2, duration: 0.6 }}
          className="pb-6 text-center"
          aria-hidden
        >
          <motion.span
            animate={{ y: [0, 5, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            className="inline-block font-mono text-[10px] uppercase tracking-[0.3em] text-ink/35"
          >
            scroll ↓
          </motion.span>
        </motion.div>
      </header>
    </MotionConfig>
  );
}
