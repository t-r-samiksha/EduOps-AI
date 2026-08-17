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

export interface FeeStatusItem {
  student_id: number;
  fee_record_id: number;
  amount_due: number;
  amount_paid: number;
  due_date: string;
  status: "pending" | "partial" | "paid" | "overdue" | string;
  fee_type: string;
}

export interface RemindersResult {
  sent_count: number;
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

export interface BotAskRequest {
  query: string;
  /** SECURITY BOUNDARY, not a filter - the backend validates this against the
   * caller's own enrollment before retrieving anything. See api-contract.md. */
  class_id: number;
  subject_id?: number;
}

export interface Citation {
  chunk_id: number;
  source_id: number;
  title: string | null;
  snippet: string;
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

// --- Classroom Stream (Person B) --------------------------------------------

export type PostType = "note" | "announcement" | "material";

export interface PostAttachment {
  id: number;
  post_id: number;
  file_name: string;
  file_url: string;
  file_type: string;
  file_size: number;
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
