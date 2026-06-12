"use client";

import type { ReactNode } from "react";
import { motion, useTransform, type MotionValue } from "motion/react";

const MONO = "var(--font-ibm-plex-mono), monospace";

/** Fades a group of SVG elements in at a given point of the local timeline. */
function FadeG({
  t,
  at,
  children,
}: {
  t: MotionValue<number>;
  at: number;
  children: ReactNode;
}) {
  const opacity = useTransform(t, [at, at + 0.06], [0, 1]);
  return <motion.g style={{ opacity }}>{children}</motion.g>;
}

/** Small triangular arrowhead, rotated along the travel direction. */
function Arrow({
  x,
  y,
  angle,
  color,
}: {
  x: number;
  y: number;
  angle: number;
  color: string;
}) {
  return (
    <polygon
      points="0,-3.5 7,0 0,3.5"
      fill={color}
      transform={`translate(${x} ${y}) rotate(${angle})`}
    />
  );
}

/** A labeled stop on the loop: dot + mono caption + small annotation. */
function Stop({
  x,
  y,
  label,
  sub,
  labelY,
  subY,
  accent = false,
}: {
  x: number;
  y: number;
  label: string;
  sub?: string;
  labelY: number;
  subY?: number;
  accent?: boolean;
}) {
  const color = accent ? "var(--accent)" : "var(--ink)";
  return (
    <g>
      <circle
        cx={x}
        cy={y}
        r={5}
        fill="var(--card)"
        stroke={color}
        strokeWidth={1.5}
      />
      <text
        x={x}
        y={labelY}
        textAnchor="middle"
        fontSize={10}
        fontFamily={MONO}
        fontWeight={500}
        letterSpacing="1.5"
        fill={color}
      >
        {label}
      </text>
      {sub && subY !== undefined && (
        <text
          x={x}
          y={subY}
          textAnchor="middle"
          fontSize={8}
          fontFamily={MONO}
          fill="rgba(28,24,20,0.5)"
        >
          {sub}
        </text>
      )}
    </g>
  );
}

/**
 * Stage 05 figure — the agent loop draws itself: a circular path with three
 * stops (RETRIEVE → GRADE → REWRITE), a vermilion retry arc back to the top,
 * and an exit arrow toward the answer once the grade passes.
 *
 * `t` is the stage-local timeline, 0 → 1. Pass a constant MotionValue(1)
 * to render the finished diagram (reduced-motion fallback).
 */
export default function AgentLoopDiagram({ t }: { t: MotionValue<number> }) {
  // Main loop draws across [0.05, 0.55]; stops appear as the pen reaches them.
  const loopDrawn = useTransform(t, [0.05, 0.55], [0, 1]);
  // Retry arc (vermilion, dashed) draws after the loop closes.
  const retryDrawn = useTransform(t, [0.6, 0.78], [0, 1]);
  // Exit arrow toward the answer, last.
  const exitDrawn = useTransform(t, [0.84, 0.94], [0, 1]);

  return (
    <svg
      viewBox="0 0 400 300"
      className="h-auto w-full max-w-[380px]"
      role="img"
      aria-label="Agent loop diagram: retrieve, grade, rewrite, with a retry arc and an exit toward the answer"
    >
      {/* Main loop — full circle starting at the top, clockwise */}
      <motion.path
        d="M 170 62 A 96 96 0 0 1 170 254 A 96 96 0 0 1 170 62"
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.5}
        style={{ pathLength: loopDrawn }}
      />

      {/* Direction arrowheads along the loop (appear as the pen passes) */}
      <FadeG t={t} at={0.13}>
        <Arrow x={253.1} y={110} angle={60} color="var(--ink)" />
      </FadeG>
      <FadeG t={t} at={0.3}>
        <Arrow x={170} y={254} angle={180} color="var(--ink)" />
      </FadeG>
      <FadeG t={t} at={0.46}>
        <Arrow x={86.9} y={110} angle={-60} color="var(--ink)" />
      </FadeG>

      {/* Stops */}
      <FadeG t={t} at={0.07}>
        <Stop
          x={170}
          y={62}
          label="RETRIEVE"
          sub="cosine top-k"
          labelY={36}
          subY={48}
        />
      </FadeG>
      <FadeG t={t} at={0.22}>
        <Stop
          x={253}
          y={206}
          label="GRADE"
          sub="score ≥ 0.75?"
          labelY={230}
          subY={242}
        />
      </FadeG>
      <FadeG t={t} at={0.38}>
        <Stop
          x={87}
          y={206}
          label="REWRITE"
          sub="sharper query"
          labelY={230}
          subY={242}
          accent
        />
      </FadeG>

      {/* Center mark */}
      <FadeG t={t} at={0.5}>
        <text
          x={170}
          y={162}
          textAnchor="middle"
          fontSize={9}
          fontFamily={MONO}
          letterSpacing="3"
          fill="rgba(28,24,20,0.35)"
        >
          AGENT
        </text>
      </FadeG>

      {/* Retry arc — vermilion, dashed, from REWRITE back up to RETRIEVE */}
      <motion.path
        d="M 80 198 C 16 158 28 66 150 50"
        fill="none"
        stroke="var(--accent)"
        strokeWidth={1.5}
        strokeDasharray="4 4"
        style={{ pathLength: retryDrawn }}
      />
      <FadeG t={t} at={0.76}>
        <Arrow x={150} y={50} angle={-7} color="var(--accent)" />
        <text
          x={52}
          y={34}
          textAnchor="middle"
          fontSize={8.5}
          fontFamily={MONO}
          letterSpacing="1"
          fill="var(--accent)"
        >
          retry · ×2 max
        </text>
      </FadeG>

      {/* Exit toward the answer once the grade passes */}
      <motion.path
        d="M 262 198 L 316 168"
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.5}
        style={{ pathLength: exitDrawn }}
      />
      <FadeG t={t} at={0.92}>
        <Arrow x={316} y={168} angle={-29} color="var(--ink)" />
        <text
          x={322}
          y={158}
          textAnchor="start"
          fontSize={9}
          fontFamily={MONO}
          fontWeight={500}
          letterSpacing="1.5"
          fill="var(--ink)"
        >
          ANSWER
        </text>
      </FadeG>
    </svg>
  );
}
