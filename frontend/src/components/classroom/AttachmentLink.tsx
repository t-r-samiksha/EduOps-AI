import { AlertCircle, Download, Loader2, Sparkles } from "lucide-react";
import { useFileDownload } from "@/hooks/useFileDownload";

export interface PostAttachmentRef {
  id: number;
  file_name: string;
  file_type: string;
  file_size: number;
  /** Set once the file has been indexed into the resource library, which is what makes it
   *  answerable by the Doubt Bot. */
  resource_id?: number | null;
}

/** One downloadable post attachment. See useFileDownload for why this is a button
 * making an authenticated request rather than a plain link to `att.file_url`. */
export default function AttachmentLink({
  attachment,
  formatBytes,
  icon: Icon,
}: {
  attachment: PostAttachmentRef;
  formatBytes: (bytes: number) => string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  const { open, isLoading, error } = useFileDownload(
    `/classroom/attachments/${attachment.id}/download`,
  );

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={open}
        disabled={isLoading}
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-elevated/30 p-2.5 text-left transition-colors hover:bg-elevated/70 disabled:opacity-60 group"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
            <Icon className="h-4 w-4" />
          </div>
          <div className="flex flex-col min-w-0">
            <span className="text-xs font-medium text-ink truncate group-hover:text-accent">
              {attachment.file_name}
            </span>
            <span className="flex items-center gap-1 text-[11px] text-ink-faint">
              {formatBytes(attachment.file_size)}
              {/* Makes the classroom -> library -> bot link visible. Before this, a teacher
                  had no way to tell whether what they shared was answerable by the bot -
                  and for classroom uploads it never was. */}
              {attachment.resource_id != null && (
                <>
                  <span aria-hidden="true">·</span>
                  <span
                    className="flex items-center gap-0.5 text-accent"
                    title="Indexed in the resource library - the Doubt Bot can answer from this file"
                  >
                    <Sparkles className="h-2.5 w-2.5" />
                    Bot-searchable
                  </span>
                </>
              )}
            </span>
          </div>
        </div>
        {isLoading ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-ink-faint" />
        ) : (
          <Download className="h-4 w-4 shrink-0 text-ink-faint group-hover:text-accent" />
        )}
      </button>
      {error && (
        <p className="flex items-start gap-1 pl-1 text-[11px] text-urgent" role="alert">
          <AlertCircle className="mt-px h-3 w-3 shrink-0" />
          {error}
        </p>
      )}
    </div>
  );
}
