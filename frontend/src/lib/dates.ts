/** Local calendar-date helpers for the `YYYY-MM-DD` strings the API uses.
 *
 * WHY THIS EXISTS - a real bug, caught in the browser
 * ----------------------------------------------------
 * The obvious way to produce these strings is `d.toISOString().slice(0, 10)`, and
 * it is wrong everywhere east of UTC. `toISOString()` converts to UTC first, so at
 * UTC+5:30 (this project's actual timezone) a *local* midnight is 18:30 the
 * PREVIOUS day in UTC, and the sliced date is a day behind.
 *
 * Where that merely shifted a date range by one day it went unnoticed. Where it
 * round-tripped, it broke outright: the day register's next-day button did
 *
 *     new Date("2026-08-10T00:00:00")   // local midnight  = 2026-08-09T18:30Z
 *       .setDate(getDate() + 1)         // local 2026-08-11 = 2026-08-10T18:30Z
 *       .toISOString().slice(0, 10)     // -> "2026-08-10"  <-- the SAME date
 *
 * so "next" appeared dead and "previous" skipped two days.
 *
 * Everything here stays in local calendar space and formats the date by its parts,
 * so no UTC conversion ever happens. Use these instead of hand-rolling a
 * toISOString() slice.
 */

/** Format a Date as `YYYY-MM-DD` using its LOCAL calendar fields. */
export function toIsoDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Parse `YYYY-MM-DD` as a LOCAL midnight Date.
 *
 * `new Date("2026-08-10")` (no time part) is parsed as UTC midnight by spec, which
 * is the other half of the same trap; passing the parts explicitly is local. */
export function fromIsoDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** Today, as a local `YYYY-MM-DD`. */
export function todayIso(): string {
  return toIsoDate(new Date());
}

/** `YYYY-MM-DD` shifted by whole days. Round-trips exactly, in any timezone. */
export function shiftIsoDate(iso: string, days: number): string {
  const d = fromIsoDate(iso);
  d.setDate(d.getDate() + days);
  return toIsoDate(d);
}

/** `n` days before today, as a local `YYYY-MM-DD`. */
export function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toIsoDate(d);
}
