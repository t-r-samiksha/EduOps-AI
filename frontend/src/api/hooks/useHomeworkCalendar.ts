import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";

export interface HomeworkEvent {
  id: string;
  title: string;
  type: string; // assignment, quiz, exam
  subject: string;
  start: string;
  end: string;
  status: string; // upcoming, overdue, completed
  details?: string;
  max_marks?: number;
}

export interface CalendarEvent {
  id: number;
  user_id: number;
  event_type: string;
  title: string;
  subject_id?: number;
  start_time: string;
  end_time: string;
  source_id?: number;
  source_type?: string;
}

export function useHomeworkCalendar(studentId?: number) {
  return useQuery<HomeworkEvent[]>({
    queryKey: ["homework-calendar", studentId],
    queryFn: () => apiGet<HomeworkEvent[]>(`/calendar/homework/${studentId}`),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}

export function useUserCalendar(userId?: number, start?: string, end?: string) {
  return useQuery<CalendarEvent[]>({
    queryKey: ["user-calendar", userId, start, end],
    queryFn: () =>
      apiGet<CalendarEvent[]>(`/calendar/${userId}`, { start, end }),
    enabled: typeof userId === "number" && !isNaN(userId),
  });
}

export function useTriggerCalendarSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/calendar/sync"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-calendar"] });
      queryClient.invalidateQueries({ queryKey: ["homework-calendar"] });
    },
  });
}
