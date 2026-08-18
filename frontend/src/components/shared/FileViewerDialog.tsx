import { useEffect, useState } from "react";
import { AlertCircle, Download, ExternalLink, Loader2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApiError, apiGetBlob } from "@/api/client";

/** Formats a browser can render itself. Anything else gets a download instead of a blank
 *  frame - an `<iframe>` pointed at a .docx renders nothing in most browsers, which reads as
 *  a broken viewer rather than an unsupported format. */
function isViewable(mimeType: string | undefined): boolean {
  if (!mimeType) return false;
  return (
    mimeType === "application/pdf" ||
    mimeType.startsWith("image/") ||
    mimeType.startsWith("text/")
  );
}

/**
 * Views a file stored in a PRIVATE bucket, in-app.
 *
 * Files live in the private `resources` bucket, so there is no URL to point an `<iframe>` or
 * `<img>` at - the bytes have to be fetched with the caller's bearer token and turned into a
 * blob URL (same approach as the fee payment-proof viewer).
 *
 * WHY A VIEWER AND NOT A DOWNLOAD. "Download" made checking a worksheet a five-step detour:
 * save it, find it in Downloads, open it, and it is now a stale copy on disk. Teachers and
 * students overwhelmingly want to LOOK at the file. Download stays available for the formats
 * a browser cannot render, and as an explicit action for the ones it can.
 */
export default function FileViewerDialog({
  open,
  onClose,
  path,
  fileName,
  mimeType,
}: {
  open: boolean;
  onClose: () => void;
  /** API path that streams the bytes, e.g. `/resources/12/download`. */
  path: string;
  fileName: string;
  mimeType?: string;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let url: string | null = null;
    let cancelled = false;

    setIsLoading(true);
    setError(null);
    apiGetBlob(path)
      .then((blob) => {
        if (cancelled) return;
        // The server sends the real content type; trust it over the caller's hint, which can
        // be stale for rows written before mime detection improved.
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not open this file.");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
      // Revoked on close, unlike the fire-and-forget download path - the dialog owns this
      // blob's whole lifetime, so there is no new tab still reading it.
      if (url) URL.revokeObjectURL(url);
      setObjectUrl(null);
    };
  }, [open, path]);

  const viewable = isViewable(mimeType);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-3 pr-6">
            <span className="min-w-0 truncate text-base">{fileName}</span>
            {objectUrl && (
              <div className="flex shrink-0 items-center gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => window.open(objectUrl, "_blank", "noopener,noreferrer")}
                  className="flex items-center gap-1 text-xs"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  New tab
                </Button>
                {/* download attribute so this saves under the real filename rather than a
                    uuid-ish blob id. An <a>, not a Button - Button renders a <button> and has
                    no asChild passthrough in this codebase. */}
                <a
                  href={objectUrl}
                  download={fileName}
                  className={buttonVariants({
                    variant: "outline",
                    size: "sm",
                    className: "flex items-center gap-1 text-xs",
                  })}
                >
                  <Download className="h-3.5 w-3.5" />
                  Download
                </a>
              </div>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="min-h-[60vh]">
          {isLoading ? (
            <div className="flex h-[60vh] flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin" />
              Loading file…
            </div>
          ) : error ? (
            <div
              className="flex h-[60vh] flex-col items-center justify-center gap-2 px-6 text-center"
              role="alert"
            >
              <AlertCircle className="h-6 w-6 text-[hsl(var(--urgent))]" />
              <p className="text-sm font-medium text-[hsl(var(--urgent))]">{error}</p>
            </div>
          ) : !objectUrl ? null : viewable ? (
            mimeType?.startsWith("image/") ? (
              <div className="flex max-h-[70vh] justify-center overflow-auto">
                <img src={objectUrl} alt={fileName} className="max-w-full object-contain" />
              </div>
            ) : (
              <iframe
                src={objectUrl}
                title={fileName}
                className="h-[70vh] w-full rounded-lg border border-border bg-white"
              />
            )
          ) : (
            <div className="flex h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center">
              <p className="text-sm font-medium text-foreground">
                This file type can't be previewed in the browser
              </p>
              <p className="text-xs text-muted-foreground">
                {mimeType || "Unknown format"} — download it to open in the right application.
              </p>
              <a
                href={objectUrl}
                download={fileName}
                className={buttonVariants({
                  size: "sm",
                  className: "flex items-center gap-1.5",
                })}
              >
                <Download className="h-4 w-4" />
                Download {fileName}
              </a>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
