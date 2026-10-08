import type {
  PublicTaskState,
  TaskEvent,
  UploadedWorkspace,
  StagedUpload,
  TaskMessageAccepted,
  TaskFile,
} from "./types";

interface CreatedTask {
  task_id: string;
  original_request: string;
  workspace_id: string;
  status: "running";
  revision: number;
}

interface AnswerAccepted {
  response_id: string;
  task_id: string;
  question_action_id: string;
  status: "running";
  revision: number;
}

interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function responseError(response: Response): Promise<ApiError> {
  let message = `请求失败（HTTP ${response.status}）`;
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body.detail)) {
      message = body.detail.map((item) => item.msg ?? "输入无效").join("；");
    }
  } catch {
    // 非 JSON 错误仍使用稳定的 HTTP 状态消息。
  }
  return new ApiError(message, response.status);
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as T;
}

export async function uploadWorkspace(files: File[]): Promise<UploadedWorkspace> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file, file.name));
  return jsonRequest<UploadedWorkspace>("/workspaces", { method: "POST", body });
}

export async function createTask(
  originalRequest: string,
  workspaceId: string,
): Promise<CreatedTask> {
  return jsonRequest<CreatedTask>("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ original_request: originalRequest, workspace_id: workspaceId }),
  });
}

export async function getTask(taskId: string): Promise<PublicTaskState> {
  return jsonRequest<PublicTaskState>(`/tasks/${encodeURIComponent(taskId)}`);
}

export async function stageTaskFiles(taskId: string, files: File[]): Promise<StagedUpload[]> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file, file.name));
  const result = await jsonRequest<{ uploads: StagedUpload[] }>(
    `/tasks/${encodeURIComponent(taskId)}/files`,
    { method: "POST", body },
  );
  return result.uploads;
}

export async function sendTaskMessage(
  taskId: string,
  content: string,
  attachmentUploadIds: string[],
): Promise<TaskMessageAccepted> {
  return jsonRequest<TaskMessageAccepted>(`/tasks/${encodeURIComponent(taskId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: content.trim() || null, attachment_upload_ids: attachmentUploadIds }),
  });
}

export async function listTaskFiles(taskId: string): Promise<TaskFile[]> {
  const result = await jsonRequest<{ files: TaskFile[] }>(
    `/tasks/${encodeURIComponent(taskId)}/files`,
  );
  return result.files;
}

export async function deleteStagedFile(taskId: string, uploadId: string): Promise<void> {
  const response = await fetch(
    `/tasks/${encodeURIComponent(taskId)}/files/staged/${encodeURIComponent(uploadId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw await responseError(response);
}

export async function answerQuestion(
  taskId: string,
  questionActionId: string,
  rawResponse: string,
  selectedOption: string | null,
): Promise<AnswerAccepted> {
  return jsonRequest<AnswerAccepted>(`/tasks/${encodeURIComponent(taskId)}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question_action_id: questionActionId,
      raw_response: rawResponse,
      selected_option: selectedOption,
    }),
  });
}

export async function decidePermission(
  taskId: string,
  permissionRequestId: string,
  decision: "approve" | "reject",
  rawResponse: string,
): Promise<PublicTaskState> {
  return jsonRequest<PublicTaskState>(
    `/tasks/${encodeURIComponent(taskId)}/permissions/${encodeURIComponent(permissionRequestId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, raw_response: rawResponse }),
    },
  );
}

const EVENT_TYPES: TaskEvent["type"][] = [
  "agent.step",
  "task.waiting_user",
  "task.permission_required",
  "task.completed",
  "task.step_limit_reached",
  "task.failed",
];

export function connectTaskEvents(
  taskId: string,
  callbacks: {
    onEvent: (event: TaskEvent) => void;
    onConnectionError: () => void;
  },
): () => void {
  const source = new EventSource(`/tasks/${encodeURIComponent(taskId)}/events`);

  EVENT_TYPES.forEach((type) => {
    source.addEventListener(type, (rawEvent) => {
      const event = rawEvent as MessageEvent<string>;
      const payload = JSON.parse(event.data) as { task_id: string; data: unknown };
      callbacks.onEvent({
        type,
        sequence: Number(event.lastEventId),
        data: payload.data,
      } as TaskEvent);
      if (
        type === "task.waiting_user" ||
        type === "task.permission_required" ||
        type === "task.completed" ||
        type === "task.step_limit_reached" ||
        type === "task.failed"
      ) {
        source.close();
      }
    });
  });
  source.onerror = () => callbacks.onConnectionError();
  return () => source.close();
}
