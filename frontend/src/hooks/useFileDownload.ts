import { useState } from "react";
import { ApiError, apiGetBlob } from "@/api/client";

/**
 * Opens a file that lives in a PRIVATE Supabase Storage bucket.
 *
 * WHY A HOOK AND NOT AN `<a href>`. Uploaded files (classroom post attachments, class
 * resources) are stored in the private `resources` bucket, so their stored `file_url` is
 * an object PATH, not a URL - there is nothing an anchor can point at. The bytes come
 * back through a role-scoped API route that has to carry the caller's bearer token.
 *
 * Both call sites used to link directly at the stored value and both were broken in their
 * own way: the classroom stream built a `/object/public/resources/...` URL, which Supabase
 * answers for a private bucket with `NoSuchBucket`, and the resources page linked at the
 * bare path, which resolved against the frontend origin. Shared here so a third caller
 * cannot invent a fourth way to get it wrong.
 *
 * Fetches on CALL, not on mount - a stream page can list dozens of files and eagerly
 * downloading all of them would pull megabytes nobody asked for.
 */
export function useFileDownload(path: string) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    if (isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      const blob = await apiGetBlob(path);
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      // Deliberately not revoked straight away - the new tab is still reading it. On a
      // timer rather than never, so a long session does not leak every file opened.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open this file.");
    } finally {
      setIsLoading(false);
    }
  }

  return { open, isLoading, error };
}
