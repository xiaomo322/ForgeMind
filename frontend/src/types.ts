export type TaskStatus =
  | "running"
  | "waiting_user"
  | "executing"
  | "completed"
  | "blocked"
  | "cancelled";

export interface UploadedFileInfo {
  path: string;
  size_bytes: number;
}

export interface UploadedWorkspace {
  workspace_id: string;
  files: UploadedFileInfo[];
  file_count: number;
  total_size_bytes: number;
}

export interface PublicActionState {
  sequence: number;
  action: Record<string, unknown>;
  user_response: Record<string, unknown> | null;
  permission_request: Record<string, unknown> | null;
  permission_decision: Record<string, unknown> | null;
  observation: Record<string, unknown> | null;
}

export interface PublicTaskState {
  task_id: string;
  original_request: string;
  status: TaskStatus;
  revision: number;
  actions: PublicActionState[];
}

export interface AgentStepData {
  step_number: number;
  decision: Record<string, unknown>;
  runtime: Record<string, unknown>;
}

export interface WaitingUserData {
  question_action_id: string;
  reason: string;
  question: string;
  options: string[] | null;
}

export interface PermissionRequiredData {
  permission_request_id: string;
  tool_name: string;
  reason: string;
  arguments: Record<string, unknown>;
}

export type TaskEvent =
  | { type: "agent.step"; sequence: number; data: AgentStepData }
  | { type: "task.waiting_user"; sequence: number; data: WaitingUserData }
  | {
      type: "task.permission_required";
      sequence: number;
      data: PermissionRequiredData;
    }
  | { type: "task.completed"; sequence: number; data: { summary: string } }
  | {
      type: "task.failed";
      sequence: number;
      data: { category: string; message: string };
    };
