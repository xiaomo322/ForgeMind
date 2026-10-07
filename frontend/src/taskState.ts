import type {
  PermissionRequiredData,
  TaskEvent,
  TaskStatus,
  WaitingUserData,
} from "./types";

export type TimelineItem =
  | { kind: "step"; sequence: number; data: Extract<TaskEvent, { type: "agent.step" }>["data"] }
  | { kind: "question"; sequence: number; data: WaitingUserData }
  | { kind: "permission"; sequence: number; data: PermissionRequiredData }
  | { kind: "completion"; sequence: number; summary: string }
  | { kind: "failure"; sequence: number; message: string };

export interface TaskUiState {
  taskId: string;
  status: TaskStatus;
  timeline: TimelineItem[];
  pendingQuestion: WaitingUserData | null;
  pendingPermission: PermissionRequiredData | null;
  summary: string | null;
  error: string | null;
}

export function initialTaskUiState(taskId: string): TaskUiState {
  return {
    taskId,
    status: "running",
    timeline: [],
    pendingQuestion: null,
    pendingPermission: null,
    summary: null,
    error: null,
  };
}

export function taskStateReducer(state: TaskUiState, event: TaskEvent): TaskUiState {
  switch (event.type) {
    case "agent.step":
      return {
        ...state,
        status: "running",
        error: null,
        timeline: [...state.timeline, { kind: "step", sequence: event.sequence, data: event.data }],
      };
    case "task.waiting_user":
      return {
        ...state,
        status: "waiting_user",
        pendingQuestion: event.data,
        pendingPermission: null,
        timeline: [...state.timeline, { kind: "question", sequence: event.sequence, data: event.data }],
      };
    case "task.permission_required":
      return {
        ...state,
        status: "waiting_user",
        pendingQuestion: null,
        pendingPermission: event.data,
        timeline: [...state.timeline, { kind: "permission", sequence: event.sequence, data: event.data }],
      };
    case "task.completed":
      return {
        ...state,
        status: "completed",
        pendingQuestion: null,
        pendingPermission: null,
        summary: event.data.summary,
        timeline: [
          ...state.timeline,
          { kind: "completion", sequence: event.sequence, summary: event.data.summary },
        ],
      };
    case "task.failed":
      return {
        ...state,
        error: event.data.message,
        timeline: [
          ...state.timeline,
          { kind: "failure", sequence: event.sequence, message: event.data.message },
        ],
      };
  }
}
