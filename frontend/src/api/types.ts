// Types mirror docs/api-contract.md response shapes exactly (snake_case, matches wire format).

export type Severity = "normal" | "urgent";

export interface Alert {
  id: string; // composite "{source}:{entity_id}"
  source: string;
  severity: Severity;
  title: string;
  message: string;
  entity_type: string;
  entity_id: number;
  created_at: string;
  resolved: boolean;
}

export interface AlertsSummary {
  total: number;
  by_severity: Record<string, number>;
  by_source: Record<string, number>;
}

export interface TimetableSlot {
  id: number;
  day_of_week: number; // 0 = Monday
  period_number: number; // 0-indexed
  start_time: string; // "HH:MM:SS"
  end_time: string;
  subject_id: number;
  teacher_id: number;
  class_id: number;
  room_id: number;
  academic_year: string;
  is_active: boolean;
  // Enriched fields the frontend resolves for display when available.
  subject_name?: string;
  teacher_name?: string;
  room_name?: string;
  class_name?: string;
}

export interface TimetableActiveResponse extends Array<TimetableSlot> {}

export interface Remedy {
  action: string;
  quantity: number;
  detail: string;
}

export interface Finding {
  severity: "error" | "warning";
  code: string;
  subject: string | null;
  message: string;
  numbers: Record<string, number>;
  remedies: Remedy[];
  details: Record<string, unknown> | null;
}

/** POST /timetable/preflight's response shape, and also the shape of a
 * failed POST /timetable/generate's 422 `detail` - see docs/api-contract.md.
 * `stage` is null/absent when feasible; "preflight" means an arithmetic
 * check failed before the solver ran (milliseconds), "solve" means every
 * pre-flight check passed but CP-SAT itself proved infeasible. */
export interface PreflightResult {
  feasible: boolean;
  stage: "preflight" | "solve" | null;
  findings: Finding[];
}

export interface TimetableGenerateResponse {
  academic_year: string;
  slots_created: number;
  slots: TimetableSlot[];
  warnings: string[];
  findings: Finding[];
  objective_weights: Record<string, number>;
  objective_values: Record<string, number>;
}

export interface TimetableUpdateConflict {
  type: "teacher" | "room" | "class" | string;
  conflicting_slot_id: number;
  message: string;
}

export interface TimetableUpdateResponse {
  slot: TimetableSlot | null;
  conflicts: TimetableUpdateConflict[];
}

export interface EnrollResponse {
  id: number;
  student_id: number;
  enrolled_at: string;
}

export interface EnrollmentListItem {
  id: number;
  student_id: number;
  student_name: string;
  enrolled_at: string;
}

export interface AttendanceMatch {
  student_id: number;
  confidence: number;
  needs_review: boolean;
  face_location: [number, number, number, number];
  record_id: number;
  already_marked: boolean;
  student_name?: string;
}

export interface UnmatchedFace {
  face_location: [number, number, number, number];
  best_confidence: number;
}

export interface RosterStudent {
  student_id: number;
  name: string;
}

export interface MarkAttendanceResponse {
  timetable_slot_id: number;
  class_id: number;
  date: string;
  records_created: number;
  matches: AttendanceMatch[];
  unmatched_faces: UnmatchedFace[];
  class_roster: RosterStudent[];
}

export interface AttendanceSummaryItem {
  student_id: number;
  class_id: number;
  present_count: number;
  absent_count: number;
  late_count: number;
  total_records: number;
  present_pct: number;
}

export interface AttendanceSummaryResponse {
  from_date: string;
  to_date: string;
  items: AttendanceSummaryItem[];
}

export interface AttendanceRecord {
  id: number;
  student_id: number;
  class_id: number;
  timetable_slot_id: number;
  date: string;
  status: "present" | "absent" | "late";
  source: string;
  marked_at: string;
  confidence_score: number | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
}

// --- Day register, manual marking, analytics, per-student history ------------

export type AttendanceStatus = "present" | "absent" | "late";

export interface RegisterPeriod {
  timetable_slot_id: number;
  period_number: number;
  start_time: string;
  end_time: string;
  subject_id: number;
  subject_name: string;
  teacher_id: number;
  teacher_name: string;
  /** False when the period has no records at all - distinct from "everyone was absent". */
  is_marked: boolean;
  marked_count: number;
}

export interface RegisterCell {
  timetable_slot_id: number;
  record_id: number | null;
  /** null = unmarked, no record exists for this student/period/date. */
  status: AttendanceStatus | null;
  source: string | null;
  confidence_score: number | null;
  needs_review: boolean;
  reviewed_by_name: string | null;
}

export interface RegisterStudent {
  student_id: number;
  name: string;
  cells: RegisterCell[];
  present_count: number;
  absent_count: number;
  late_count: number;
  unmarked_count: number;
  /** Of periods actually marked - unmarked periods are out of the denominator. */
  present_pct: number;
}

export interface RegisterTotals {
  roster_size: number;
  period_count: number;
  marked_periods: number;
  unmarked_periods: number;
  present_cells: number;
  absent_cells: number;
  late_cells: number;
  unmarked_cells: number;
  present_pct: number;
}

export interface AttendanceRegisterResponse {
  class_id: number;
  class_name: string;
  grade_level: number | null;
  grade_label: string | null;
  section: string | null;
  date: string;
  day_of_week: number;
  academic_year: string;
  periods: RegisterPeriod[];
  students: RegisterStudent[];
  totals: RegisterTotals;
}

export interface ManualMarkEntry {
  student_id: number;
  timetable_slot_id: number;
  status: AttendanceStatus;
}

export interface ManualMarkResponse {
  created: number;
  updated: number;
  unchanged: number;
  records: AttendanceRecord[];
}

export interface AttendanceBucket {
  present_count: number;
  absent_count: number;
  late_count: number;
  total_records: number;
  present_pct: number;
}

export interface PeriodBucket extends AttendanceBucket {
  period_number: number;
}

export interface DayBucket extends AttendanceBucket {
  date: string;
  day_of_week: number;
}

export interface ClassBucket extends AttendanceBucket {
  class_id: number;
  class_name: string;
  grade_level: number | null;
  grade_label: string | null;
  section: string | null;
}

export interface SubjectBucket extends AttendanceBucket {
  subject_id: number;
  subject_name: string;
}

export interface StudentBucket extends AttendanceBucket {
  student_id: number;
  name: string;
  class_id: number;
  class_name: string;
  section: string | null;
  /** Newer half of the window minus the older half, in percentage points. */
  trend_delta: number;
  trend: "rising" | "flat" | "falling";
}

export interface AttendanceAnalyticsResponse {
  from_date: string;
  to_date: string;
  overall: AttendanceBucket;
  by_period: PeriodBucket[];
  by_day: DayBucket[];
  by_class: ClassBucket[];
  by_subject: SubjectBucket[];
  students: StudentBucket[];
  roster_size: number;
  below_pct_count: number;
}

export interface MyRecordPeriod {
  timetable_slot_id: number | null;
  period_number: number | null;
  start_time: string | null;
  end_time: string | null;
  subject_name: string | null;
  teacher_name: string | null;
  status: AttendanceStatus;
  source: string;
  marked_at: string;
}

export interface MyRecordDay {
  date: string;
  day_of_week: number;
  periods: MyRecordPeriod[];
  present_count: number;
  total_count: number;
  present_pct: number;
}

export interface MyAttendanceRecordsResponse {
  student_id: number;
  student_name: string;
  class_id: number | null;
  class_name: string | null;
  from_date: string;
  to_date: string;
  summary: AttendanceBucket;
  /** Newest day first. */
  days: MyRecordDay[];
}

// --- Fee payment confirmation loop ------------------------------------------

export type PaymentMethod = "UPI" | "Bank Transfer" | "Cash" | "Other";
export const PAYMENT_METHODS: PaymentMethod[] = ["UPI", "Bank Transfer", "Cash", "Other"];

export type PaymentRequestStatus = "pending" | "confirmed" | "rejected";

/** What the parent sees, folding an open or recently-rejected claim into the canonical
 * record status. `paid` is the ONLY settled state — anything short of the full amount
 * stays visible as incomplete until it is settled. */
export type DerivedFeeStatus = "unpaid" | "partially_paid" | "payment_pending" | "paid" | "rejected";

export interface FeePaymentRequestSummary {
  id: number;
  fee_record_id: number;
  amount: number;
  payment_method: string;
  payment_reference: string;
  status: PaymentRequestStatus;
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  has_proof: boolean;
}

export interface ParentFeeItem {
  fee_record_id: number;
  fee_type: string;
  amount_due: number;
  amount_paid: number;
  outstanding: number;
  due_date: string;
  /** The canonical fee_records.status. */
  record_status: string;
  derived_status: DerivedFeeStatus;
  request: FeePaymentRequestSummary | null;
}

export interface ParentFeesResponse {
  student_id: number;
  student_name: string;
  items: ParentFeeItem[];
}

export interface FeePaymentRequestItem {
  id: number;
  fee_record_id: number;
  student_id: number;
  student_name: string;
  class_name: string | null;
  parent_id: number;
  parent_name: string;
  fee_type: string;
  amount: number;
  amount_due: number;
  amount_paid: number;
  outstanding: number;
  payment_method: string;
  payment_reference: string;
  has_proof: boolean;
  status: PaymentRequestStatus;
  submitted_at: string;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
}

export interface FeePaymentRequestQueue {
  items: FeePaymentRequestItem[];
  /** Total pending for the school, ignoring any status filter - so the dashboard
   * badge and a filtered queue view can share one request. */
  pending_count: number;
}

export interface ConfirmPaymentRequestResult {
  request: FeePaymentRequestItem;
  fee_record: PaymentResult;
}

// --- Doubt threads ----------------------------------------------------------

export interface ThreadReply {
  id: number;
  thread_id: number;
  author_id: number;
  author_name: string;
  body: string;
  created_at: string;
  /** The reply a teacher certified as the answer. Flagged in place so the UI can pin
   * it without cross-referencing verified_reply_id. */
  is_verified: boolean;
}

export interface DoubtThread {
  id: number;
  school_id: number;
  class_id: number;
  class_name: string | null;
  subject_id: number | null;
  title: string;
  body: string;
  author_id: number;
  author_name: string;
  resolved: boolean;
  verified_reply_id: number | null;
  reply_count: number;
  created_at: string;
  verified_reply: ThreadReply | null;
}

export interface DoubtThreadDetail extends DoubtThread {
  /** Chronological. */
  replies: ThreadReply[];
}

export interface ThreadVerifyResult {
  thread: DoubtThreadDetail;
  chunks_written: number;
  /** Human-readable confirmation that the answer reached the bot's knowledge base —
   * the causal link a reader needs to see, so it is rendered inline and stays put. */
  kb_note: string;
}

export interface ThreadUnverifyResult {
  thread: DoubtThreadDetail;
  chunks_deleted: number;
}

// --- Staffing & Substitutes -------------------------------------------------

export interface LeaveRequest {
  id: number;
  teacher_id: number;
  start_date: string;
  end_date: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  requested_at: string;
  decided_by: number | null;
  decided_at: string | null;
  /** The approver's note back to the teacher. Null while pending, or when the
   * approver left the Approvals Inbox comment box blank. */
  decision_comment: string | null;
}

export interface SubstitutionCandidate {
  teacher_id: number;
  score: number;
  reason: string;
  /** False only for automatic fallback suggestions - a real teacher surfaced
   * because nobody qualified for the subject was free at all (supervision-only
   * cover). Render distinctly from a normal qualified candidate. */
  qualified: boolean;
}

export interface Substitution {
  id: number | null;
  leave_request_id: number | null;
  timetable_slot_id: number;
  original_teacher_id: number;
  substitute_teacher_id: number | null;
  status: "suggested" | "confirmed" | null;
  suggested_score: number | null;
  confirmed_at: string | null;
  subject_id: number;
  class_id: number;
  day_of_week: number;
  period_number: number;
  candidates: SubstitutionCandidate[];
}

export interface MySubstituteDuty {
  substitution_id: number;
  leave_request_id: number;
  original_teacher_id: number;
  subject_id: number;
  class_id: number;
  day_of_week: number;
  period_number: number;
  status: "suggested" | "confirmed";
  leave_start_date: string;
  leave_end_date: string;
}

export interface ApproveLeaveResponse {
  leave_request: LeaveRequest;
  substitutions: Substitution[];
}

export interface SuggestSubstitutionsResponse {
  substitutions: Substitution[];
}

export interface ConfirmSubstitutionConflict {
  type: string;
  message: string;
  /** True only for "not_qualified" - a preference/quality concern (supervision-
   * only cover), not a scheduling/physical impossibility. See useConfirmSubstitution's
   * overrideQualification param. */
  overridable: boolean;
}

export interface ConfirmSubstitutionResponse {
  substitution: Substitution | null;
  conflicts: ConfirmSubstitutionConflict[];
  class_id: number | null;
  class_name: string | null;
  subject_name: string | null;
  original_teacher_name: string | null;
  substitute_teacher_name: string | null;
  affected_student_ids: number[];
  leave_start_date: string | null;
  leave_end_date: string | null;
}

export interface ForecastDay {
  date: string;
  predicted_absences: number;
  risk_level: string;
}

export interface StaffingForecast {
  school_id: number;
  week_start: string;
  forecast: ForecastDay[];
  data_sufficient: boolean;
  /** False when fewer than a handful of real approved leave requests exist
   * historically - a school with e.g. exactly one ever-approved leave can
   * mathematically produce a full week of numbers, but that's one data
   * point, not a real pattern. Render an explicit "not enough data" state
   * instead of a flat, confidently-styled risk_level when this is false. */
}

export interface SlotSuggestion {
  timetable_slot_id: number;
  subject_id: number;
  class_id: number;
  period_number: number;
  suggestions: SubstitutionCandidate[];
}

export interface SubstituteSuggestionsResponse {
  absent_teacher_id: number;
  date: string;
  slots: SlotSuggestion[];
}

// --- Early-Warning / Risk ----------------------------------------------------

export interface RiskFlag {
  id: number;
  student_id: number;
  risk_level: "low" | "medium" | "high";
  score: number;
  reasons: string[];
  flagged_at: string;
  status: "open" | "acknowledged" | "resolved";
  resolved_by: number | null;
  resolved_at: string | null;
  class_id: number | null;
  class_name: string | null;
  homeroom_teacher_id: number | null;
  parent_ids: number[];
  student_name: string | null;
}

export interface Intervention {
  id: number;
  risk_flag_id: number;
  created_by: number;
  /** Who logged it, resolved server-side on the list endpoint so the panel does not need a
   *  lookup per row. Null on the create response, where the caller is the actor. */
  created_by_name?: string | null;
  note: string;
  action_taken: string;
  created_at: string;
}

// --- Syllabus tracking --------------------------------------------------------

export interface SyllabusPlan {
  id: number;
  class_id: number;
  subject_id: number;
  academic_year: string;
  total_units: number;
  term_start_date: string;
  term_end_date: string;
  created_by: number;
  created_at: string;
}

export interface SyllabusCheckpoint {
  id: number;
  plan_id: number;
  topic_label: string;
  sequence_number: number;
  logged_by: number;
  logged_at: string;
}

export interface SyllabusSummaryItem {
  plan_id: number;
  class_id: number;
  class_name: string;
  subject_id: number;
  subject_name: string;
  academic_year: string;
  total_units: number;
  checkpoints_logged: number;
  term_start_date: string;
  term_end_date: string;
  expected_fraction: number;
  actual_fraction: number;
  drift: number;
  status: "on_pace" | "behind" | "ahead";
}

// --- Approvals -----------------------------------------------------------------

export interface Approval {
  id: string; // composite "{type}:{entity_id}"
  type: "leave_request" | "admission_application" | string;
  requested_by: number;
  requested_at: string;
  payload: Record<string, unknown>;
  entity_type: string;
  entity_id: number;
}

// --- Parent -----------------------------------------------------------------

export interface LinkedChild {
  id: number;
  name: string;
  class_id: number | null;
  class_name: string | null;
}

// --- Document OCR --------------------------------------------------------------

export type DocumentType = "marksheet" | "admission_form" | "id_proof" | "other";
export type DocumentStatus = "queued" | "processing" | "done" | "failed";

export interface DocumentCreateResult {
  id: number;
  school_id: number | null;
  document_type: DocumentType;
  status: DocumentStatus;
  uploaded_at: string;
}

export interface DocumentSummary {
  id: number;
  school_id: number | null;
  document_type: DocumentType;
  status: DocumentStatus;
  uploaded_at: string;
  processed_at: string | null;
  /** Set once this document is linked into some AdmissionApplication's
   * ocr_document_ids - null if still unlinked. Lets the document list group/nest
   * documents by application without a detail fetch per row. */
  application_id: number | null;
  /** The linked application's real applicant_name - null exactly when
   * application_id is null. Always the one canonical name off the application
   * itself, not this document's own extracted fields (a marksheet says
   * student_name, an id_proof says full_name - not necessarily identical). */
  application_applicant_name: string | null;
}

export interface DocumentsListResponse {
  items: DocumentSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExtractedEntity {
  id: number;
  field_name: string;
  field_value: string;
  confidence_score: number;
  is_low_confidence: boolean;
  corrected_value: string | null;
  corrected_by: number | null;
  corrected_at: string | null;
}

export interface DocumentRouting {
  routed: boolean;
  target_table: string | null;
  reason: string;
  /** Only set when routed=true - a pre-filled POST /admin/admissions/applications
   * body (applicant_name/dob/guardian_email/grade_applied/school_id/
   * ocr_document_ids). Never auto-submitted - present it for a human to review
   * and submit for real. academic_year is deliberately absent (never printed on
   * the physical form) and must be supplied by whoever reviews this. */
  suggested_payload: {
    applicant_name: string;
    dob: string;
    guardian_email: string;
    /** Only present when OCR actually found them (not in REQUIRED_ADMISSION_FIELDS,
     * so a form missing these still routes) - real fix for parent accounts
     * created with no name (see AdmissionApplication.guardian_name's docstring). */
    guardian_name?: string;
    guardian_phone?: string;
    grade_applied: string;
    school_id: number;
    ocr_document_ids: number[];
  } | null;
}

export interface DocumentDetail {
  id: number;
  school_id: number | null;
  document_type: DocumentType;
  status: DocumentStatus;
  uploaded_at: string;
  processed_at: string | null;
  extracted_fields: Record<string, string>;
  entities: ExtractedEntity[];
  /** Every field this document_type's extraction rules look for, regardless of
   * whether OCR found it here - diff against extracted_fields's keys to find
   * fields that are genuinely missing (not just low-confidence), e.g. a garbled
   * "Total Marks" line that never matched at all. */
  expected_fields: string[];
  application_id: number | null;
  application_applicant_name: string | null;
  raw_text: string | null;
  ocr_confidence: number | null;
  routing: DocumentRouting | null;
  error: string | null;
}

// --- Fees ----------------------------------------------------------------------

export interface FeeSchedule {
  id: number;
  school_id: number;
  class_id: number | null;
  academic_year: string;
  fee_type: string;
  amount: number;
  due_date: string;
  created_at: string;
  records_generated: boolean;
}

export interface FeeStatusClaim {
  id: number;
  status: PaymentRequestStatus;
  amount: number;
  payment_method: string;
  payment_reference: string;
  submitted_at: string;
  rejection_reason: string | null;
  has_proof: boolean;
}

export interface FeeStatusItem {
  student_id: number;
  fee_record_id: number;
  amount_due: number;
  amount_paid: number;
  outstanding: number;
  due_date: string;
  /** The canonical fee_records.status — knows nothing about payment claims. */
  status: "pending" | "partial" | "paid" | "overdue" | string;
  fee_type: string;
  /** The open claim against this fee, else the most recent closed one. Without
   * this, staff saw "overdue" on a fee a parent had already reported paying. */
  claim: FeeStatusClaim | null;
}

export interface RemindersResult {
  sent_count: number;
}

export interface ReminderTierBucket {
  cadence_reason: string;
  severity: "normal" | "urgent" | string;
  count: number;
}

/** Dry run of a reminder trigger — what it would do and why. Exists because
 * "0 reminder(s) recorded as due" is indistinguishable from a broken button. */
export interface RemindersPreview {
  /** Records matching the status filter, before the day-tier gate. */
  in_scope: number;
  due_now: number;
  by_tier: ReminderTierBucket[];
  /** Due today or later — can never produce a reminder whatever the scope says. */
  not_yet_due: number;
  waiting_for_next_tier: number;
  fully_escalated: number;
  next_due_date: string | null;
  next_due_count: number;
}

export interface InvoicingRunResult {
  records_created: number;
  overdue_marked: number;
  reminders_sent: number;
}

export interface PaymentResult {
  fee_record_id: number;
  amount_paid: number;
  amount_due: number;
  status: string;
}

// --- Admissions ------------------------------------------------------------------

export type AdmissionStatus = "submitted" | "under_review" | "accepted" | "rejected";

export interface AdmissionApplication {
  id: number;
  school_id: number;
  academic_year: string;
  applicant_name: string;
  dob: string;
  guardian_email: string;
  /** Real fields now (found live: parent accounts created without a name because
   * these never reached that far) - optional since not every submission path
   * captures them (the Submit tab's own form, no document involved, doesn't ask). */
  guardian_name: string | null;
  guardian_phone: string | null;
  /** A stringified grade LEVEL (e.g. "3", "-2" for LKG) - never a section name.
   * Use gradeLevelDisplay() (lib/format.ts) to render, never prefix with "Grade "
   * yourself - see that helper's docstring for the bug this replaced. */
  grade_applied: string;
  ocr_document_ids: number[];
  status: AdmissionStatus;
  submitted_by: number;
  submitted_at: string;
  decided_by: number | null;
  decided_at: string | null;
  decision_justification: string | null;
  enrolled_student_id: number | null;
}

/** GET /admin/admissions/applications/{id}'s response shape - adds full detail
 * for EVERY linked document (not just the ids in ocr_document_ids), so the
 * applicant detail view can show the admission form, marksheet, and ID proof
 * together without a round-trip per document. Same DocumentDetail shape
 * GET /admin/ocr/documents/{id} returns for one document. */
export interface AdmissionApplicationDetail extends AdmissionApplication {
  documents: DocumentDetail[];
}

export interface AdmissionsListResponse {
  items: AdmissionApplication[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdmissionDecisionResult {
  id: number;
  status: AdmissionStatus;
  enrollment_created: boolean;
  /** Set only on a successful acceptance - the real, auto-assigned section. */
  assigned_class_id: number | null;
  enrolled_student_id: number | null;
  parent_user_id: number | null;
  /** True iff accepting created a BRAND NEW parent account (guardian_email
   * didn't already belong to one) - False when an existing parent (e.g. a
   * sibling's application) was found and reused instead. */
  parent_account_created: boolean;
}

export interface GradeLevelOption {
  grade_level: number;
  display: string;
}

export interface GradeLevelsResponse {
  items: GradeLevelOption[];
}

// --- Exam management ---------------------------------------------------------------

export type ExamType = "class_test" | "unit_test" | "mid_term" | "end_term";

export interface Exam {
  id: number;
  school_id: number;
  subject_id: number;
  class_id: number;
  academic_year: string;
  exam_type: ExamType | null;
  exam_date: string;
  start_time: string;
  end_time: string;
  total_marks: number | null;
  created_at: string;
}

export interface ExamListItem {
  id: number;
  subject_id: number;
  class_id: number;
  academic_year: string;
  exam_type: ExamType | null;
  exam_date: string;
  start_time: string;
  end_time: string;
}

export interface RoomSuggestionItem {
  room_id: number;
  room_name: string;
  capacity: number;
}

export interface RoomSuggestionsResult {
  exam_id: number;
  headcount: number;
  available_rooms: RoomSuggestionItem[];
  suggested_room_ids: number[];
}

export interface ExamsListResponse {
  items: ExamListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface SeatAssignment {
  student_id: number;
  room_id: number;
  seat_no: number;
}

export interface InvigilatorAssignment {
  room_id: number;
  teacher_id: number | null;
}

export interface GenerateSchedulesResult {
  exam_id: number;
  status: string;
  seating: SeatAssignment[];
  invigilators: InvigilatorAssignment[];
  unassigned_rooms: number[];
}

export interface SeatingItem {
  exam_id: number;
  student_id: number;
  room_id: number;
  room_name: string;
  seat_no: number;
  subject_id: number;
  subject_name: string;
  exam_type: ExamType | null;
  exam_date: string;
  class_id: number;
  class_name: string;
  invigilator_teacher_id: number | null;
  invigilator_name: string | null;
}

export interface SeatingResponse {
  exam_id: number | null;
  items: SeatingItem[];
}

export interface InvigilationDuty {
  exam_id: number;
  room_id: number;
  room_name: string;
  subject_id: number;
  subject_name: string;
  class_id: number;
  class_name: string;
  exam_date: string;
  start_time: string;
  end_time: string;
  status: string;
}

// --- Notification center ---------------------------------------------------
// Hand-written, like everything else in this file - there is no codegen here.
// Mirrors app/routers/notifications.py's NotificationOut / NotificationPage.

/** One of app/models/notification.py's SOURCE_TYPES. Kept as a union so the
 * bell's icon map is exhaustive-checked, with a string fallback so a new
 * backend source_type renders with a default icon instead of crashing. */
export type NotificationSourceType =
  | "early_warning"
  | "fee_reminder"
  | "fee_payment_request"
  | "fee_payment_confirmed"
  | "fee_payment_rejected"
  | "report_card"
  | "substitute_assigned"
  | "announcement"
  | "remark_posted"
  | "leave_decision"
  | "admission_decision";

export type NotificationPriority = "normal" | "important" | "urgent";

export interface Notification {
  id: number;
  source_type: NotificationSourceType | string;
  source_id: number | null;
  title: string;
  body: string | null;
  priority: NotificationPriority | string;
  /** null = unread */
  read_at: string | null;
  acknowledged_at: string | null;
  created_at: string;
}

export interface NotificationPage {
  items: Notification[];
  total: number;
  page: number;
  page_size: number;
}

export interface UnreadCountResponse {
  count: number;
}

/** Payload pushed by GET /notifications/stream. */
export interface NotificationStreamSnapshot {
  unread_count: number;
  latest: Notification[];
}

// --- RAG chatbots ----------------------------------------------------------
// Mirrors app/routers/bots.py's StudentAskRequest / StudentAskResponse.

/**
 * Bot request bodies, as a DISCRIMINATED UNION rather than one loose interface.
 *
 * The two bots scope on different things and neither field is optional for its own
 * bot: the student bot must send `class_id` (validated against enrollment), the parent
 * bot must send `student_id` (validated against parent_student). A single interface
 * with both fields optional would compile happily for a request that carried neither -
 * which is exactly the shape the `as never` cast in ChatShell used to hide.
 */
export interface StudentBotAskRequest {
  query: string;
  /** SECURITY BOUNDARY, not a filter - the backend validates this against the
   * caller's own enrollment before retrieving anything. See api-contract.md. */
  class_id: number;
  subject_id?: number;
}

export interface ParentBotAskRequest {
  query: string;
  /** SECURITY BOUNDARY - validated with assert_parent_linked on every request. The
   * frontend child selector is never trusted. */
  student_id: number;
}

export type BotAskRequest = StudentBotAskRequest | ParentBotAskRequest;

export interface Citation {
  chunk_id: number;
  source_id: number;
  title: string | null;
  snippet: string;
  /** Which kind of thing was cited: `resource` for an uploaded document,
   * `verified_doubt_answer` for a reply a teacher marked verified in a doubt thread.
   * The footnote label depends on it — calling a teacher's verified answer a "class
   * note" would be untrue, and would bury the fact that makes the feature legible. */
  source_type: "resource" | "verified_doubt_answer" | string;
}

export interface BotAskResponse {
  answer: string;
  citations: Citation[];
}

// --- Top Doubts (bot insights) ---------------------------------------------
// Mirrors app/routers/bots.py's DoubtClusterOut / MyTopDoubtsResponse.

export interface DoubtCluster {
  /** Null in degraded mode (fewer than 3 clusterable logs) or if Gemini labelling
   * failed - the UI must render the sample question instead, never "null". */
  label: string | null;
  description: string | null;
  question_count: number;
  distinct_student_count: number;
  /** Class names contributing. More than one = the cross-section insight. */
  sections: string[];
  sample_questions: string[];
}

export interface GradeSubjectDoubts {
  grade_level: number;
  subject_id: number;
  subject_name: string;
  clusters: DoubtCluster[];
}

export interface MyTopDoubtsResponse {
  items: GradeSubjectDoubts[];
}

// --- Parent portal: GET /parent/child/{id}/summary -------------------------
// One round trip for the whole portal page. Mirrors app/routers/parent.py's
// ChildSummaryResponse.

export interface ChildSummaryStudent {
  id: number;
  name: string;
  class_id: number | null;
  class_name: string | null;
  grade_level: number | null;
}

export interface ChildSummaryAttendance {
  present_pct: number;
  /** "Last 30 days" — shown beside the figure so the portal and the report card read
   *  as two measures rather than a discrepancy. See services/attendance_stats.py. */
  window_label?: string;
  present_count: number;
  absent_count: number;
  late_count: number;
  /** Window in CALENDAR days, matching the risk scorer's lookback so the banner and
   * this card can never quote different attendance figures. */
  days: number;
}

export interface ChildSummaryRisk {
  level: string;
  score: number;
  /** Already-human-readable strings from the nightly scorer - render them verbatim. */
  reasons: string[];
  flagged_at: string;
}

export interface ChildSummaryRemark {
  id: number;
  teacher_name: string | null;
  remark_text: string;
  /** `compound` is -1..+1. Drives visual weight, not just a label. */
  sentiment: { label: string; compound: number };
  created_at: string;
}

export interface ChildSummaryFee {
  fee_record_id: number;
  fee_type: string;
  amount_due: number;
  amount_paid: number;
  status: string;
  due_date: string;
}

export interface ChildSummary {
  student: ChildSummaryStudent;
  attendance: ChildSummaryAttendance;
  /** null = healthy. Hide the banner entirely rather than rendering an empty one. */
  risk: ChildSummaryRisk | null;
  remarks: ChildSummaryRemark[];
  fees: ChildSummaryFee[];
  upcoming: { type: string; title: string; date: string }[];
}

// --- Classroom Stream (Person B) --------------------------------------------

export type PostType = "note" | "announcement" | "material";

export interface PostAttachment {
  id: number;
  post_id: number;
  file_name: string;
  /** Object PATH inside a PRIVATE bucket, NOT a link - never put this in an href.
   *  Download via GET /classroom/attachments/{id}/download (see useFileDownload). */
  file_url: string;
  file_type: string;
  file_size: number;
  /** The library `resources` row this file was indexed as, so the Doubt Bot can answer
   *  from it. Null for images (no extractable text) and for files uploaded before
   *  classroom posts fed the knowledge base. */
  resource_id: number | null;
  created_at: string;
}

export interface PostAuthor {
  id: number;
  full_name: string | null;
  email: string | null;
  role?: string | null;
}

export interface StreamPost {
  id: number;
  classroom_id: number;
  author_id: number;
  author: PostAuthor | null;
  post_type: PostType;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  attachments: PostAttachment[];
  /** Notes from adding this post's files to the bots' knowledge base. Only present on the
   *  create response, and empty on the happy path - a post whose attachment could not be
   *  indexed still succeeds (losing a teacher's post to an unparseable PDF would be worse),
   *  so this is how they find out the bot cannot read it yet. */
  indexing_warnings?: string[];
}

export interface Classroom {
  id: number;
  school_id: number;
  class_id: number;
  class_name: string;
  subject_id: number;
  subject_name: string | null;
  teacher_id: number;
  teacher_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface StreamResponse {
  classroom: Classroom;
  items: StreamPost[];
}

export interface CreateAttachmentInput {
  file_name: string;
  file_url: string;
  file_type: string;
  file_size: number;
}

export interface CreatePostRequest {
  post_type: PostType;
  title: string;
  content: string;
  attachments?: CreateAttachmentInput[];
  /** File the attachments in the resource library for the whole GRADE (default) rather than
   *  only this class section. Grade-wide because a Grade 3-B Math worksheet is nearly always
   *  just as useful to Grade 3-A Math, and grade is the unit bot retrieval scopes by. Does
   *  not affect who sees the stream post itself. */
  share_with_grade?: boolean;
}

export interface UploadAttachmentResponse {
  file_name: string;
  file_url: string;
  file_type: string;
  file_size: number;
}

// --- Resources Library (Person B) -------------------------------------------

export interface ResourceItem {
  id: number;
  title: string;
  description: string | null;
  unit: string | null;
  school_id: number;
  grade_level: number;
  class_id: number | null;
  class_name: string | null;
  subject_id: number | null;
  subject_name: string | null;
  teacher_id: number;
  teacher_name: string | null;
  file_url: string;
  mime_type: string;
  file_size: number;
  needs_reindex: boolean;
  indexed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface ResourceUploadResponse extends ResourceItem {
  chunk_count: number;
}

export interface ResourceListResponse {
  items: ResourceItem[];
}

export interface UnitsListResponse {
  units: string[];
}

export interface ResourceFilters {
  class_id?: number;
  grade_level?: number;
  subject_id?: number;
  unit?: string;
  file_type?: string;
  q?: string;
}

// --- Assignments & Submissions (Person B) -----------------------------------

export type SubmissionStatus = "submitted" | "late" | "missing" | "graded" | "pending";

export interface SubmissionItem {
  id: number;
  assignment_id: number;
  student_id: number;
  student_name: string | null;
  student_email: string | null;
  file_url: string | null;
  file_name: string | null;
  file_size: number;
  grade: number | null;
  feedback: string | null;
  status: SubmissionStatus;
  submitted_at: string | null;
  graded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssignmentStats {
  enrolled_count: number;
  submitted_count: number;
  late_count: number;
  missing_count: number;
  graded_count: number;
  average_grade: number | null;
}

export interface AssignmentItem {
  id: number;
  school_id: number;
  class_id: number;
  class_name: string | null;
  subject_id: number | null;
  subject_name: string | null;
  teacher_id: number;
  teacher_name: string | null;
  title: string;
  description: string | null;
  deadline: string;
  max_marks: number;
  attachment_url: string | null;
  attachment_name: string | null;
  created_at: string;
  updated_at: string;
  stats?: AssignmentStats | null;
  my_submission?: SubmissionItem | null;
}

export interface CreateAssignmentRequest {
  class_id: number;
  subject_id?: number;
  title: string;
  description?: string;
  deadline: string;
  max_marks?: number;
  attachment_url?: string;
  attachment_name?: string;
}

export interface SubmitAssignmentRequest {
  file_url: string;
  file_name?: string;
  file_size?: number;
}

export interface GradeSubmissionRequest {
  grade: number;
  feedback?: string;
}

// --- Announcements (Person C) ------------------------------------------------
// A source that routes through the existing notification dispatch, not a second
// inbox — see backend/app/services/announcements.py. `scope_label` and
// `related_children` are both resolved server-side so the UI renders the same
// targeting the backend enforced, rather than recomputing it and drifting.

export type AnnouncementScope = "school" | "grade" | "class";
export type AnnouncementCategory = "event" | "academic" | "fee" | "general";
export type AnnouncementPriority = "normal" | "important" | "urgent";

export interface AnnouncementChild {
  id: number;
  name: string | null;
}

export interface Announcement {
  id: number;
  title: string;
  body: string;
  category: AnnouncementCategory;
  priority: AnnouncementPriority;
  scope_type: AnnouncementScope;
  scope_grade_level: number | null;
  scope_class_id: number | null;
  /** "School" / "Grade 3" / "Grade 3 - A" — resolved server-side. */
  scope_label: string;
  author_id: number;
  author_name: string | null;
  created_at: string;
  acknowledged: boolean;
  acknowledged_at: string | null;
  /** Parents only: which of THEIR children this relates to. Empty for a school-wide
   * item (it relates to everyone) and for every non-parent role. */
  related_children: AnnouncementChild[];
}

export interface AnnouncementFeed {
  items: Announcement[];
  unacknowledged_count: number;
}

export interface AnnouncementCreateRequest {
  scope_type: AnnouncementScope;
  scope_grade_level?: number | null;
  scope_class_id?: number | null;
  title: string;
  body: string;
  category: AnnouncementCategory;
  priority: AnnouncementPriority;
}

export interface AnnouncementCreateResult {
  announcement: Announcement;
  /** Notifications actually dispatched — the author's reach, shown immediately. */
  recipients: number;
}

export interface AckPerson {
  user_id: number;
  name: string | null;
  role: string | null;
  acknowledged_at?: string | null;
}

export interface AnnouncementAckStatus {
  announcement_id: number;
  audience_size: number;
  acknowledged_count: number;
  acknowledged_pct: number;
  acknowledged: AckPerson[];
  outstanding: AckPerson[];
}
