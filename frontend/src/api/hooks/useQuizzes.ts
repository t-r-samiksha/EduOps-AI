import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";

export interface Question {
  id?: number;
  question_text: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_option?: string;
  marks: number;
  order_index?: number;
}

export interface QuizAttempt {
  id: number;
  quiz_id: number;
  student_id: number;
  score: number;
  total_marks: number;
  percentage: number;
  status: string;
  answers: Record<string, any>;
  started_at: string;
  submitted_at?: string;
}

export interface Quiz {
  id: number;
  school_id: number;
  class_id: number;
  class_name?: string;
  subject_id?: number;
  subject_name?: string;
  teacher_id: number;
  teacher_name?: string;
  title: string;
  description?: string;
  duration_minutes: number;
  available_from?: string;
  available_until?: string;
  total_marks: number;
  questions_count: number;
  questions?: Question[];
  my_attempt?: QuizAttempt;
  created_at: string;
}

export function useQuizzes(classId?: number, subjectId?: number) {
  return useQuery<Quiz[]>({
    queryKey: ["quizzes", { classId, subjectId }],
    queryFn: () =>
      apiGet<Quiz[]>("/quizzes", {
        class_id: classId,
        subject_id: subjectId,
      }),
  });
}

export function useQuizDetail(quizId?: number) {
  return useQuery<Quiz>({
    queryKey: ["quiz", quizId],
    queryFn: () => apiGet<Quiz>(`/quizzes/detail/${quizId}`),
    enabled: typeof quizId === "number" && !isNaN(quizId),
  });
}

export function useCreateQuiz() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      class_id: number;
      subject_id?: number;
      title: string;
      description?: string;
      duration_minutes: number;
      questions: Question[];
    }) => apiPost<Quiz>("/quizzes", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quizzes"] });
    },
  });
}

export function useSubmitQuizAttempt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      quizId,
      answers,
    }: {
      quizId: number;
      answers: Record<string, string>;
    }) =>
      apiPost<QuizAttempt>(`/quizzes/${quizId}/attempt`, {
        answers,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["quiz", variables.quizId] });
      queryClient.invalidateQueries({ queryKey: ["quizzes"] });
      queryClient.invalidateQueries({ queryKey: ["gradebook"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useQuizResults(quizId?: number) {
  return useQuery<any>({
    queryKey: ["quiz-results", quizId],
    queryFn: () => apiGet(`/quizzes/${quizId}/results`),
    enabled: typeof quizId === "number" && !isNaN(quizId),
  });
}
