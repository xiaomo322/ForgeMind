import { useEffect, useReducer, useState } from "react";

import { answerQuestion, connectTaskEvents, createTask, decidePermission, deleteStagedFile, getTask, listTasks, listTaskFiles, sendTaskMessage, stageTaskFiles, uploadWorkspace, uploadWorkspaceArchive } from "./api";
import { PermissionPrompt } from "./components/PermissionPrompt";
import { StatusHeader } from "./components/StatusHeader";
import { UserPrompt } from "./components/UserPrompt";
import { WorkspaceForm } from "./components/WorkspaceForm";
import { MessageComposer } from "./components/MessageComposer";
import { ProjectFilesDrawer } from "./components/ProjectFilesDrawer";
import { ConversationFeed } from "./components/ConversationFeed";
import { TaskHistoryDrawer } from "./components/TaskHistoryDrawer";
import type { PublicActionState, PublicTaskMessage, TaskFile, TaskSummary } from "./types";
import { hydrateTaskUiState, initialTaskUiState, taskStateReducer } from "./taskState";

function taskIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("task");
}

export function App() {
  const [taskState, dispatch] = useReducer(taskStateReducer, null, () => {
    const taskId = taskIdFromUrl();
    return taskId ? initialTaskUiState(taskId) : initialTaskUiState("");
  });
  const [taskMeta, setTaskMeta] = useState<{ id: string; request: string } | null>(null);
  const [restoring, setRestoring] = useState(Boolean(taskIdFromUrl()));
  const [interactionBusy, setInteractionBusy] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [messages, setMessages] = useState<PublicTaskMessage[]>([]);
  const [actions, setActions] = useState<PublicActionState[]>([]);
  const [files, setFiles] = useState<TaskFile[]>([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyTasks, setHistoryTasks] = useState<TaskSummary[]>([]);

  async function loadTask(taskId: string) {
    const task = await getTask(taskId);
    setTaskMeta({ id: task.task_id, request: task.original_request });
    setMessages(task.messages ?? []);
    setActions(task.actions);
    dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
    setFiles(await listTaskFiles(task.task_id));
  }

  useEffect(() => {
    const taskId = taskIdFromUrl();
    if (!taskId) return;
    loadTask(taskId)
      .catch((error: unknown) => setPageError(error instanceof Error ? error.message : "无法恢复任务"))
      .finally(() => setRestoring(false));
    // 首次加载 URL 时恢复一次；后续状态由 SSE 和用户 POST 驱动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!taskMeta || taskState.status !== "running") return;
    return connectTaskEvents(taskMeta.id, {
      onEvent: (event) => {
        dispatch(event);
        getTask(taskMeta.id).then((task) => {
          setMessages(task.messages ?? []);
          setActions(task.actions);
        }).catch(() => undefined);
        listTaskFiles(taskMeta.id).then(setFiles).catch(() => undefined);
      },
      onConnectionError: () => dispatch({
        type: "stream.connection_failed",
        message: "与服务器的实时连接中断，请重试。",
      }),
    });
  }, [taskMeta, taskState.status]);

  async function start(files: File[], request: string) {
    let workspaceId: string | undefined;
    if (files.length > 0) {
      const workspace = files.length === 1 && files[0].name.toLowerCase().endsWith(".zip")
        ? await uploadWorkspaceArchive(files[0])
        : await uploadWorkspace(files);
      workspaceId = workspace.workspace_id;
    }
    const created = workspaceId
      ? await createTask(request, workspaceId)
      : await createTask(request);
    window.history.replaceState({}, "", `/?task=${encodeURIComponent(created.task_id)}`);
    setTaskMeta({ id: created.task_id, request: created.original_request });
    setActions([]);
    setFiles(await listTaskFiles(created.task_id));
    setPageError(null);
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      setHistoryTasks(await listTasks());
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "无法读取历史任务");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function selectHistoryTask(taskId: string) {
    setHistoryOpen(false);
    setRestoring(true);
    setPageError(null);
    window.history.replaceState({}, "", `/?task=${encodeURIComponent(taskId)}`);
    try {
      await loadTask(taskId);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "无法恢复任务");
    } finally {
      setRestoring(false);
    }
  }

  async function submitAnswer(rawResponse: string, selectedOption: string | null) {
    if (!taskMeta || !taskState.pendingQuestion) return;
    setInteractionBusy(true);
    try {
      await answerQuestion(taskMeta.id, taskState.pendingQuestion.question_action_id, rawResponse, selectedOption);
      // POST 先写 SQLite，再重新读取权威快照；因此已回答问题仍保留在时间线中。
      const task = await getTask(taskMeta.id);
      setMessages(task.messages ?? []);
      setActions(task.actions);
      dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "回答提交失败");
    } finally {
      setInteractionBusy(false);
    }
  }

  async function submitPermission(decision: "approve" | "reject") {
    if (!taskMeta || !taskState.pendingPermission) return;
    setInteractionBusy(true);
    try {
      const task = await decidePermission(
        taskMeta.id,
        taskState.pendingPermission.permission_request_id,
        decision,
        `${decision === "approve" ? "批准" : "拒绝"}本次 ${taskState.pendingPermission.tool_name} 操作`,
      );
      setMessages(task.messages ?? []);
      setActions(task.actions);
      dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "权限决定提交失败");
    } finally {
      setInteractionBusy(false);
    }
  }

  async function submitMessage(content: string, selectedFiles: File[]) {
    if (!taskMeta) return;
    setInteractionBusy(true);
    setPageError(null);
    try {
      const staged = selectedFiles.length > 0 ? await stageTaskFiles(taskMeta.id, selectedFiles) : [];
      await sendTaskMessage(taskMeta.id, content, staged.map((item) => item.upload_id));
      const task = await getTask(taskMeta.id);
      setMessages(task.messages ?? []);
      setActions(task.actions);
      setFiles(await listTaskFiles(taskMeta.id));
      dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "消息发送失败");
      throw error;
    } finally {
      setInteractionBusy(false);
    }
  }

  async function removeStagedFile(uploadId: string) {
    if (!taskMeta) return;
    try {
      await deleteStagedFile(taskMeta.id, uploadId);
      setFiles(await listTaskFiles(taskMeta.id));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "暂存文件删除失败");
    }
  }

  function newTask() {
    window.history.replaceState({}, "", "/");
    window.location.reload();
  }

  function resumeTask() {
    setPageError(null);
    dispatch({ type: "task.resumed" });
  }

  if (restoring) return <main className="loading-page" aria-busy="true"><p>正在从 SQLite 恢复任务…</p></main>;
  if (!taskMeta) {
    return <main className="launch-shell">
      <nav className="brand-bar"><strong>ForgeMind</strong><span>Agent Runtime Workbench</span><button className="secondary-button compact-button" type="button" onClick={openHistory}>历史任务</button></nav>
      <WorkspaceForm onStart={start} />
      <TaskHistoryDrawer open={historyOpen} tasks={historyTasks} loading={historyLoading} error={historyError} onClose={() => setHistoryOpen(false)} onSelect={selectHistoryTask} />
    </main>;
  }

  return (
    <main className="workbench-shell conversation-shell">
      <nav className="app-topbar" aria-label="ForgeMind 任务工具栏">
        <div className="brand-lockup"><span className="brand-mark" aria-hidden="true">F</span><strong>ForgeMind</strong></div>
        <div className="topbar-actions">
          <button className="secondary-button compact-button" type="button" onClick={openHistory}>历史任务</button>
          <button
            className="files-trigger"
            type="button"
            aria-controls="project-files-drawer"
            aria-expanded={filesOpen}
            onClick={() => setFilesOpen((open) => !open)}
          >
            项目文件 · {files.length}
          </button>
          <button className="secondary-button compact-button" type="button" onClick={newTask}>新建任务</button>
        </div>
      </nav>
      <StatusHeader taskId={taskMeta.id} status={taskState.status} request={taskMeta.request} />
      {pageError && <p className="page-error" role="alert">{pageError}</p>}
      <div className="conversation-column">
        <ConversationFeed originalRequest={taskMeta.request} messages={messages} actions={actions} />
        <div className="interaction-column conversation-interactions">
          {taskState.pendingQuestion && <UserPrompt prompt={taskState.pendingQuestion} disabled={interactionBusy} onSubmit={submitAnswer} />}
          {taskState.pendingPermission && <PermissionPrompt prompt={taskState.pendingPermission} disabled={interactionBusy} onDecision={submitPermission} />}
          {taskState.status === "paused" && <aside className="runtime-action-panel"><p className="machine-label">EXECUTION PAUSED</p><h2>本轮执行已暂停</h2><p>Agent 已用完本轮的执行步数。请先检查左侧记录，再决定是否继续下一批。</p><button className="primary-button" type="button" onClick={resumeTask}>继续运行</button></aside>}
          {taskState.status === "failed" && <aside className="runtime-action-panel runtime-action-panel--danger"><p className="machine-label">CONNECTION STOPPED</p><h2>本次执行未能继续</h2><p>{taskState.error}</p><button className="primary-button" type="button" onClick={resumeTask}>重试连接</button></aside>}
          {!taskState.pendingQuestion && !taskState.pendingPermission && !taskState.summary && taskState.status !== "paused" && taskState.status !== "failed" && <aside className="context-panel"><p className="machine-label">RUNTIME BOUNDARY</p><p>读取与搜索可直接执行；修改文件、运行命令和测试会在这里等待你的明确授权。</p></aside>}
        </div>
      </div>
      {!taskState.pendingQuestion && <MessageComposer busy={interactionBusy} running={taskState.status === "running"} onSend={submitMessage} />}
      <ProjectFilesDrawer taskId={taskMeta.id} open={filesOpen} files={files} onClose={() => setFilesOpen(false)} onDeleteStaged={removeStagedFile} />
      <TaskHistoryDrawer open={historyOpen} tasks={historyTasks} loading={historyLoading} error={historyError} onClose={() => setHistoryOpen(false)} onSelect={selectHistoryTask} />
    </main>
  );
}
