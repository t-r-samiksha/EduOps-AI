import { useState } from "react";
import { Eye, Sparkles } from "lucide-react";
import FileViewerDialog from "@/components/shared/FileViewerDialog";

export interface PostAttachmentRef {
  id: number;
  file_name: string;
  file_type: string;
  file_size: number;
  /** Set once the file has been indexed into the resource library, which is what makes it
   *  answerable by the Doubt Bot. */
  resource_id?: number | null;
}

/** One viewable post attachment.
 *
 * A button rather than a link because `att.file_url` is an object path in a PRIVATE bucket -
 * the bytes come through an authenticated, role-scoped route. Opens FileViewerDialog, which
 * renders the file inline and keeps Download available. */
export default function AttachmentLink({
  attachment,
  formatBytes,
  icon: Icon,
}: {
  attachment: PostAttachmentRef;
  formatBytes: (bytes: number) => string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-elevated/30 p-2.5 text-left transition-colors hover:bg-elevated/70 group"
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
        <Eye className="h-4 w-4 shrink-0 text-ink-faint group-hover:text-accent" />
      </button>
      <FileViewerDialog
        open={open}
        onClose={() => setOpen(false)}
        path={`/classroom/attachments/${attachment.id}/download`}
        fileName={attachment.file_name}
        mimeType={attachment.file_type}
      />
    </div>
  );
}
