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

export interface TaskSummary {
  task_id: string;
  original_request: string;
  workspace_id: string | null;
  status: TaskStatus;
  revision: number;
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
  messages?: PublicTaskMessage[];
}

export interface PublicAttachment {
  upload_id: string;
  path: string;
  size_bytes: number;
  sha256: string;
  state: "active" | "staged";
}

export interface PublicTaskMessage {
  message_id: string;
  sequence: number;
  content: string | null;
  delivery: "queued" | "applied";
  applied_after_action_sequence: number | null;
  attachments: PublicAttachment[];
}

export interface StagedUpload extends PublicAttachment {
  state: "staged";
}

export interface TaskFile {
  upload_id?: string;
  path: string;
  size_bytes: number;
  sha256: string;
  state: "active" | "staged";
}

export interface TaskMessageAccepted {
  message_id: string;
  sequence: number;
  delivery: "queued";
  task_status: TaskStatus;
  revision: number;
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

export interface StepLimitReachedData {
  max_steps: number;
  message: string;
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
      type: "task.step_limit_reached";
      sequence: number;
      data: StepLimitReachedData;
    }
  | {
      type: "task.failed";
      sequence: number;
      data: { category: string; message: string };
    };
