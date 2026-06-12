"use client";

import { useEffect, useRef, useState } from "react";
import { FilePlus2 } from "lucide-react";

export const ALLOWED_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".xlsx",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".txt",
  ".md",
];

/**
 * Drag-drop + click upload target. Pure input surface: validation and the
 * actual upload calls live in the parent (ChatApp).
 *
 * `openPickerRef` lets other surfaces (empty state, failed-row retry) open
 * the same file picker.
 */
export default function UploadZone({
  disabled,
  uploading,
  onFiles,
  openPickerRef,
}: {
  disabled: boolean;
  uploading: boolean;
  onFiles: (files: File[]) => void;
  openPickerRef?: { current: (() => void) | null };
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!openPickerRef) return;
    openPickerRef.current = () => inputRef.current?.click();
    return () => {
      openPickerRef.current = null;
    };
  }, [openPickerRef]);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) onFiles(files);
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ALLOWED_EXTENSIONS.join(",")}
        className="sr-only"
        aria-hidden
        tabIndex={-1}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFiles(files);
          e.target.value = ""; // allow re-selecting the same file
        }}
      />

      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        aria-label="Upload documents — drag and drop or browse"
        className={`group w-full border border-dashed bg-card px-4 py-5 text-center transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          dragging
            ? "border-accent bg-accent/5"
            : "border-ink/40 hover:border-accent"
        }`}
        style={dragging ? { transform: "rotate(-0.4deg)" } : undefined}
      >
        <FilePlus2
          size={18}
          strokeWidth={1.5}
          aria-hidden
          className={`mx-auto ${dragging ? "text-accent" : "text-ink/50 group-hover:text-accent"}`}
        />
        <p className="mt-2 font-body text-xs font-medium text-ink/75">
          {uploading
            ? "Uploading…"
            : dragging
              ? "Drop to file it"
              : "Drop files or click to browse"}
        </p>
        <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.1em] text-ink/40">
          pdf · docx · xlsx · png · jpg · webp · txt · md — max 10 MB
        </p>
      </button>
    </div>
  );
}
