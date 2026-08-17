import { useEffect, useRef, useState } from "react";
import { Bot, BookOpen, ChevronDown, Send, User as UserIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useBotAsk } from "@/api/hooks/useStudentBot";
import { ApiError } from "@/api/client";
import type { Citation } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * The shared chat surface for every RAG bot.
 *
 * GENERIC BY PROPS ON PURPOSE. The Student Doubt Bot and the Parent Assistant Bot are
 * the same interaction - ask a question, get a grounded answer with citations - so
 * they are one component configured twice, not two components kept in sync by hand.
 * Anything bot-specific (which endpoint, what the placeholder says, what scope fields
 * go in the request body) arrives as a prop. Nothing in here knows what a student is.
 */

interface ChatShellProps {
  /** e.g. "/bots/student/ask". The whole reason this component is reusable. */
  endpoint: string;
  placeholder: string;
  /** Bot-specific scope fields merged into every request body (class_id for the
   * student bot; the parent bot will send its own). */
  extraBody: Record<string, unknown>;
  /** Shown before the first question, instead of an empty void. */
  emptyHint: string;
  /** Blocks sending with an explanation - e.g. the student has no enrolled class yet,
   * so there is no class_id to scope retrieval by. */
  disabledReason?: string;
}

interface Turn {
  id: number;
  question: string;
  answer: string | null;
  citations: Citation[];
  error: string | null;
}

/** Citations as expandable footnotes - the visible proof the answer is grounded in
 * the class's own material rather than the model's general knowledge. Collapsed by
 * default so the answer stays readable; one click shows the exact retrieved text. */
function Citations({ citations, turnId }: { citations: Citation[]; turnId: number }) {
  const [open, setOpen] = useState(false);
  if (citations.length === 0) return null;

  const panelId = `citations-${turnId}`;
  return (
    <div className="mt-2.5 border-t border-border pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${open ? "Hide" : "Show"} the ${citations.length} sources for this answer`}
        className="flex items-center gap-1.5 rounded text-xs font-medium text-ink-muted transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
        <span>
          {citations.length} source{citations.length === 1 ? "" : "s"} from your class notes
        </span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>

      {open && (
        <ol id={panelId} className="mt-2 flex flex-col gap-2">
          {citations.map((citation, index) => (
            <li key={citation.chunk_id} className="rounded-lg bg-elevated/50 px-3 py-2">
              <p className="font-display text-xs font-semibold text-ink">
                [{index + 1}] {citation.title ?? "Class material"}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">{citation.snippet}…</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function ChatShell({
  endpoint,
  placeholder,
  extraBody,
  emptyHint,
  disabledReason,
}: ChatShellProps) {
  const ask = useBotAsk(endpoint);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, ask.isPending]);

  const blocked = Boolean(disabledReason);

  function send() {
    const question = draft.trim();
    if (!question || ask.isPending || blocked) return;

    const id = nextId.current++;
    setTurns((prev) => [...prev, { id, question, answer: null, citations: [], error: null }]);
    setDraft("");

    ask.mutate(
      { query: question, ...extraBody } as never,
      {
        onSuccess: (data) =>
          setTurns((prev) =>
            prev.map((t) => (t.id === id ? { ...t, answer: data.answer, citations: data.citations } : t))
          ),
        onError: (err) =>
          setTurns((prev) =>
            prev.map((t) =>
              t.id === id
                ? {
                    ...t,
                    error:
                      err instanceof ApiError
                        ? err.message
                        : "Something went wrong reaching the bot. Try again.",
                  }
                : t
            )
          ),
      }
    );
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a newline, the convention every chat UI uses.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  return (
    <Card className="flex h-[calc(100vh-13rem)] min-h-[26rem] flex-col overflow-hidden">
      <div
        className="flex-1 overflow-y-auto p-4"
        // Answers arrive asynchronously; without this a screen reader user gets no
        // announcement that the bot replied at all.
        aria-live="polite"
        aria-busy={ask.isPending}
        aria-label="Conversation"
      >
        {turns.length === 0 && !ask.isPending && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Bot className="h-8 w-8 text-ink-faint" aria-hidden="true" />
            <p className="font-display text-sm font-medium text-ink">Ask about anything you've covered in class</p>
            <p className="max-w-sm text-xs text-ink-muted">{emptyHint}</p>
          </div>
        )}

        <div className="flex flex-col gap-4">
          {turns.map((turn) => (
            <div key={turn.id} className="flex flex-col gap-2">
              <div className="flex items-start justify-end gap-2">
                <p className="max-w-[80%] rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2 text-sm text-accent-foreground">
                  {turn.question}
                </p>
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-elevated">
                  <UserIcon className="h-3.5 w-3.5 text-ink-muted" aria-hidden="true" />
                </div>
              </div>

              <div className="flex items-start gap-2">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10">
                  <Bot className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                </div>
                <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-panel px-3.5 py-2.5 shadow-panel">
                  {turn.error ? (
                    <p className="text-sm text-urgent">{turn.error}</p>
                  ) : turn.answer === null ? (
                    <span className="flex gap-1" aria-label="Thinking">
                      {[0, 150, 300].map((delay) => (
                        <span
                          key={delay}
                          className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-faint"
                          style={{ animationDelay: `${delay}ms` }}
                        />
                      ))}
                    </span>
                  ) : (
                    <>
                      <p className="whitespace-pre-line text-sm leading-relaxed text-ink">{turn.answer}</p>
                      <Citations citations={turn.citations} turnId={turn.id} />
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div ref={bottomRef} />
      </div>

      <CardContent className="border-t border-border p-3">
        {blocked ? (
          <p className="py-1 text-center text-sm text-ink-muted">{disabledReason}</p>
        ) : (
          <div className="flex items-end gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={placeholder}
              rows={1}
              aria-label="Your question"
              className="max-h-32 min-h-[2.5rem] resize-none"
            />
            <Button onClick={send} disabled={!draft.trim() || ask.isPending} size="icon" aria-label="Send question">
              <Send className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
