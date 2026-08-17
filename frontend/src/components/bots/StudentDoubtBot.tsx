import PageHeader from "@/components/shared/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import ChatShell from "@/components/bots/ChatShell";
import { STUDENT_BOT_ENDPOINT } from "@/api/hooks/useStudentBot";
import { useTimetableActive } from "@/api/hooks/useTimetable";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";

/**
 * Student Doubt Bot = ChatShell + the student's own class_id. Everything else is the
 * shell's job; this file exists only to resolve scope and hand it over.
 *
 * WHY class_id IS RESOLVED HERE AND NOT TYPED BY THE STUDENT: it is a security
 * boundary (the backend validates it against the caller's enrollment and 403s on a
 * mismatch - see api-contract.md), so the UI must never offer it as an input. It comes
 * from the student's own active timetable, the same source the rest of their
 * dashboard uses.
 */
export default function StudentDoubtBot() {
  // A student's own /timetable/active is already scoped to them server-side, so the
  // class_id on any returned slot is by definition a class they are enrolled in.
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR, retry: false });

  const classId = timetable.data?.[0]?.class_id;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Doubt Bot"
        description="Ask about anything from your class notes. Every answer shows the notes it came from."
      />

      {timetable.isLoading ? (
        <Card>
          <CardContent className="py-8">
            <div className="h-24 animate-pulse rounded-xl bg-elevated/60" />
          </CardContent>
        </Card>
      ) : (
        <ChatShell
          endpoint={STUDENT_BOT_ENDPOINT}
          extraBody={{ class_id: classId }}
          placeholder="e.g. why do we carry the one when multiplying?"
          emptyHint="The bot only answers from material your teacher has uploaded for your class. If something isn't in your notes, it will tell you instead of guessing."
          disabledReason={
            classId === undefined
              ? "You're not enrolled in a class yet, so there are no class notes to search. Ask your teacher to add you to a class."
              : undefined
          }
        />
      )}
    </div>
  );
}
