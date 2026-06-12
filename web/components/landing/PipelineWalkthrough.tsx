"use client";

import {
  useRef,
  useState,
  useSyncExternalStore,
  type ComponentType,
} from "react";
import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react";
import AgentLoopDiagram from "./AgentLoopDiagram";

/* ─── Stage definitions ──────────────────────────────────────────────────── */

type FigProps = { t: MotionValue<number> };

interface Stage {
  num: string;
  label: string;
  caption: string;
  footnote: string;
  Figure: ComponentType<FigProps>;
}

/* ─── 01 · UPLOAD — a paper sheet drops into the dashed drop zone ────────── */

function SheetSvg({ width = 140 }: { width?: number }) {
  const height = Math.round((width / 120) * 148);
  return (
    <svg width={width} height={height} viewBox="0 0 120 148" fill="none" aria-hidden>
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
        PDF
      </text>
    </svg>
  );
}

function UploadFigure({ t }: FigProps) {
  const y = useTransform(t, [0, 0.55], [110, 0]);
  const rotate = useTransform(t, [0, 0.55], [-9, -2]);
  const opacity = useTransform(t, [0, 0.3], [0, 1]);
  const chipOpacity = useTransform(t, [0.62, 0.82], [0, 1]);
  const chipY = useTransform(t, [0.62, 0.82], [8, 0]);

  return (
    <div className="relative h-[270px] w-[240px]">
      {/* Dashed drop target */}
      <div className="absolute inset-x-0 top-0 h-[228px] border border-dashed border-ink/30">
        <span className="absolute left-2 top-1.5 font-mono text-[8px] uppercase tracking-[0.18em] text-ink/35">
          drop zone
        </span>
      </div>
      <motion.div
        style={{ y, rotate, opacity }}
        className="absolute left-1/2 top-6 -ml-[70px]"
      >
        <SheetSvg width={140} />
      </motion.div>
      <motion.div
        style={{ opacity: chipOpacity, y: chipY }}
        className="absolute inset-x-0 bottom-0 flex justify-center"
      >
        <span className="chip" style={{ transform: "rotate(-1deg)" }}>
          notes.pdf · 2.1 MB
        </span>
      </motion.div>
    </div>
  );
}

/* ─── 02 · PARSE/OCR — a vermilion scan-line sweeps the sheet ────────────── */

const OCR_LINE_YS = [44, 58, 72, 86, 100, 114];

function OcrLine({ t, y, x2 }: FigProps & { y: number; x2: number }) {
  // Each line turns from faint rule to ink as the scan-line passes its height.
  const at = 0.08 + ((y - 36) / 92) * 0.72;
  const inkOpacity = useTransform(t, [at, at + 0.06], [0, 1]);
  return (
    <>
      <line x1={22} y1={y} x2={x2} y2={y} stroke="var(--rule)" strokeWidth={1.5} />
      <motion.line
        x1={22}
        y1={y}
        x2={x2}
        y2={y}
        stroke="var(--ink)"
        strokeWidth={1.5}
        style={{ opacity: inkOpacity }}
      />
    </>
  );
}

function OcrFigure({ t }: FigProps) {
  const scanY = useTransform(t, [0.08, 0.9], [28, 128]);
  const scanOpacity = useTransform(t, [0.02, 0.08, 0.88, 0.96], [0, 1, 1, 0]);
  const chipOpacity = useTransform(t, [0.88, 1], [0, 1]);

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={180} height={222} viewBox="0 0 120 148" fill="none" aria-hidden>
        <defs>
          <linearGradient id="ocr-glow" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity="0" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0.22" />
          </linearGradient>
        </defs>
        <rect x="14" y="14" width="92" height="128" fill="rgba(28,24,20,0.10)" />
        <path
          d="M10 10 H 84 L 102 28 V 138 H 10 Z"
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
        {OCR_LINE_YS.map((y, i) => (
          <OcrLine key={y} t={t} y={y} x2={i === OCR_LINE_YS.length - 1 ? 64 : 90} />
        ))}
        {/* Scan-line: faint glow trailing above a vermilion bar */}
        <motion.g style={{ y: scanY, opacity: scanOpacity }}>
          <rect x={11} y={-14} width={90} height={14} fill="url(#ocr-glow)" />
          <rect x={11} y={0} width={90} height={2.5} fill="var(--accent)" />
        </motion.g>
      </svg>
      <motion.span
        style={{ opacity: chipOpacity }}
        className="chip chip--accent"
      >
        text extracted
      </motion.span>
    </div>
  );
}

/* ─── 03 · CHUNK — the sheet slices into strips that separate ────────────── */

const STRIP_X = [-14, 10, -6, 12, -10];
const STRIP_R = [-1.6, 1.2, -0.8, 1.8, -1.2];

function ChunkStrip({ t, i }: FigProps & { i: number }) {
  const from = 0.05 + i * 0.06;
  const to = 0.5 + i * 0.06;
  const y = useTransform(t, [from, to], [-(i * 14), 0]);
  const x = useTransform(t, [from, to], [0, STRIP_X[i]]);
  const rotate = useTransform(t, [from, to], [0, STRIP_R[i]]);

  return (
    <motion.div
      style={{ top: i * 52, y, x, rotate }}
      className="card-paper absolute inset-x-0 flex h-[38px] items-center px-3"
    >
      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink/55">
        chunk {String(i + 1).padStart(2, "0")}
      </span>
      <span className="mx-3 h-px flex-1 bg-rule" />
      {i === 2 && (
        <span className="font-mono text-[9px] text-ink/40">300 chars</span>
      )}
      {/* Overlap band: the tail each strip shares with the next */}
      {i < 4 && (
        <span
          className="absolute inset-x-0 bottom-0 h-[5px]"
          style={{ background: "color-mix(in srgb, var(--accent) 15%, transparent)" }}
          aria-hidden
        />
      )}
    </motion.div>
  );
}

function ChunksFigure({ t }: FigProps) {
  const labelOpacity = useTransform(t, [0.78, 0.92], [0, 1]);
  return (
    <div className="relative h-[252px] w-[300px]">
      {/* left-1/2 + fixed negative margin centers the 220px strip column without a transform */}
      <div className="absolute bottom-0 top-0 left-1/2 -ml-[110px] w-[220px]">
        {[0, 1, 2, 3, 4].map((i) => (
          <ChunkStrip key={i} t={t} i={i} />
        ))}
      </div>
      <motion.span
        style={{ opacity: labelOpacity }}
        className="absolute -right-9 top-[148px] hidden font-mono text-[8px] uppercase tracking-[0.1em] text-accent sm:block"
      >
        ← 50 overlap
      </motion.span>
    </div>
  );
}

/* ─── 04 · EMBED — strips collapse into a pulsing dot-grid of vectors ────── */

const DOT_COUNT = 54; // 9 × 6
const ACCENT_DOTS = new Set([7, 21, 38]);

function EmbedDot({ t, i }: FigProps & { i: number }) {
  const reducedMotion = useReducedMotion();
  // Pseudo-random but stable appearance order (17 is coprime with 54).
  const order = (i * 17) % DOT_COUNT;
  const at = 0.18 + (order / DOT_COUNT) * 0.52;
  const opacity = useTransform(t, [at, at + 0.08], [0, 1]);
  const scale = useTransform(t, [at, at + 0.08], [0.3, 1]);
  const accent = ACCENT_DOTS.has(i);

  return (
    <motion.span
      style={{ opacity, scale }}
      className="flex h-2 w-2 items-center justify-center"
    >
      {accent ? (
        <motion.span
          className="h-2 w-2 rounded-full bg-accent"
          animate={
            reducedMotion
              ? undefined
              : { scale: [1, 1.5, 1], opacity: [1, 0.55, 1] }
          }
          transition={{ duration: 2.4, repeat: Infinity, delay: (i % 7) * 0.3 }}
        />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-ink/50" />
      )}
    </motion.span>
  );
}

function GhostStrip({ t, i }: FigProps & { i: number }) {
  // Echo of stage 03: the strips converge to the center and dissolve.
  const opacity = useTransform(t, [0, 0.22], [0.9, 0]);
  const y = useTransform(t, [0, 0.25], [(i - 2) * 36, 0]);
  const scaleX = useTransform(t, [0, 0.25], [1, 0.2]);
  return (
    <motion.div
      style={{ opacity, y, scaleX }}
      className="absolute h-[24px] w-[190px] border border-ink/60 bg-card"
    />
  );
}

function EmbedFigure({ t }: FigProps) {
  const axisOpacity = useTransform(t, [0.78, 0.92], [0, 1]);
  return (
    <div className="flex flex-col items-center gap-5">
      <div className="relative flex h-[200px] w-[300px] items-center justify-center">
        <div className="absolute inset-0 flex items-center justify-center" aria-hidden>
          {[0, 1, 2, 3, 4].map((i) => (
            <GhostStrip key={i} t={t} i={i} />
          ))}
        </div>
        <div className="grid grid-cols-9 gap-x-5 gap-y-6">
          {Array.from({ length: DOT_COUNT }, (_, i) => (
            <EmbedDot key={i} t={t} i={i} />
          ))}
        </div>
      </div>
      <motion.p
        style={{ opacity: axisOpacity }}
        className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink/45"
      >
        1536 dimensions — flattened to two for your eyes
      </motion.p>
    </div>
  );
}

/* ─── 05 · AGENT LOOP — see AgentLoopDiagram ─────────────────────────────── */

function LoopFigure({ t }: FigProps) {
  return <AgentLoopDiagram t={t} />;
}

/* ─── 06 · ANSWER — a mock answer streams in, cited and stamped ──────────── */

const ANSWER_WORDS =
  "The Calvin cycle uses the ATP and NADPH made in the light reactions to fix CO₂ into glucose — the sugar-building half of photosynthesis.".split(
    " ",
  );

function AnswerWord({ t, i, word }: FigProps & { i: number; word: string }) {
  const at = 0.04 + (i / ANSWER_WORDS.length) * 0.56;
  const opacity = useTransform(t, [at, at + 0.04], [0, 1]);
  return <motion.span style={{ opacity }}>{word} </motion.span>;
}

function AnswerFigure({ t }: FigProps) {
  const citeOpacity = useTransform(t, [0.66, 0.76], [0, 1]);
  const citeY = useTransform(t, [0.66, 0.76], [6, 0]);
  const stampOpacity = useTransform(t, [0.82, 0.88], [0, 1]);
  const stampScale = useTransform(t, [0.82, 0.92], [1.6, 1]);
  const stampRotate = useTransform(t, [0.82, 0.92], [-8, -1.5]);

  return (
    <div
      className="card-paper-md w-[300px] p-5 sm:w-[340px]"
      style={{ transform: "rotate(-1deg)" }}
    >
      <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink/50">
        Q · What does the Calvin cycle do?
      </p>
      <div className="my-3 h-px bg-rule" />
      <p className="margin-line font-body text-sm leading-relaxed text-ink/90">
        {ANSWER_WORDS.map((word, i) => (
          <AnswerWord key={i} t={t} i={i} word={word} />
        ))}
        <motion.sup style={{ opacity: citeOpacity }} className="text-accent">
          1
        </motion.sup>
      </p>
      <motion.p
        style={{ opacity: citeOpacity, y: citeY }}
        className="mt-3 font-mono text-[10px] text-ink/55"
      >
        <span className="text-accent" aria-hidden>
          ¹
        </span>{" "}
        biology-notes.pdf · <span className="tabular-nums">92%</span> match
      </motion.p>
      <motion.div
        style={{
          opacity: stampOpacity,
          scale: stampScale,
          rotate: stampRotate,
        }}
        className="mt-3 inline-block origin-center"
      >
        <span className="chip">✓ grounded</span>
      </motion.div>
    </div>
  );
}

/* ─── The six stages ─────────────────────────────────────────────────────── */

const STAGES: Stage[] = [
  {
    num: "01",
    label: "UPLOAD",
    caption:
      "Drop in a PDF, a scan, a spreadsheet — anything you would hand to a study partner.",
    footnote: "01 · multipart upload · 10 MB max · pdf docx xlsx png jpg webp txt md",
    Figure: UploadFigure,
  },
  {
    num: "02",
    label: "PARSE / OCR",
    caption:
      "Every page is read as text — and when a page is a scan, a vision model reads it the way you would.",
    footnote: "02 · pypdf + gpt-4o-mini vision OCR",
    Figure: OcrFigure,
  },
  {
    num: "03",
    label: "CHUNK",
    caption:
      "The text is sliced into small overlapping passages, so no idea gets cut in half at a boundary.",
    footnote: "03 · recursive splitter · 300 chars · 50 overlap",
    Figure: ChunksFigure,
  },
  {
    num: "04",
    label: "EMBED",
    caption:
      "Each passage becomes a point in vector space — meaning, mapped to coordinates a database can search.",
    footnote: "04 · text-embedding-3-small · 1536d · pgvector cosine",
    Figure: EmbedFigure,
  },
  {
    num: "05",
    label: "AGENT LOOP",
    caption:
      "An agent retrieves passages, grades them, and rewrites the question until the evidence is good enough.",
    footnote: "05 · LangGraph · grade ≥ 0.75 · max 2 rewrites",
    Figure: LoopFigure,
  },
  {
    num: "06",
    label: "ANSWER",
    caption:
      "The answer streams in with citations — then a judge stamps it grounded, or admits that it is not.",
    footnote: "06 · SSE stream · grounding judge",
    Figure: AnswerFigure,
  },
];

const N = STAGES.length;
const FADE = 0.035; // crossfade width between stages, in overall-progress units

/* ─── Shared stage content (figure + caption + footnote) ─────────────────── */

function StageContent({ stage, t }: { stage: Stage; t: MotionValue<number> }) {
  const { Figure } = stage;
  return (
    <>
      <div className="flex h-[300px] w-full max-w-[440px] items-center justify-center sm:h-[340px]">
        <Figure t={t} />
      </div>
      <div className="max-w-md px-2 text-center">
        <p className="font-mono text-[10px] font-medium uppercase tracking-[0.24em] text-accent">
          {stage.num} · {stage.label}
        </p>
        <p className="mt-2 font-body text-base leading-relaxed text-ink/75">
          {stage.caption}
        </p>
        <p className="mt-3 font-mono text-[10px] text-ink/45">{stage.footnote}</p>
      </div>
    </>
  );
}

/* ─── Scroll-driven version ──────────────────────────────────────────────── */

function StageLayer({
  stage,
  index,
  progress,
}: {
  stage: Stage;
  index: number;
  progress: MotionValue<number>;
}) {
  const start = index / N;
  const end = (index + 1) / N;

  // NOTE: motion hardware-accelerates direct scroll→opacity bindings via
  // WAAPI ScrollTimeline, where the input range becomes keyframe offsets.
  // Offsets must stay inside [0, 1] AND cover both endpoints — otherwise the
  // browser pads with implicit keyframes from the underlying value (opacity
  // 1) and ghost layers bleed through. So every range starts at 0 and ends
  // at 1 explicitly.
  const fadeIn: number[] = index === 0 ? [0] : [0, start, start + FADE];
  const fadeOut: number[] = index === N - 1 ? [1] : [end - FADE, end, 1];
  const opacity = useTransform(
    progress,
    [...fadeIn, ...fadeOut],
    [...(index === 0 ? [1] : [0, 0, 1]), ...(index === N - 1 ? [1] : [1, 0, 0])],
  );
  // Stage-local timeline: finishes a touch before the crossfade out.
  const t = useTransform(
    progress,
    [index === 0 ? 0 : start + FADE, end - FADE * 1.5],
    [0, 1],
  );

  return (
    <motion.div
      style={{ opacity }}
      className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-5"
    >
      <StageContent stage={stage} t={t} />
    </motion.div>
  );
}

function ScrollPipeline() {
  const sectionRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start start", "end end"],
  });

  const [active, setActive] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (v) => {
    setActive(Math.min(N - 1, Math.max(0, Math.floor(v * N))));
  });

  function jumpTo(i: number) {
    const el = sectionRef.current;
    if (!el) return;
    const scrollable = el.offsetHeight - window.innerHeight;
    window.scrollTo({
      top: el.offsetTop + ((i + 0.5) / N) * scrollable,
      behavior: "smooth",
    });
  }

  return (
    <section
      ref={sectionRef}
      id="how-it-works"
      className="relative"
      style={{ height: `${N * 110}vh` }}
      aria-label="How it works — the pipeline"
    >
      <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
        {/* Section header */}
        <div className="mx-auto w-full max-w-6xl px-6 pt-8">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.28em] text-ink/50">
            How it works
          </p>
          <h2
            className="font-display mt-1 text-2xl tracking-tight sm:text-3xl"
            style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 1" }}
          >
            One question, six moves.
          </h2>
          {/* Mobile stage indicator */}
          <div className="mt-3 flex gap-3 lg:hidden" aria-hidden>
            {STAGES.map((s, i) => (
              <span
                key={s.num}
                className={`font-mono text-[10px] tabular-nums ${
                  i === active ? "font-medium text-accent" : "text-ink/35"
                }`}
              >
                {s.num}
              </span>
            ))}
          </div>
        </div>

        <div className="relative mx-auto flex w-full max-w-6xl flex-1 px-6">
          {/* Ledger rail (desktop) */}
          <aside className="hidden w-56 shrink-0 flex-col justify-center lg:flex">
            <div className="relative pl-5">
              {/* Track + scroll progress */}
              <span className="absolute bottom-1 left-0 top-1 w-px bg-rule" aria-hidden />
              <motion.span
                className="absolute bottom-1 left-0 top-1 w-px origin-top bg-accent"
                style={{ scaleY: scrollYProgress }}
                aria-hidden
              />
              <ol className="space-y-4">
                {STAGES.map((s, i) => (
                  <li key={s.num}>
                    <button
                      type="button"
                      onClick={() => jumpTo(i)}
                      className={`flex items-baseline gap-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors ${
                        i === active
                          ? "font-medium text-accent"
                          : "text-ink/40 hover:text-ink/70"
                      }`}
                      aria-current={i === active ? "step" : undefined}
                    >
                      <span className="tabular-nums">{s.num}</span>
                      <span>{s.label}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          </aside>

          {/* Stacked stage layers */}
          <div className="relative flex-1">
            {STAGES.map((stage, i) => (
              <StageLayer
                key={stage.num}
                stage={stage}
                index={i}
                progress={scrollYProgress}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Reduced-motion version: static stacked figures ─────────────────────── */

function StaticStage({ stage }: { stage: Stage }) {
  // Constant timeline at 1 → every figure renders its finished state.
  const t = useMotionValue(1);
  return (
    <li className="flex flex-col items-center gap-5 border-t border-rule py-14 first:border-t-0">
      <StageContent stage={stage} t={t} />
    </li>
  );
}

function StaticPipeline() {
  return (
    <section
      id="how-it-works"
      className="mx-auto max-w-3xl px-6 py-16"
      aria-label="How it works — the pipeline"
    >
      <p className="font-mono text-[10px] font-medium uppercase tracking-[0.28em] text-ink/50">
        How it works
      </p>
      <h2
        className="font-display mt-1 text-3xl tracking-tight"
        style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 1" }}
      >
        One question, six moves.
      </h2>
      <ol className="mt-6 list-none">
        {STAGES.map((stage) => (
          <StaticStage key={stage.num} stage={stage} />
        ))}
      </ol>
    </section>
  );
}

/* ─── Entry point ────────────────────────────────────────────────────────── */

/**
 * SSR-safe reduced-motion check via useSyncExternalStore: the server (and
 * hydration pass) renders the animated layout, then the client swaps to the
 * static layout if the user prefers reduced motion — no hydration mismatch.
 */
const REDUCED_MQ = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onChange: () => void): () => void {
  const mq = window.matchMedia(REDUCED_MQ);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MQ).matches,
    () => false,
  );
}

export default function PipelineWalkthrough() {
  const reduced = usePrefersReducedMotion();
  return reduced ? <StaticPipeline /> : <ScrollPipeline />;
}
