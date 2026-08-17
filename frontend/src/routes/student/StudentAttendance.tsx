import PageHeader from "@/components/shared/PageHeader";
import StudentAttendanceView from "@/components/attendance/StudentAttendanceView";

/** The student's own attendance. No student_id is passed - GET
 * /attendance/my-records pins a student caller to themselves. */
export default function StudentAttendance() {
  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="My Attendance"
        description="Every period, as it was recorded — by the classroom camera or by your teacher."
      />
      <StudentAttendanceView />
    </div>
  );
}
