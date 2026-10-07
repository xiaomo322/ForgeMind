import type {
  PermissionRequiredData,
  PublicTaskState,
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

export type TaskStateAction =
  | TaskEvent
  | { type: "task.snapshot"; state: TaskUiState }
  | { type: "task.resumed" };

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringOptions(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : null;
}

export function hydrateTaskUiState(task: PublicTaskState): TaskUiState {
  const state = initialTaskUiState(task.task_id);
  state.status = task.status;

  task.actions.forEach((item) => {
    const action = item.action;
    const stepSequence = item.sequence * 2 - 1;
    state.timeline.push({
      kind: "step",
      sequence: stepSequence,
      data: {
        step_number: item.sequence,
        decision: action,
        runtime: {
          permission_request: item.permission_request,
          permission_decision: item.permission_decision,
          observation: item.observation,
          user_response: item.user_response,
        },
      },
    });

    if (action.action_type === "complete") {
      state.summary = text(action.summary);
      state.timeline.push({
        kind: "completion",
        sequence: item.sequence * 2,
        summary: state.summary,
      });
    }
    if (
      action.action_type === "ask_user" &&
      item.user_response === null &&
      task.status === "waiting_user"
    ) {
      state.pendingQuestion = {
        question_action_id: text(action.action_id),
        reason: text(action.reason),
        question: text(action.question),
        options: stringOptions(action.options),
      };
      state.timeline.push({
        kind: "question",
        sequence: item.sequence * 2,
        data: state.pendingQuestion,
      });
    }
    if (
      item.permission_request !== null &&
      item.permission_decision === null &&
      task.status === "waiting_user"
    ) {
      const request = item.permission_request;
      state.pendingPermission = {
        permission_request_id: text(request.permission_request_id),
        tool_name: text(request.tool_name),
        reason: text(request.reason),
        arguments:
          typeof request.arguments === "object" && request.arguments !== null
            ? (request.arguments as Record<string, unknown>)
            : {},
      };
      state.timeline.push({
        kind: "permission",
        sequence: item.sequence * 2,
        data: state.pendingPermission,
      });
    }
  });
  return state;
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

export function taskStateReducer(state: TaskUiState, event: TaskStateAction): TaskUiState {
  switch (event.type) {
    case "task.snapshot":
      return event.state;
    case "task.resumed":
      return {
        ...state,
        status: "running",
        pendingQuestion: null,
        pendingPermission: null,
        error: null,
      };
    case "agent.step":
      return {
        ...state,
        status: "running",
        pendingQuestion: null,
        pendingPermission: null,
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
