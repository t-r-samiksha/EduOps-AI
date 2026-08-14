import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";

interface FileDropzoneProps {
  file: File | null;
  onFileSelected: (file: File | null) => void;
  accept?: string;
  className?: string;
}

/** Drag-and-drop + click-to-browse file picker, styled consistent with the existing
 * Input/Select tokens (rounded-xl border, accent-on-hover) rather than a new visual
 * language — the design system has no file-upload primitive yet, so this is genuinely
 * new, not a reinvention of something that already exists. */
export default function FileDropzone({ file, onFileSelected, accept = "image/*", className }: FileDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
        dragging ? "border-accent bg-accent/5" : "border-border bg-elevated/40 hover:border-border-strong",
        className
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const dropped = e.dataTransfer.files?.[0];
        if (dropped) onFileSelected(dropped);
      }}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
    >
      <UploadCloud className="h-6 w-6 text-ink-muted" />
      {file ? (
        <div>
          <p className="text-sm font-medium text-ink">{file.name}</p>
          <p className="text-xs text-ink-muted">{(file.size / 1024).toFixed(0)} KB · click to replace</p>
        </div>
      ) : (
        <div>
          <p className="text-sm font-medium text-ink">Drop a file here, or click to browse</p>
          <p className="text-xs text-ink-muted">Image of a document (marksheet, admission form, ID proof, …)</p>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => onFileSelected(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}
