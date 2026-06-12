import Link from "next/link";

/**
 * Chat app stub.
 * Task 2 replaces this with the full upload + streaming chat interface.
 */
export default function ChatPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center min-h-screen px-6">
      <div
        className="card-paper w-full max-w-md p-10 space-y-5 text-center"
        style={{ transform: "rotate(0.3deg)" }}
      >
        <span
          className="chip chip--accent"
          style={{ transform: "rotate(-1deg)" }}
        >
          Under Construction
        </span>

        <h1
          className="font-display text-2xl leading-tight mt-3"
          style={{ fontVariationSettings: "'opsz' 48, 'SOFT' 80, 'WONK' 0" }}
        >
          App coming soon
        </h1>

        <hr style={{ borderColor: "var(--rule)" }} />

        <p className="font-body text-sm" style={{ color: "color-mix(in srgb, var(--ink) 60%, transparent)" }}>
          The chat interface is being assembled. Check back shortly.
        </p>

        <Link
          href="/"
          className="dotted-link font-body text-sm"
        >
          ← Back to home
        </Link>
      </div>
    </main>
  );
}
