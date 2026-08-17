import { useState, useRef, useEffect, useMemo } from "react";
import {
  Bot,
  User as UserIcon,
  Send,
  BookOpen,
  Sparkles,
  ChevronDown,
  Copy,
  Check,
  HelpCircle,
  TrendingUp,
  FileText,
  Clock,
  AlertCircle,
  PlusCircle,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import PageHeader from "@/components/shared/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { useTeacherBot, type TeacherAskRequest } from "@/api/hooks/useTeacherBot";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useAuthStore } from "@/store/authStore";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { Citation } from "@/api/types";
import { cn } from "@/lib/utils";

interface ChatTurn {
  id: number;
  question: string;
  answer: string | null;
  citations: Citation[];
  mode?: string;
  error: string | null;
  timestamp: Date;
}

const QUICK_ACTIONS = [
  {
    icon: Sparkles,
    label: "Create Lesson Plan",
    prompt: "Create a structured 40-minute lesson plan covering key learning objectives, activities, and an exit ticket.",
    mode: "lesson_plan",
  },
  {
    icon: HelpCircle,
    label: "Generate 5 MCQs",
    prompt: "Create 5 multiple-choice questions (MCQs) with options A-D, correct answer, and explanation from my curriculum notes.",
    mode: "quiz",
  },
  {
    icon: TrendingUp,
    label: "Summarize Performance",
    prompt: "Summarize recent academic performance, average scores, and topics needing revision for my students.",
    mode: "performance",
  },
  {
    icon: BookOpen,
    label: "Ask About My Resources",
    prompt: "What are the core concepts and key formulas covered in my uploaded unit notes?",
    mode: "resource_qa",
  },
];

/** Expandable citation component for grounded document sources */
function CitationFootnotes({ citations, turnId }: { citations: Citation[]; turnId: number }) {
  const [open, setOpen] = useState(false);
  if (!citations || citations.length === 0) return null;

  const panelId = `citations-${turnId}`;
  return (
    <div className="mt-3 border-t border-border/80 pt-2.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${open ? "Hide" : "Show"} the ${citations.length} curriculum sources`}
        className="flex items-center gap-1.5 rounded-lg text-xs font-medium text-ink-muted transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <BookOpen className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        <span>
          {citations.length} source{citations.length === 1 ? "" : "s"} from your uploaded curriculum
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>

      {open && (
        <ol id={panelId} className="mt-2.5 flex flex-col gap-2">
          {citations.map((c, idx) => (
            <li
              key={c.chunk_id || idx}
              className="rounded-xl border border-border/60 bg-elevated/40 p-3 text-xs"
            >
              <div className="flex items-center gap-1.5 font-semibold text-ink">
                <FileText className="h-3.5 w-3.5 text-accent shrink-0" />
                <span>[{idx + 1}] {c.title || "Curriculum Document"}</span>
              </div>
              <p className="mt-1 text-ink-muted leading-relaxed whitespace-pre-wrap">
                {c.snippet}…
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Formatted text message display with markdown headers, bold text, and numbered items */
function FormattedMessage({ text }: { text: string }) {
  const lines = text.split("\n");

  return (
    <div className="flex flex-col gap-1.5 text-xs sm:text-sm leading-relaxed text-ink">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <div key={i} className="h-1.5" />;
        }

        // Markdown Headings ### or ## or #
        if (trimmed.startsWith("### ")) {
          return (
            <h4 key={i} className="font-bold text-sm text-ink mt-2 mb-0.5">
              {trimmed.replace("### ", "")}
            </h4>
          );
        }
        if (trimmed.startsWith("## ")) {
          return (
            <h3 key={i} className="font-bold text-base text-ink mt-2 mb-1">
              {trimmed.replace("## ", "")}
            </h3>
          );
        }
        if (trimmed.startsWith("# ")) {
          return (
            <h2 key={i} className="font-bold text-lg text-ink mt-2.5 mb-1">
              {trimmed.replace("# ", "")}
            </h2>
          );
        }

        // Bullet points
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          return (
            <div key={i} className="flex items-start gap-2 pl-2">
              <span className="text-accent">•</span>
              <span>{renderBoldSpans(trimmed.substring(2))}</span>
            </div>
          );
        }

        // Question or Numbered lists: 1. or Question 1:
        if (/^(\d+\.|Question \d+:?)/i.test(trimmed)) {
          return (
            <div key={i} className="font-semibold text-ink pt-1.5">
              {renderBoldSpans(trimmed)}
            </div>
          );
        }

        return <p key={i}>{renderBoldSpans(line)}</p>;
      })}
    </div>
  );
}

function renderBoldSpans(line: string) {
  // Simple regex for **bold** or *italic*
  const parts = line.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return part;
  });
}

export default function TeacherAssistantBot() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const currentUser = useCurrentUser().data;
  const schoolId = currentUser?.school_id;
  const lookup = useReferenceLookup(schoolId);
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });

  // --- Dynamic Teacher Scope (Grades & Subjects) ---
  const teacherSlots = timetable.data ?? [];

  const availableGrades = useMemo(() => {
    if (!lookup.data?.classes) return [];
    const classIdsTaught = new Set<number>();
    for (const s of teacherSlots) {
      if (s.class_id) classIdsTaught.add(s.class_id);
    }
    if (user?.id) {
      const numericUserId = Number(user.id);
      for (const c of lookup.data.classes) {
        if (c.class_teacher_id === numericUserId) {
          classIdsTaught.add(c.id);
        }
      }
    }
    const grades = new Set<number>();
    for (const c of lookup.data.classes) {
      if (classIdsTaught.size === 0 || classIdsTaught.has(c.id)) {
        if (c.grade_level != null) grades.add(c.grade_level);
      }
    }
    return Array.from(grades).sort((a, b) => a - b);
  }, [lookup.data?.classes, teacherSlots, user?.id]);

  const availableSubjects = useMemo(() => {
    if (!lookup.data?.subjects) return [];
    const subjectIdsTaught = new Set<number>();
    for (const s of teacherSlots) {
      if (s.subject_id) subjectIdsTaught.add(s.subject_id);
    }
    if (subjectIdsTaught.size > 0) {
      return lookup.data.subjects.filter((s) => subjectIdsTaught.has(s.id));
    }
    return lookup.data.subjects;
  }, [lookup.data?.subjects, teacherSlots]);

  // Selected Scope Filters
  const [selectedGrade, setSelectedGrade] = useState<string>("all");
  const [selectedSubjectId, setSelectedSubjectId] = useState<string>("all");

  // Chat State
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const botMutation = useTeacherBot();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, botMutation.isPending]);

  const handleSend = async (customPrompt?: string, customMode?: string) => {
    const message = (customPrompt || draft).trim();
    if (!message || botMutation.isPending) return;

    const turnId = nextId.current++;
    const newTurn: ChatTurn = {
      id: turnId,
      question: message,
      answer: null,
      citations: [],
      mode: customMode,
      error: null,
      timestamp: new Date(),
    };

    setTurns((prev) => [...prev, newTurn]);
    if (!customPrompt) setDraft("");

    const payload: TeacherAskRequest = {
      query: message,
      grade_level: selectedGrade !== "all" ? Number(selectedGrade) : undefined,
      subject_id: selectedSubjectId !== "all" ? Number(selectedSubjectId) : undefined,
      mode: customMode,
    };

    try {
      const res = await botMutation.mutateAsync(payload);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                answer: res.answer,
                citations: res.citations || [],
                mode: res.mode,
              }
            : t
        )
      );
    } catch (err: any) {
      let errorMsg = "Failed to receive a response from the Teaching Assistant.";
      if (err instanceof ApiError) {
        if (err.status === 403) {
          errorMsg = "You do not have access to retrieve resources for this grade or subject.";
        } else if (err.status === 400) {
          errorMsg = err.message || "Please enter a valid question.";
        } else {
          errorMsg = err.message || errorMsg;
        }
      } else if (err?.message) {
        errorMsg = err.message;
      }

      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                error: errorMsg,
              }
            : t
        )
      );
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopy = (text: string, id: number) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Teacher Assistant"
        description="Plan lessons, create questions, and get help from your curriculum resources."
      />

      {/* SCOPE SELECTION & QUICK PROMPT BAR */}
      <Card className="border shadow-elevated">
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <Bot className="h-4 w-4" />
              </div>
              <span className="text-xs font-semibold text-ink">Context Scoping:</span>
            </div>

            {/* Scope Selectors */}
            <div className="flex flex-wrap items-center gap-2">
              {/* Grade Selector */}
              <div className="w-36">
                <Select value={selectedGrade} onValueChange={setSelectedGrade}>
                  <SelectTrigger className="h-8 text-xs" aria-label="Filter by Grade">
                    <SelectValue placeholder="All Grades" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Grades</SelectItem>
                    {availableGrades.map((g) => (
                      <SelectItem key={g} value={String(g)}>
                        Grade {g}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Subject Selector */}
              <div className="w-40">
                <Select value={selectedSubjectId} onValueChange={setSelectedSubjectId}>
                  <SelectTrigger className="h-8 text-xs" aria-label="Filter by Subject">
                    <SelectValue placeholder="All Subjects" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Subjects</SelectItem>
                    {availableSubjects.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Quick Action Pills */}
          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border">
            <span className="text-xs text-ink-muted font-medium">Quick Actions:</span>
            {QUICK_ACTIONS.map((action, i) => {
              const Icon = action.icon;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => handleSend(action.prompt, action.mode)}
                  disabled={botMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-elevated/40 px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:border-accent hover:bg-accent/10 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                >
                  <Icon className="h-3 w-3 text-accent" />
                  <span>{action.label}</span>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* CHAT CONTAINER */}
      <Card className="border shadow-elevated flex flex-col h-[560px]">
        {/* Messages Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-4">
          {turns.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-12 px-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent mb-3">
                <Bot className="h-7 w-7" />
              </div>
              <h3 className="font-display font-semibold text-base text-ink">
                How can I assist your teaching today?
              </h3>
              <p className="text-xs sm:text-sm text-ink-muted mt-1.5 max-w-md">
                I can craft lesson plans, generate quizzes from your uploaded notes, summarize student performance, and answer curriculum questions.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 max-w-lg w-full">
                {QUICK_ACTIONS.map((action, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSend(action.prompt, action.mode)}
                    className="flex items-center gap-2.5 rounded-xl border border-border bg-card p-3 text-left transition-all hover:border-accent hover:bg-accent/5 hover:shadow-xs group"
                  >
                    <action.icon className="h-4 w-4 text-accent shrink-0" />
                    <span className="text-xs font-medium text-ink group-hover:text-accent">
                      {action.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((turn) => (
              <div key={turn.id} className="flex flex-col gap-3">
                {/* Teacher Question */}
                <div className="flex items-start justify-end gap-2.5">
                  <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-accent px-4 py-2.5 text-xs sm:text-sm text-white shadow-xs">
                    <p className="whitespace-pre-wrap">{turn.question}</p>
                  </div>
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
                    <UserIcon className="h-4 w-4" />
                  </div>
                </div>

                {/* Assistant Answer or Loading / Error */}
                <div className="flex items-start gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-elevated border border-border text-accent">
                    <Bot className="h-4 w-4" />
                  </div>

                  <div className="flex-1 max-w-[90%] sm:max-w-[85%]">
                    {turn.error ? (
                      <div
                        role="alert"
                        className="rounded-2xl border border-urgent/30 bg-urgent/10 p-3.5 text-xs text-urgent flex items-start gap-2"
                      >
                        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>{turn.error}</span>
                      </div>
                    ) : turn.answer ? (
                      <div className="rounded-2xl border border-border bg-card p-4 shadow-xs">
                        <div className="flex items-center justify-between gap-2 pb-2 mb-2 border-b border-border/60">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-ink">Teaching Assistant</span>
                            {turn.mode && (
                              <Badge variant="outline" className="text-[10px] uppercase font-bold tracking-wider">
                                {turn.mode.replace("_", " ")}
                              </Badge>
                            )}
                          </div>

                          <div className="flex items-center gap-1.5">
                            {/* Copy button */}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleCopy(turn.answer!, turn.id)}
                              className="h-7 px-2 text-ink-muted hover:text-ink"
                              aria-label="Copy assistant answer"
                            >
                              {copiedId === turn.id ? (
                                <>
                                  <Check className="h-3 w-3 text-positive mr-1" />
                                  <span className="text-[11px] text-positive">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="h-3 w-3 mr-1" />
                                  <span className="text-[11px]">Copy</span>
                                </>
                              )}
                            </Button>

                            {/* Create Quiz Shortcut if MCQ questions detected */}
                            {turn.mode === "quiz" && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => navigate("/teacher/quizzes")}
                                className="h-7 px-2 text-[11px] text-accent gap-1 hover:bg-accent/10"
                              >
                                <PlusCircle className="h-3 w-3" />
                                <span>Open Quizzes</span>
                              </Button>
                            )}
                          </div>
                        </div>

                        {/* Formatted Content */}
                        <FormattedMessage text={turn.answer} />

                        {/* Citation Footnotes */}
                        <CitationFootnotes citations={turn.citations} turnId={turn.id} />
                      </div>
                    ) : (
                      /* Thinking / Loading skeleton */
                      <div className="flex items-center gap-2 rounded-2xl border border-border bg-card p-4 text-xs text-ink-muted shadow-xs">
                        <Clock className="h-4 w-4 animate-spin text-accent" />
                        <span>Researching curriculum and composing answer...</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Chat Input Bar */}
        <div className="p-3 sm:p-4 border-t border-border bg-elevated/20">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex items-end gap-2"
          >
            <div className="flex-1 relative">
              <Textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask your teaching assistant... (Press Enter to send, Shift+Enter for new line)"
                rows={1}
                className="min-h-[44px] max-h-32 resize-none py-3 text-xs sm:text-sm bg-card"
                disabled={botMutation.isPending}
                aria-label="Teacher Assistant Question Input"
              />
            </div>

            <Button
              type="submit"
              disabled={!draft.trim() || botMutation.isPending}
              className="h-11 px-4 shrink-0"
              aria-label="Send question"
            >
              {botMutation.isPending ? (
                <Clock className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
        </div>
      </Card>
    </div>
  );
}
