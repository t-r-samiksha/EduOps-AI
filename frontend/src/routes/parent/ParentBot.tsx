import PageHeader from "@/components/shared/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import ChatShell from "@/components/bots/ChatShell";
import { PARENT_BOT_ENDPOINT } from "@/api/hooks/useStudentBot";
import { useSelectedChild } from "@/hooks/useSelectedChild";
import type { ParentBotAskRequest } from "@/api/types";

/**
 * Parent Assistant Bot = ChatShell + the selected child's id. A CONFIG SWAP, not a
 * second chat component - which is the whole reason ChatShell was built generic-by-props
 * on Day 2 and de-student-ised before this was written.
 *
 * Shares `useSelectedChild()` with the portal page, and that selection lives in the URL,
 * so switching child on /parent/child and then opening the bot keeps the same child.
 */
export default function ParentBot() {
  const { children, selectedChildId, setSelectedChildId, selectedChild, showSelector, isLoading } =
    useSelectedChild();

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Ask about your child"
        description="Answers come from your child's own attendance, teacher remarks and fee record — nothing else."
      />

      {/* Same selector placement as the portal page so switching child is in the same
          spot on both screens. */}
      {showSelector && (
        <Card>
          <CardContent className="flex flex-col gap-2 py-3">
            <label htmlFor="bot-child-select" className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
              Asking about
            </label>
            <Select value={String(selectedChildId ?? "")} onValueChange={(v) => setSelectedChildId(Number(v))}>
              <SelectTrigger id="bot-child-select" className="w-full" aria-label="Select which child to ask about">
                <SelectValue placeholder="Select child" />
              </SelectTrigger>
              <SelectContent>
                {children.map((child) => (
                  <SelectItem key={child.id} value={String(child.id)}>
                    {child.name}
                    {child.class_name ? ` · ${child.class_name}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <Card>
          <CardContent className="py-8">
            <div className="h-24 animate-pulse rounded-xl bg-elevated/60" />
          </CardContent>
        </Card>
      ) : (
        // `key` remounts the shell when the child changes: the transcript is about ONE
        // child, so carrying answers about Aarav into a conversation about Diya would be
        // actively misleading.
        <ChatShell<ParentBotAskRequest>
          key={selectedChildId}
          endpoint={PARENT_BOT_ENDPOINT}
          extraBody={{ student_id: selectedChildId as number }}
          placeholder={
            selectedChild ? `e.g. how is ${selectedChild.name.split(" ")[0]} doing?` : "Ask about your child…"
          }
          emptyTitle={selectedChild ? `Ask about ${selectedChild.name.split(" ")[0]}` : "Ask about your child"}
          emptyHint="Try attendance, teacher remarks, or fees. The assistant only uses what the school has recorded — it won't guess, and it won't give medical or diagnostic opinions."
          citationLabel="from your child's record"
          citationFallbackTitle="School record"
          disabledReason={
            children.length === 0
              ? "Your account isn't linked to a student yet, so there's nothing to ask about. Ask the school office to link your child."
              : undefined
          }
        />
      )}
    </div>
  );
}
