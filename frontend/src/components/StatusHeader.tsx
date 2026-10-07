import type { TaskStatus } from "../types";

const STATUS_LABEL: Record<TaskStatus, string> = {
  running: "Agent 正在工作",
  waiting_user: "等待你的决定",
  executing: "正在执行 Tool",
  completed: "任务已完成",
  blocked: "任务受阻",
  cancelled: "任务已取消",
};

export function StatusHeader({
  taskId,
  status,
  request,
  onNewTask,
}: {
  taskId: string;
  status: TaskStatus;
  request: string;
  onNewTask: () => void;
}) {
  return (
    <header className="task-header">
      <div>
        <div className="status-line">
          <span className={`status-dot status-dot--${status}`} aria-hidden="true" />
          <span>{STATUS_LABEL[status]}</span>
        </div>
        <h1>{request}</h1>
        <code>{taskId}</code>
      </div>
      <button className="secondary-button" type="button" onClick={onNewTask}>
        新建任务
      </button>
    </header>
  );
}
