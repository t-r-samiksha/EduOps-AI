/** CSV export, built from data already loaded in the browser.
 *
 * Deliberately client-side rather than a backend export endpoint: the register
 * and analytics payloads are fully in memory by the time an export button is
 * visible, and `apiGet` authenticates with a bearer header - a server CSV route
 * would need blob-fetch plumbing to carry that token for no extra capability at
 * this data size. If exports ever need to be emailed or scheduled, that's the
 * point to move generation server-side.
 */

/** RFC 4180: quote any field containing a comma, quote or newline, and escape
 * embedded quotes by doubling them. */
function escapeField(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(headers: string[], rows: (string | number | null | undefined)[][]): string {
  return [headers, ...rows].map((row) => row.map(escapeField).join(",")).join("\r\n");
}

/** Triggers a browser download of `csv` as `filename`.
 *
 * The leading ﻿ is a UTF-8 BOM: without it Excel on Windows reads the file
 * as the local ANSI codepage and mangles any non-ASCII student name. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Revoked on the next tick rather than immediately - Safari cancels an
  // in-flight download if the object URL disappears synchronously.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** `attendance-grade-8-a-2026-08-17.csv` - lowercase, spaces and punctuation
 * collapsed to single dashes, so the file lands predictably sorted. */
export function csvFilename(...parts: (string | number | null | undefined)[]): string {
  const slug = parts
    .filter((p) => p !== null && p !== undefined && String(p).length > 0)
    .join("-")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${slug || "export"}.csv`;
}
