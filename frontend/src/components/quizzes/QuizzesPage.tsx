import { useState, useEffect } from "react";
import {
  HelpCircle,
  Plus,
  Clock,
  CheckCircle2,
  Sparkles,
  BarChart3,
  Award,
  Play,
  BookOpen,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useQuizzes,
  useQuizDetail,
  useCreateQuiz,
  useSubmitQuizAttempt,
  useQuizResults,
  Question,
} from "@/api/hooks/useQuizzes";
import { useAuthStore } from "@/store/authStore";

export default function QuizzesPage() {
  const { role } = useAuthStore();
  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const { data: quizzes = [], isLoading } = useQuizzes();
  const createQuizMutation = useCreateQuiz();
  const submitAttemptMutation = useSubmitQuizAttempt();

  // Create Quiz Modal State
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const newClassId = 1;
  const [newDuration, setNewDuration] = useState("30");
  const [newQuestions, setNewQuestions] = useState<Question[]>([
    {
      question_text: "",
      option_a: "",
      option_b: "",
      option_c: "",
      option_d: "",
      correct_option: "A",
      marks: 1.0,
      order_index: 0,
    },
  ]);

  // Taking Quiz State
  const [activeQuizId, setActiveQuizId] = useState<number | null>(null);
  const { data: activeQuiz } = useQuizDetail(activeQuizId ?? undefined);
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, string>>({});
  const [timeLeft, setTimeLeft] = useState<number>(0);
  const [quizFinished, setQuizFinished] = useState<boolean>(false);
  const [latestAttemptResult, setLatestAttemptResult] = useState<any>(null);

  // Results Modal State (Teacher)
  const [resultsQuizId, setResultsQuizId] = useState<number | null>(null);
  const { data: quizResults } = useQuizResults(resultsQuizId ?? undefined);

  // Timer logic for quiz taking
  useEffect(() => {
    if (!activeQuizId || !activeQuiz || quizFinished) return;
    if (activeQuiz.my_attempt) {
      setQuizFinished(true);
      setLatestAttemptResult(activeQuiz.my_attempt);
      return;
    }

    setTimeLeft(activeQuiz.duration_minutes * 60);
    const interval = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          handleAutoSubmit();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [activeQuizId, activeQuiz]);

  const handleAddQuestion = () => {
    setNewQuestions((prev) => [
      ...prev,
      {
        question_text: "",
        option_a: "",
        option_b: "",
        option_c: "",
        option_d: "",
        correct_option: "A",
        marks: 1.0,
        order_index: prev.length,
      },
    ]);
  };

  const handleQuestionChange = (index: number, field: keyof Question, value: any) => {
    setNewQuestions((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    await createQuizMutation.mutateAsync({
      title: newTitle,
      description: newDescription,
      class_id: Number(newClassId),
      duration_minutes: Number(newDuration),
      questions: newQuestions,
    });

    setIsCreateOpen(false);
    setNewTitle("");
    setNewDescription("");
    setNewQuestions([
      {
        question_text: "",
        option_a: "",
        option_b: "",
        option_c: "",
        option_d: "",
        correct_option: "A",
        marks: 1.0,
        order_index: 0,
      },
    ]);
  };

  const handleOptionSelect = (questionId: number, optionKey: string) => {
    setSelectedAnswers((prev) => ({
      ...prev,
      [String(questionId)]: optionKey,
    }));
  };

  const handleAutoSubmit = async () => {
    if (!activeQuizId) return;
    try {
      const res = await submitAttemptMutation.mutateAsync({
        quizId: activeQuizId,
        answers: selectedAnswers,
      });
      setLatestAttemptResult(res);
      setQuizFinished(true);
    } catch (err) {
      console.error(err);
    }
  };

  const formatTimer = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s < 10 ? "0" : ""}${s}`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <HelpCircle className="h-7 w-7 text-primary" />
            Online Quizzes & Auto-Grading
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isTeacherOrAdmin
              ? "Create MCQ assessments, monitor class performance, and evaluate student accuracy."
              : "Take interactive timed quizzes, get instant auto-graded scores, and review answers."}
          </p>
        </div>

        {isTeacherOrAdmin && (
          <Button
            onClick={() => setIsCreateOpen(true)}
            className="flex items-center gap-2 shadow-sm font-medium"
          >
            <Plus className="h-4 w-4" />
            Create Quiz
          </Button>
        )}
      </div>

      {/* Main Content: Taking Quiz OR Quiz List */}
      {activeQuizId && activeQuiz ? (
        <Card className="border shadow-sm">
          <CardContent className="p-6">
            {!quizFinished ? (
              <div className="space-y-6">
                {/* Quiz Taking Header & Timer */}
                <div className="flex items-center justify-between border-b pb-4">
                  <div>
                    <h2 className="text-xl font-bold text-foreground">{activeQuiz.title}</h2>
                    <p className="text-sm text-muted-foreground">{activeQuiz.description}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/10 text-amber-600 font-mono font-bold text-sm">
                      <Clock className="h-4 w-4 animate-pulse" />
                      Time Remaining: {formatTimer(timeLeft)}
                    </div>
                  </div>
                </div>

                {/* Questions List */}
                <div className="space-y-6">
                  {activeQuiz.questions?.map((q, idx) => (
                    <div key={q.id || idx} className="p-4 rounded-xl border bg-muted/20 space-y-3">
                      <div className="flex items-start justify-between">
                        <span className="font-semibold text-sm text-foreground">
                          Question {idx + 1}. {q.question_text}
                        </span>
                        <Badge variant="outline" className="text-xs">
                          {q.marks} {q.marks === 1 ? "mark" : "marks"}
                        </Badge>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2">
                        {[
                          { key: "A", text: q.option_a },
                          { key: "B", text: q.option_b },
                          { key: "C", text: q.option_c },
                          { key: "D", text: q.option_d },
                        ].map((opt) => {
                          const isSelected = selectedAnswers[String(q.id)] === opt.key;
                          return (
                            <button
                              key={opt.key}
                              type="button"
                              onClick={() => q.id && handleOptionSelect(q.id, opt.key)}
                              className={`flex items-center gap-3 p-3 rounded-lg border text-left text-sm transition-all ${
                                isSelected
                                  ? "border-primary bg-primary/10 font-medium text-primary shadow-xs"
                                  : "border-border hover:bg-muted/50 text-foreground"
                              }`}
                            >
                              <span
                                className={`h-6 w-6 rounded-full flex items-center justify-center text-xs font-bold border ${
                                  isSelected
                                    ? "bg-primary text-primary-foreground border-primary"
                                    : "bg-background border-muted-foreground/30 text-muted-foreground"
                                }`}
                              >
                                {opt.key}
                              </span>
                              <span>{opt.text}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Submit Action */}
                <div className="flex items-center justify-between pt-4 border-t">
                  <Button variant="ghost" onClick={() => setActiveQuizId(null)}>
                    Exit Quiz
                  </Button>
                  <Button
                    onClick={handleAutoSubmit}
                    disabled={submitAttemptMutation.isPending}
                    className="flex items-center gap-2"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    {submitAttemptMutation.isPending ? "Grading..." : "Submit & Auto-Grade"}
                  </Button>
                </div>
              </div>
            ) : (
              /* Immediate Auto-Graded Result Card */
              <div className="py-8 text-center space-y-4 max-w-lg mx-auto">
                <div className="h-16 w-16 mx-auto rounded-full bg-emerald-500/10 text-emerald-600 flex items-center justify-center">
                  <Award className="h-9 w-9" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-foreground">Quiz Completed!</h2>
                  <p className="text-sm text-muted-foreground mt-1">
                    Your answers were submitted and automatically evaluated.
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-4 py-4">
                  <div className="p-4 rounded-xl border bg-muted/30">
                    <span className="text-xs text-muted-foreground">Score Obtained</span>
                    <p className="text-2xl font-bold text-primary mt-1">
                      {latestAttemptResult?.score} / {latestAttemptResult?.total_marks}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl border bg-muted/30">
                    <span className="text-xs text-muted-foreground">Accuracy</span>
                    <p className="text-2xl font-bold text-emerald-600 mt-1">
                      {latestAttemptResult?.percentage}%
                    </p>
                  </div>
                </div>

                <Button onClick={() => setActiveQuizId(null)} className="w-full">
                  Return to Quizzes List
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        /* Quizzes List Cards */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {isLoading ? (
            <div className="col-span-full py-16 text-center text-muted-foreground">
              Loading quizzes...
            </div>
          ) : quizzes.length === 0 ? (
            <div className="col-span-full py-16 text-center border rounded-xl bg-card">
              <BookOpen className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
              <h3 className="font-semibold text-foreground">No quizzes published yet</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {isTeacherOrAdmin
                  ? "Click 'Create Quiz' to build your first MCQ test."
                  : "Check back later for newly assigned assessments."}
              </p>
            </div>
          ) : (
            quizzes.map((quiz) => {
              const hasAttempted = !!quiz.my_attempt;
              return (
                <Card key={quiz.id} className="border shadow-xs hover:shadow-md transition-shadow">
                  <CardContent className="p-5 flex flex-col justify-between h-full space-y-4">
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <Badge variant="outline" className="bg-primary/5 text-primary text-xs font-semibold">
                          {quiz.class_name || `Class #${quiz.class_id}`}
                        </Badge>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Clock className="h-3.5 w-3.5" />
                          {quiz.duration_minutes} mins
                        </div>
                      </div>

                      <h3 className="font-bold text-base text-foreground mt-2 line-clamp-1">
                        {quiz.title}
                      </h3>
                      {quiz.description && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {quiz.description}
                        </p>
                      )}
                    </div>

                    <div className="border-t pt-3 flex items-center justify-between text-xs text-muted-foreground">
                      <span>{quiz.questions_count} Questions</span>
                      <span className="font-semibold text-foreground">
                        {quiz.total_marks} Marks
                      </span>
                    </div>

                    <div className="pt-1 flex gap-2">
                      {isTeacherOrAdmin ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setResultsQuizId(quiz.id)}
                          className="w-full flex items-center justify-center gap-1.5 text-xs"
                        >
                          <BarChart3 className="h-3.5 w-3.5" />
                          View Results & Analytics
                        </Button>
                      ) : hasAttempted ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setActiveQuizId(quiz.id);
                            setQuizFinished(true);
                            setLatestAttemptResult(quiz.my_attempt);
                          }}
                          className="w-full flex items-center justify-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 hover:bg-emerald-100"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Score: {quiz.my_attempt?.score}/{quiz.total_marks} (
                          {quiz.my_attempt?.percentage}%)
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          onClick={() => {
                            setActiveQuizId(quiz.id);
                            setQuizFinished(false);
                            setSelectedAnswers({});
                          }}
                          className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold"
                        >
                          <Play className="h-3.5 w-3.5" />
                          Start Quiz
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })
          )}
        </div>
      )}

      {/* Teacher Create Quiz Modal */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              Build Online Quiz
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleCreateSubmit} className="space-y-4 mt-2">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-foreground">Quiz Title</label>
                <Input
                  required
                  placeholder="e.g. Chapter 4 Calculus Quiz"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Duration (Minutes)</label>
                <Input
                  type="number"
                  required
                  min={1}
                  value={newDuration}
                  onChange={(e) => setNewDuration(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-foreground">Instructions / Description</label>
              <Input
                placeholder="Optional instructions for students"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                className="mt-1"
              />
            </div>

            {/* Questions Builder */}
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between border-b pb-2">
                <h4 className="text-sm font-bold text-foreground">
                  Questions ({newQuestions.length})
                </h4>
                <Button type="button" variant="outline" size="sm" onClick={handleAddQuestion}>
                  <Plus className="h-3.5 w-3.5 mr-1" />
                  Add Question
                </Button>
              </div>

              {newQuestions.map((q, idx) => (
                <div key={idx} className="p-3.5 rounded-lg border bg-muted/20 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-primary">Question #{idx + 1}</span>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-muted-foreground">Marks:</label>
                      <Input
                        type="number"
                        min={0.5}
                        step={0.5}
                        value={q.marks}
                        onChange={(e) =>
                          handleQuestionChange(idx, "marks", parseFloat(e.target.value) || 1.0)
                        }
                        className="w-16 h-7 text-xs"
                      />
                    </div>
                  </div>

                  <Input
                    required
                    placeholder="Enter question text..."
                    value={q.question_text}
                    onChange={(e) => handleQuestionChange(idx, "question_text", e.target.value)}
                    className="text-xs"
                  />

                  <div className="grid grid-cols-2 gap-2">
                    {["a", "b", "c", "d"].map((opt) => (
                      <Input
                        key={opt}
                        required
                        placeholder={`Option ${opt.toUpperCase()}`}
                        value={(q as any)[`option_${opt}`]}
                        onChange={(e) =>
                          handleQuestionChange(idx, `option_${opt}` as keyof Question, e.target.value)
                        }
                        className="text-xs"
                      />
                    ))}
                  </div>

                  <div className="flex items-center gap-3 pt-1">
                    <label className="text-xs font-semibold text-foreground">
                      Correct Answer:
                    </label>
                    <div className="flex gap-2">
                      {["A", "B", "C", "D"].map((opt) => (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => handleQuestionChange(idx, "correct_option", opt)}
                          className={`h-7 w-7 rounded text-xs font-bold transition-colors ${
                            q.correct_option === opt
                              ? "bg-emerald-600 text-white"
                              : "bg-muted text-muted-foreground hover:bg-muted/80"
                          }`}
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t">
              <Button type="button" variant="ghost" onClick={() => setIsCreateOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={createQuizMutation.isPending}>
                {createQuizMutation.isPending ? "Creating..." : "Publish Quiz"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Teacher Results Breakdown Modal */}
      <Dialog open={!!resultsQuizId} onOpenChange={() => setResultsQuizId(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-primary" />
              Class Results Breakdown
            </DialogTitle>
          </DialogHeader>

          {quizResults && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3 p-3 rounded-lg bg-muted/30 border">
                <div className="text-center">
                  <span className="text-xs text-muted-foreground">Attempts</span>
                  <p className="text-lg font-bold text-foreground">
                    {quizResults.attempts_count} / {quizResults.enrolled_count}
                  </p>
                </div>
                <div className="text-center">
                  <span className="text-xs text-muted-foreground">Average Score</span>
                  <p className="text-lg font-bold text-primary">
                    {quizResults.average_score ?? "—"} / {quizResults.total_marks}
                  </p>
                </div>
                <div className="text-center">
                  <span className="text-xs text-muted-foreground">Highest Score</span>
                  <p className="text-lg font-bold text-emerald-600">
                    {quizResults.highest_score ?? "—"}
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Per-Question Accuracy
                </h4>
                {quizResults.questions_analysis?.map((q: any, i: number) => (
                  <div key={q.id || i} className="p-3 rounded-lg border space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-foreground">
                        Q{i + 1}. {q.question_text}
                      </span>
                      <Badge variant="outline" className="text-emerald-700 bg-emerald-50">
                        {q.accuracy_percentage}% Accuracy
                      </Badge>
                    </div>
                    <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-emerald-500 h-2 rounded-full transition-all"
                        style={{ width: `${q.accuracy_percentage}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>Correct: Option {q.correct_option}</span>
                      <span>
                        {q.correct_count} of {q.total_answered} answered correctly
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
