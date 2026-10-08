import { useEffect, useReducer, useState } from "react";

import { answerQuestion, connectTaskEvents, createTask, decidePermission, getTask, uploadWorkspace } from "./api";
import { PermissionPrompt } from "./components/PermissionPrompt";
import { StatusHeader } from "./components/StatusHeader";
import { TaskTimeline } from "./components/TaskTimeline";
import { UserPrompt } from "./components/UserPrompt";
import { WorkspaceForm } from "./components/WorkspaceForm";
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
  useEffect(() => {
    const taskId = taskIdFromUrl();
    if (!taskId) return;
    getTask(taskId)
      .then((task) => {
        setTaskMeta({ id: task.task_id, request: task.original_request });
        dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
      })
      .catch((error: unknown) => setPageError(error instanceof Error ? error.message : "无法恢复任务"))
      .finally(() => setRestoring(false));
    // 首次加载 URL 时恢复一次；后续状态由 SSE 和用户 POST 驱动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!taskMeta || taskState.status !== "running") return;
    return connectTaskEvents(taskMeta.id, {
      onEvent: dispatch,
      onConnectionError: () => dispatch({
        type: "stream.connection_failed",
        message: "与服务器的实时连接中断，请重试。",
      }),
    });
  }, [taskMeta, taskState.status]);

  async function start(files: File[], request: string) {
    const workspace = await uploadWorkspace(files);
    const created = await createTask(request, workspace.workspace_id);
    window.history.replaceState({}, "", `/?task=${encodeURIComponent(created.task_id)}`);
    setTaskMeta({ id: created.task_id, request: created.original_request });
    setPageError(null);
  }

  async function submitAnswer(rawResponse: string, selectedOption: string | null) {
    if (!taskMeta || !taskState.pendingQuestion) return;
    setInteractionBusy(true);
    try {
      await answerQuestion(taskMeta.id, taskState.pendingQuestion.question_action_id, rawResponse, selectedOption);
      // POST 先写 SQLite，再重新读取权威快照；因此已回答问题仍保留在时间线中。
      const task = await getTask(taskMeta.id);
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
      dispatch({ type: "task.snapshot", state: hydrateTaskUiState(task) });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "权限决定提交失败");
    } finally {
      setInteractionBusy(false);
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
    return <main className="launch-shell"><nav className="brand-bar"><strong>ForgeMind</strong><span>Agent Runtime Workbench</span></nav><WorkspaceForm onStart={start} /></main>;
  }

  return (
    <main className="workbench-shell">
      <StatusHeader taskId={taskMeta.id} status={taskState.status} request={taskMeta.request} onNewTask={newTask} />
      {pageError && <p className="page-error" role="alert">{pageError}</p>}
      <div className="workbench-grid">
        <TaskTimeline timeline={taskState.timeline} />
        <div className="interaction-column">
          {taskState.pendingQuestion && <UserPrompt prompt={taskState.pendingQuestion} disabled={interactionBusy} onSubmit={submitAnswer} />}
          {taskState.pendingPermission && <PermissionPrompt prompt={taskState.pendingPermission} disabled={interactionBusy} onDecision={submitPermission} />}
          {taskState.summary && <aside className="completion-panel"><p className="machine-label">TASK COMPLETE</p><h2>{taskState.summary}</h2></aside>}
          {taskState.status === "paused" && <aside className="runtime-action-panel"><p className="machine-label">EXECUTION PAUSED</p><h2>本轮执行已暂停</h2><p>Agent 已用完本轮的执行步数。请先检查左侧记录，再决定是否继续下一批。</p><button className="primary-button" type="button" onClick={resumeTask}>继续运行</button></aside>}
          {taskState.status === "failed" && <aside className="runtime-action-panel runtime-action-panel--danger"><p className="machine-label">CONNECTION STOPPED</p><h2>本次执行未能继续</h2><p>{taskState.error}</p><button className="primary-button" type="button" onClick={resumeTask}>重试连接</button></aside>}
          {!taskState.pendingQuestion && !taskState.pendingPermission && !taskState.summary && taskState.status !== "paused" && taskState.status !== "failed" && <aside className="context-panel"><p className="machine-label">RUNTIME BOUNDARY</p><p>读取与搜索可直接执行；修改文件、运行命令和测试会在这里等待你的明确授权。</p></aside>}
        </div>
      </div>
    </main>
  );
}
