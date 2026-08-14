import PageHeader from "@/components/shared/PageHeader";
import InvigilationDuties from "@/components/exams/InvigilationDuties";

export default function InvigilationDutiesPage() {
  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="My Invigilation Duties" description="Exams you've been assigned to invigilate." />
      <InvigilationDuties />
    </div>
  );
}
