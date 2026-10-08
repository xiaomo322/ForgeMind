import type { TaskSummary } from "../types";

interface Props {
  open: boolean;
  tasks: TaskSummary[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onSelect: (taskId: string) => void;
}

const STATUS_LABELS: Record<TaskSummary["status"], string> = {
  running: "运行中",
  waiting_user: "等待确认",
  executing: "执行中",
  completed: "已完成",
  blocked: "已阻塞",
  cancelled: "已取消",
};

export function TaskHistoryDrawer({ open, tasks, loading, error, onClose, onSelect }: Props) {
  if (!open) return null;
  return <>
    <button className="drawer-backdrop" type="button" onClick={onClose} aria-label="关闭历史任务" />
    <aside id="task-history-drawer" className="history-drawer" aria-label="历史任务">
      <header>
        <div><strong>历史任务</strong><span>数据保存在 ForgeMind SQLite</span></div>
        <button type="button" onClick={onClose} aria-label="关闭历史任务抽屉">×</button>
      </header>
      {loading && <p className="drawer-message">正在读取历史任务…</p>}
      {error && <p className="drawer-message drawer-message--error" role="alert">{error}</p>}
      {!loading && !error && tasks.length === 0 && <p className="drawer-message">还没有创建过任务。</p>}
      {!loading && !error && tasks.length > 0 && <ul>{tasks.map((task) => <li key={task.task_id}>
        <button type="button" onClick={() => onSelect(task.task_id)} aria-label={`${task.original_request}，${STATUS_LABELS[task.status]}`}>
          <strong>{task.original_request}</strong>
          <span>{STATUS_LABELS[task.status]} · revision {task.revision}</span>
          <code>{task.task_id}</code>
        </button>
      </li>)}</ul>}
    </aside>
  </>;
}
