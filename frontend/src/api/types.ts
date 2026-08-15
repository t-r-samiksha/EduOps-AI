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
}

export interface SubstitutionCandidate {
  teacher_id: number;
  score: number;
  reason: string;
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
}

export interface FeeStatusItem {
  student_id: number;
  fee_record_id: number;
  amount_due: number;
  amount_paid: number;
  due_date: string;
  status: "pending" | "partial" | "paid" | "overdue" | string;
}

export interface RemindersResult {
  sent_count: number;
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
}

// --- Exam management ---------------------------------------------------------------

export interface Exam {
  id: number;
  school_id: number;
  subject_id: number;
  class_id: number;
  academic_year: string;
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
  exam_date: string;
  start_time: string;
  end_time: string;
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
