import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CameraOff,
  CheckCircle2,
  Circle,
  Play,
  Square,
  UserCheck,
  UserX,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useMarkAttendance, useReviewAttendanceRecord } from "@/api/hooks/useAttendance";
import { ApiError } from "@/api/client";
import type { MarkAttendanceResponse, RosterStudent } from "@/api/types";
import { cn } from "@/lib/utils";

/** How often a frame is grabbed off the video and sent to /attendance/mark.
 * Measured from the *end* of the previous request, not on a fixed interval, so
 * a slow recognition pass can never queue up a backlog of frames. */
const CAPTURE_INTERVAL_MS = 3000;
/** Give the camera a moment to auto-expose before the first frame - a capture
 * taken the instant the stream opens is usually a dark, unrecognizable frame. */
const FIRST_CAPTURE_DELAY_MS = 800;
/** Consecutive /attendance/mark failures before scanning gives up, so a bad
 * slot id or a dead backend isn't hammered every 3 seconds for the whole demo. */
const MAX_CONSECUTIVE_FAILURES = 3;
const JPEG_QUALITY = 0.85;
/** The feed is append-only; cap it so a long session can't grow unbounded. */
const MAX_LOG_ENTRIES = 60;

interface SeenStudent {
  studentId: number;
  name: string;
  recordId: number;
  /** Best confidence seen for this student across every frame so far. */
  confidence: number;
  needsReview: boolean;
  /** True once a teacher has explicitly confirmed (or corrected) a needs_review row. */
  confirmed: boolean;
  firstSeenLabel: string;
}

interface LogEntry {
  id: number;
  kind: "recognized" | "upgraded" | "confirmed" | "rejected" | "unmatched";
  text: string;
  timeLabel: string;
}

function timeLabel(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ConfidenceBadge({ confidence, needsReview }: { confidence: number; needsReview: boolean }) {
  return (
    <Badge variant={needsReview ? "urgent" : "positive"} className="font-mono tabular-nums">
      {(confidence * 100).toFixed(1)}%
    </Badge>
  );
}

/** getUserMedia's failure modes are the single most likely thing to break a live
 * demo, and the raw DOMException names mean nothing to a teacher - each one gets
 * a message that says what to actually do about it. */
function describeCameraError(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  switch (name) {
    case "NotAllowedError":
    case "PermissionDeniedError":
    case "SecurityError":
      return "Camera permission denied — allow camera access in your browser (click the camera icon in the address bar), then press Start again.";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "No camera found on this device. Switch to Upload Photo mode instead.";
    case "NotReadableError":
    case "TrackStartError":
      return "The camera is in use by another app (Zoom, Teams, another browser tab). Close it, then press Start again.";
    case "OverconstrainedError":
      return "This camera can't provide a usable video stream. Try a different camera, or switch to Upload Photo mode.";
    default:
      return err instanceof Error && err.message
        ? `Could not start the camera: ${err.message}`
        : "Could not start the camera.";
  }
}

export default function LiveCameraCapture({
  timetableSlotId,
  date,
}: {
  timetableSlotId: number;
  date: string;
}) {
  const mark = useMarkAttendance();
  const review = useReviewAttendanceRecord();

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  /** Set the moment scanning stops, so an in-flight capture that resolves after
   * the teacher pressed Stop doesn't schedule another round. */
  const cancelledRef = useRef(true);
  const failuresRef = useRef(0);
  const logIdRef = useRef(0);
  /** The authoritative accumulated session state. Kept in a ref (not just
   * state) so each merge reads the real previous value without doing the work
   * inside a setState updater, which React can invoke twice in dev. */
  const seenRef = useRef<Map<number, SeenStudent>>(new Map());

  const [scanning, setScanning] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [markError, setMarkError] = useState<string | null>(null);
  const [stoppedReason, setStoppedReason] = useState<string | null>(null);
  /** Render mirror of seenRef, ordered by first sighting. */
  const [seenList, setSeenList] = useState<SeenStudent[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [roster, setRoster] = useState<RosterStudent[]>([]);
  const [framesProcessed, setFramesProcessed] = useState(0);
  const [unmatchedLatest, setUnmatchedLatest] = useState(0);
  const [reviewedIds, setReviewedIds] = useState<Set<number>>(new Set());
  /** Only populated when a teacher picks a DIFFERENT student than the one the CV
   * pipeline matched for a needs_review row - same idiom as the upload path. */
  const [reassignments, setReassignments] = useState<Record<number, number>>({});

  const seenById = useMemo(() => new Map(seenList.map((s) => [s.studentId, s])), [seenList]);
  const presentCount = useMemo(
    () => roster.filter((s) => seenById.has(s.student_id)).length,
    [roster, seenById]
  );
  const pendingReview = useMemo(
    () => seenList.filter((s) => s.needsReview && !reviewedIds.has(s.recordId)),
    [seenList, reviewedIds]
  );

  function commitSeen() {
    setSeenList(Array.from(seenRef.current.values()));
  }

  function pushLog(entries: Omit<LogEntry, "id" | "timeLabel">[]) {
    if (entries.length === 0) return;
    const stamped = entries.map((e) => ({ ...e, id: ++logIdRef.current, timeLabel: timeLabel() }));
    setLog((prev) => [...stamped.reverse(), ...prev].slice(0, MAX_LOG_ENTRIES));
  }

  function stopStream() {
    cancelledRef.current = true;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  function resetSession() {
    seenRef.current = new Map();
    failuresRef.current = 0;
    setSeenList([]);
    setLog([]);
    setRoster([]);
    setFramesProcessed(0);
    setUnmatchedLatest(0);
    setReviewedIds(new Set());
    setReassignments({});
    setMarkError(null);
    setStoppedReason(null);
  }

  const rosterName = (studentId: number, list: RosterStudent[] = roster) =>
    list.find((s) => s.student_id === studentId)?.name ?? `Student #${studentId}`;

  /** Fold one /attendance/mark response into the accumulated session state.
   * A student already logged is never re-logged - the only exception is a
   * needs_review entry that a later, more confident frame resolves. */
  function absorb(data: MarkAttendanceResponse) {
    setRoster(data.class_roster);
    setFramesProcessed((n) => n + 1);

    const lines: Omit<LogEntry, "id" | "timeLabel">[] = [];
    const map = seenRef.current;
    for (const m of data.matches) {
      const name = m.student_name ?? rosterName(m.student_id, data.class_roster);
      const existing = map.get(m.student_id);
      if (!existing) {
        map.set(m.student_id, {
          studentId: m.student_id,
          name,
          recordId: m.record_id,
          confidence: m.confidence,
          needsReview: m.needs_review,
          confirmed: false,
          firstSeenLabel: timeLabel(),
        });
        lines.push({
          kind: "recognized",
          text: m.needs_review
            ? `${name} detected at ${(m.confidence * 100).toFixed(1)}% — needs confirmation`
            : `${name} marked present (${(m.confidence * 100).toFixed(1)}%)`,
        });
      } else if (existing.needsReview && !m.needs_review) {
        // A later frame cleared the uncertainty on its own - drop the HITL row.
        map.set(m.student_id, { ...existing, recordId: m.record_id, confidence: m.confidence, needsReview: false });
        lines.push({ kind: "upgraded", text: `${name} confirmed by a clearer frame (${(m.confidence * 100).toFixed(1)}%)` });
      } else if (m.confidence > existing.confidence) {
        // Keep the best confidence seen, silently - not a new event to log.
        map.set(m.student_id, { ...existing, confidence: m.confidence });
      }
    }
    commitSeen();

    const unmatched = data.unmatched_faces.length;
    setUnmatchedLatest((prev) => {
      // Only log when the count actually changes, otherwise a room with one
      // unenrolled face would post a line every 3 seconds and drown the feed.
      if (unmatched !== prev && unmatched > 0) {
        lines.push({
          kind: "unmatched",
          text: `${unmatched} face${unmatched === 1 ? "" : "s"} detected but not recognized`,
        });
      }
      return unmatched;
    });
    pushLog(lines);
  }

  async function captureOnce() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    // HAVE_CURRENT_DATA - anything less and there's no frame to draw yet.
    if (!video || !canvas || video.readyState < 2 || !video.videoWidth) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY)
    );
    if (!blob) return;

    // Wrapped as a File (not a bare Blob) so the multipart part carries a
    // filename - FastAPI's UploadFile needs one. Same FormData shape the
    // upload path builds, via the same useMarkAttendance mutation.
    const file = new File([blob], `frame-${Date.now()}.jpg`, { type: "image/jpeg" });
    try {
      const data = await mark.mutateAsync({ timetableSlotId, file, date: date || undefined });
      failuresRef.current = 0;
      setMarkError(null);
      absorb(data);
    } catch (err) {
      failuresRef.current += 1;
      setMarkError(err instanceof ApiError ? err.message : "Recognition request failed.");
      if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
        stopStream();
        setScanning(false);
        setStoppedReason(
          `Live scan stopped after ${MAX_CONSECUTIVE_FAILURES} failed recognition attempts in a row — check the selected slot and date, then press Start to retry.`
        );
      }
    }
  }

  /** The capture loop re-schedules itself only once the previous request has
   * settled, which is what guarantees no two /attendance/mark calls overlap.
   * Held in a ref and refreshed every render so the chain always runs against
   * the current slot/date without ever restarting the timer. */
  const scanLoopRef = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    scanLoopRef.current = async () => {
      if (cancelledRef.current) return;
      await captureOnce();
      if (cancelledRef.current) return;
      timerRef.current = window.setTimeout(() => void scanLoopRef.current(), CAPTURE_INTERVAL_MS);
    };
  });

  async function handleStart() {
    setCameraError(null);
    setMarkError(null);
    setStoppedReason(null);
    failuresRef.current = 0;

    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError(
        "Camera access needs HTTPS or localhost. This page is on an insecure origin, so the browser blocks the camera entirely — open the app at http://localhost instead of a LAN IP address, or serve it over HTTPS."
      );
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      cancelledRef.current = false;
      setScanning(true);
      timerRef.current = window.setTimeout(() => void scanLoopRef.current(), FIRST_CAPTURE_DELAY_MS);
    } catch (err) {
      setCameraError(describeCameraError(err));
      stopStream();
      setScanning(false);
    }
  }

  function handleStop() {
    stopStream();
    setScanning(false);
  }

  function handleReview(entry: SeenStudent, status: "present" | "absent") {
    const targetId = reassignments[entry.recordId] ?? entry.studentId;
    const studentId = targetId !== entry.studentId ? targetId : undefined;
    review.mutate(
      { recordId: entry.recordId, status, studentId },
      {
        onSuccess: () => {
          setReviewedIds((prev) => new Set(prev).add(entry.recordId));
          const map = seenRef.current;
          map.delete(entry.studentId);
          if (status === "present") {
            map.set(targetId, {
              ...entry,
              studentId: targetId,
              name: rosterName(targetId),
              needsReview: false,
              confirmed: true,
            });
          }
          commitSeen();
          pushLog([
            status === "present"
              ? {
                  kind: "confirmed",
                  text: `${rosterName(targetId)} confirmed present by teacher${
                    studentId !== undefined ? ` (corrected from ${entry.name})` : ""
                  }`,
                }
              : { kind: "rejected", text: `${entry.name} marked not present by teacher` },
          ]);
        },
      }
    );
  }

  // Switching period or date invalidates everything accumulated so far, and
  // must not keep marking against the slot the teacher just navigated away from.
  useEffect(() => {
    stopStream();
    setScanning(false);
    resetSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timetableSlotId, date]);

  // Release the camera on unmount - without this the webcam light stays on
  // after navigating away from the page.
  useEffect(() => stopStream, []);

  return (
    <div className="grid items-start gap-3 lg:grid-cols-2">
      <div className="flex flex-col gap-3">
        <Card>
          <CardHeader>
            <CardTitle>Live camera</CardTitle>
            <CardDescription>
              Captures a frame every {CAPTURE_INTERVAL_MS / 1000}s while scanning and runs face recognition on it.
              Frames are sent for recognition only — nothing is stored.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {/* A camera viewport reads as a device surface, so it stays dark in
                both themes rather than following the ink/paper tokens. */}
            <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-black/85">
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                className={cn("h-full w-full object-cover", !scanning && "opacity-0")}
              />
              {!scanning && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-white/70">
                  <CameraOff className="h-6 w-6" />
                  <span className="text-xs">Camera off — press Start to begin scanning</span>
                </div>
              )}
              {scanning && (
                <div className="absolute left-2.5 top-2.5 flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[0.6875rem] font-medium text-white">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-urgent" />
                  {mark.isPending ? "Recognizing…" : `Scanning · every ${CAPTURE_INTERVAL_MS / 1000}s`}
                </div>
              )}
              <canvas ref={canvasRef} className="hidden" />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {scanning ? (
                <Button variant="urgent" onClick={handleStop}>
                  <Square className="h-4 w-4" /> Stop scanning
                </Button>
              ) : (
                <Button onClick={handleStart}>
                  <Play className="h-4 w-4" /> Start scanning
                </Button>
              )}
              <span className="font-mono text-xs tabular-nums text-ink-muted">
                {framesProcessed} frame{framesProcessed === 1 ? "" : "s"} processed
              </span>
              {unmatchedLatest > 0 && (
                <Badge variant="warning" className="gap-1">
                  <UserX className="h-3 w-3" />
                  {unmatchedLatest} unrecognized face{unmatchedLatest === 1 ? "" : "s"}
                </Badge>
              )}
            </div>

            {cameraError && (
              <div className="flex items-start gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3.5 py-2.5 text-xs text-urgent">
                <CameraOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{cameraError}</span>
              </div>
            )}
            {stoppedReason && (
              <div className="flex items-start gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3.5 py-2.5 text-xs text-urgent">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{stoppedReason}</span>
              </div>
            )}
            {markError && !stoppedReason && (
              <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-2.5 text-xs text-warning">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Last frame failed: {markError} — still scanning, retry{" "}
                  {MAX_CONSECUTIVE_FAILURES - failuresRef.current} of {MAX_CONSECUTIVE_FAILURES}.
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {pendingReview.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Needs confirmation</CardTitle>
              <CardDescription>
                Matched, but below the confident threshold — the record exists, so confirm it or correct who it actually
                was.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {pendingReview.map((entry) => (
                <div
                  key={entry.recordId}
                  className="flex flex-col gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3.5 py-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="urgent">needs review</Badge>
                    <ConfidenceBadge confidence={entry.confidence} needsReview />
                    <span className="font-mono text-xs text-ink-muted">record #{entry.recordId}</span>
                  </div>
                  <Select
                    value={String(reassignments[entry.recordId] ?? entry.studentId)}
                    onValueChange={(v) =>
                      setReassignments((prev) => ({ ...prev, [entry.recordId]: Number(v) }))
                    }
                  >
                    <SelectTrigger className="h-8 w-full max-w-64">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {roster.map((s) => (
                        <SelectItem key={s.student_id} value={String(s.student_id)}>
                          {s.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={review.isPending}
                      onClick={() => handleReview(entry, "present")}
                    >
                      <CheckCircle2 className="h-3 w-3" /> Confirm present
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={review.isPending}
                      onClick={() => handleReview(entry, "absent")}
                    >
                      <XCircle className="h-3 w-3" /> Not present
                    </Button>
                  </div>
                </div>
              ))}
              {review.isError && (
                <p className="text-sm text-urgent">
                  {review.error instanceof ApiError ? review.error.message : "Review failed."}
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <Card>
          <CardHeader>
            <CardTitle>Class roster</CardTitle>
            <CardDescription>
              {roster.length > 0
                ? `${presentCount} of ${roster.length} seen so far`
                : "Populated from the first recognition pass."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {roster.length === 0 && (
              <p className="text-sm text-ink-muted">Start scanning to load this slot's class roster.</p>
            )}
            {roster.length > 0 && (
              <>
                <div className="h-1.5 overflow-hidden rounded-full bg-elevated">
                  <div
                    className="h-full rounded-full bg-positive transition-all duration-500"
                    style={{ width: `${(presentCount / roster.length) * 100}%` }}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  {roster.map((s) => {
                    const hit = seenById.get(s.student_id);
                    return (
                      <div
                        key={s.student_id}
                        className={cn(
                          "flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors",
                          hit ? "bg-positive/5" : "bg-elevated/30"
                        )}
                      >
                        <span className="flex items-center gap-2">
                          {hit ? (
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-positive" />
                          ) : (
                            <Circle className="h-4 w-4 shrink-0 text-ink-faint" />
                          )}
                          <span className={cn(hit ? "font-medium text-ink" : "text-ink-muted")}>{s.name}</span>
                        </span>
                        {hit ? (
                          <span className="flex items-center gap-1.5">
                            {hit.confirmed && <Badge variant="accent">confirmed</Badge>}
                            {hit.needsReview && !reviewedIds.has(hit.recordId) && (
                              <Badge variant="urgent">review</Badge>
                            )}
                            <span className="font-mono text-xs tabular-nums text-ink-muted">
                              {hit.firstSeenLabel}
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-ink-faint">not yet seen</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recognition feed</CardTitle>
            <CardDescription>Every recognition event this session, newest first.</CardDescription>
          </CardHeader>
          <CardContent>
            {log.length === 0 ? (
              <p className="text-sm text-ink-muted">Nothing recognized yet this session.</p>
            ) : (
              <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                {log.map((entry) => (
                  <div key={entry.id} className="flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm">
                    {entry.kind === "unmatched" ? (
                      <UserX className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                    ) : entry.kind === "rejected" ? (
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-urgent" />
                    ) : entry.kind === "confirmed" ? (
                      <UserCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                    ) : (
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive" />
                    )}
                    <span className={cn("flex-1", entry.kind === "unmatched" ? "text-warning" : "text-ink")}>
                      {entry.text}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-ink-faint">{entry.timeLabel}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
