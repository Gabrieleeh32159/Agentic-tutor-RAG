"use client";

/**
 * Cold-start gate. Shown while the backend health check hasn't passed yet —
 * a paper telegram explaining that free hosting sleeps.
 */
export default function ServerWakingNotice({
  attempts,
}: {
  /** Failed probe count: 0 = first probe still in flight */
  attempts: number;
}) {
  const waking = attempts > 0;

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-16">
      <div
        className="card-paper-md w-full max-w-sm p-8 text-center"
        style={{ transform: "rotate(-0.5deg)" }}
        role="status"
        aria-live="polite"
      >
        <span
          className={`chip ${waking ? "chip--accent" : "chip--muted"}`}
          style={{ transform: "rotate(-1.5deg)" }}
        >
          {waking ? "Server waking" : "Connecting"}
        </span>

        <h2
          className="font-display mt-4 text-xl leading-snug"
          style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 0" }}
        >
          {waking ? "Warming up the press…" : "Reaching the server…"}
        </h2>

        <hr className="mx-auto mt-4 w-16 border-rule" />

        <p className="mt-4 font-body text-sm leading-relaxed text-ink/65">
          {waking
            ? "This runs on free hosting — the server goes to sleep when idle and takes about 30 seconds to wake. We keep retrying for you."
            : "Checking that the backend is up before opening your session."}
        </p>

        {waking && (
          <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.15em] text-ink/40">
            Attempt {attempts + 1} · retrying automatically
          </p>
        )}
      </div>
    </div>
  );
}
