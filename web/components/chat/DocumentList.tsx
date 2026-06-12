"use client";

import type { Document } from "@/lib/types";
import DocumentRow from "./DocumentRow";

export default function DocumentList({
  documents,
  maxDocs,
  onDelete,
  onRetry,
}: {
  documents: Document[];
  maxDocs: number;
  onDelete: (docId: string) => void;
  onRetry: () => void;
}) {
  return (
    <section aria-label="Documents">
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-ink/50">
          Documents
        </h2>
        <span className="font-mono text-[10px] tabular-nums text-ink/40">
          {documents.length} / {maxDocs}
        </span>
      </div>

      {documents.length === 0 ? (
        <p className="mt-2 border border-dashed border-rule px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink/35">
          No documents yet
        </p>
      ) : (
        <ul className="mt-2 space-y-2">
          {documents.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onDelete={onDelete}
              onRetry={onRetry}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
