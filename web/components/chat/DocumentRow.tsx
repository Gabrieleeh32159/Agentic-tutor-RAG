"use client";

import { Trash2, RotateCcw } from "lucide-react";
import type { Document } from "@/lib/types";

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function stageLabel(doc: Document): string {
  switch (doc.stage) {
    case "parsing":
      return "PARSING";
    case "ocr":
      return "OCR";
    case "embedding":
      return "EMBEDDING…";
    case "saving":
      return "SAVING…";
    default:
      return doc.status === "pending" ? "QUEUED" : "WORKING…";
  }
}

/** Deterministic tiny rotation per row so stamps don't all sit straight */
function tilt(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return ((Math.abs(h) % 21) - 10) / 10; // −1.0° … 1.0°
}

export default function DocumentRow({
  doc,
  onDelete,
  onRetry,
}: {
  doc: Document;
  onDelete: (docId: string) => void;
  onRetry: () => void;
}) {
  const inFlight = doc.status === "pending" || doc.status === "processing";
  const failed = doc.status === "failed";
  const ready = doc.status === "ready";

  return (
    <li className="card-paper p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p
            className="truncate font-mono text-[11px] font-medium text-ink"
            title={doc.filename}
          >
            {doc.filename}
          </p>

          {/* Filling-underline progress while ingesting */}
          {inFlight && (
            <div className="mt-1.5">
              <div className="h-0.5 w-full bg-rule" aria-hidden>
                <div
                  className="h-full bg-accent transition-[width] duration-700 ease-out"
                  style={{ width: `${Math.max(2, doc.progress)}%` }}
                />
              </div>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink/55">
                {stageLabel(doc)}{" "}
                <span className="tabular-nums text-ink/40">
                  {doc.progress}%
                </span>
              </p>
            </div>
          )}

          {/* Technical meta once done */}
          {ready && (
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.08em] text-ink/40">
              {formatBytes(doc.size_bytes)}
              {doc.page_count != null && <> · {doc.page_count} pp</>}
              {" · "}
              {doc.chunk_count} chunks
            </p>
          )}

          {/* Honest failure message */}
          {failed && (
            <p className="mt-1 font-body text-[11px] leading-snug text-accent">
              {doc.error_message ?? "Ingestion failed."}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {ready && (
            <span className="chip" style={{ transform: `rotate(${tilt(doc.id)}deg)` }}>
              Ready
            </span>
          )}
          {failed && (
            <span
              className="chip chip--accent"
              style={{ transform: `rotate(${tilt(doc.id)}deg)` }}
            >
              Failed
            </span>
          )}
          {inFlight && (
            <span className="chip chip--muted">Processing</span>
          )}

          <div className="flex items-center gap-1">
            {failed && (
              <button
                type="button"
                onClick={onRetry}
                title="Upload a new copy"
                aria-label={`Retry ${doc.filename} as a new upload`}
                className="p-1 text-ink/45 hover:text-accent"
              >
                <RotateCcw size={13} strokeWidth={2} aria-hidden />
              </button>
            )}
            <button
              type="button"
              onClick={() => onDelete(doc.id)}
              title="Delete document"
              aria-label={`Delete ${doc.filename}`}
              className="p-1 text-ink/45 hover:text-accent disabled:opacity-40"
              disabled={inFlight}
            >
              <Trash2 size={13} strokeWidth={2} aria-hidden />
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}
