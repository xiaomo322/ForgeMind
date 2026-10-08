import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import {
  answerQuestion,
  connectTaskEvents,
  createTask,
  decidePermission,
  getTask,
  listTasks,
  listTaskFiles,
  uploadWorkspaceArchive,
  uploadWorkspace,
} from "./api";

vi.mock("./api", () => ({
  answerQuestion: vi.fn(),
  connectTaskEvents: vi.fn(() => vi.fn()),
  createTask: vi.fn(),
  decidePermission: vi.fn(),
  deleteStagedFile: vi.fn(),
  getTask: vi.fn(),
  listTasks: vi.fn(),
  listTaskFiles: vi.fn(),
  sendTaskMessage: vi.fn(),
  stageTaskFiles: vi.fn(),
  uploadWorkspace: vi.fn(),
  uploadWorkspaceArchive: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadWorkspace);
const mockedCreate = vi.mocked(createTask);
const mockedGetTask = vi.mocked(getTask);
const mockedListTasks = vi.mocked(listTasks);
const mockedUploadArchive = vi.mocked(uploadWorkspaceArchive);
const mockedAnswer = vi.mocked(answerQuestion);
const mockedPermission = vi.mocked(decidePermission);
const mockedConnect = vi.mocked(connectTaskEvents);
const mockedListFiles = vi.mocked(listTaskFiles);

beforeEach(() => {
  vi.resetAllMocks();
  mockedConnect.mockImplementation(() => vi.fn());
  mockedListFiles.mockResolvedValue([]);
  mockedListTasks.mockResolvedValue([]);
  window.history.replaceState({}, "", "/");
});

describe("ForgeMind App", () => {
  it("rejects a non-Python file before uploading", async () => {
    render(<App />);

    fireEvent.change(screen.getByLabelText("选择 Python 文件或项目 ZIP（可选）"), {
      target: { files: [new File(["notes"], "notes.txt", { type: "text/plain" })] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("只支持 .py 文件");
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("uploads files, creates a task, and enters the live workbench", async () => {
    mockedUpload.mockResolvedValue({
      workspace_id: "workspace-1",
      files: [{ path: "main.py", size_bytes: 10 }],
      file_count: 1,
      total_size_bytes: 10,
    });
    mockedCreate.mockResolvedValue({
      task_id: "task-1",
      original_request: "检查价格计算",
      workspace_id: "workspace-1",
      status: "running",
      revision: 1,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.upload(
      screen.getByLabelText("选择 Python 文件或项目 ZIP（可选）"),
      new File(["value = 1\n"], "main.py", { type: "text/x-python" }),
    );
    await user.type(screen.getByLabelText("任务目标"), "检查价格计算");
    await user.click(screen.getByRole("button", { name: "启动 Agent" }));

    expect((await screen.findAllByText("检查价格计算")).length).toBeGreaterThan(0);
    expect(screen.getByText("task-1")).toBeInTheDocument();
    expect(mockedUpload).toHaveBeenCalledTimes(1);
    expect(mockedCreate).toHaveBeenCalledWith("检查价格计算", "workspace-1");
    expect(mockedConnect).toHaveBeenCalled();
  });

  it("creates a chat task without uploading files", async () => {
    mockedCreate.mockResolvedValue({
      task_id: "task-chat",
      original_request: "解释 Python 生成器",
      workspace_id: "workspace-empty",
      status: "running",
      revision: 1,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("任务目标"), "解释 Python 生成器");
    await user.click(screen.getByRole("button", { name: "开始聊天" }));

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith("解释 Python 生成器"));
    expect(mockedUpload).not.toHaveBeenCalled();
    expect(mockedUploadArchive).not.toHaveBeenCalled();
    expect(await screen.findByText("task-chat")).toBeInTheDocument();
  });

  it("uploads one ZIP archive as a new workspace", async () => {
    mockedUploadArchive.mockResolvedValue({
      workspace_id: "workspace-zip",
      files: [{ path: "src/main.py", size_bytes: 10 }],
      file_count: 1,
      total_size_bytes: 10,
    });
    mockedCreate.mockResolvedValue({
      task_id: "task-zip",
      original_request: "检查整个项目",
      workspace_id: "workspace-zip",
      status: "running",
      revision: 1,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.upload(
      screen.getByLabelText("选择 Python 文件或项目 ZIP（可选）"),
      new File(["zip-content"], "project.zip", { type: "application/zip" }),
    );
    await user.type(screen.getByLabelText("任务目标"), "检查整个项目");
    await user.click(screen.getByRole("button", { name: "启动 Agent" }));

    await waitFor(() => expect(mockedUploadArchive).toHaveBeenCalledTimes(1));
    expect(mockedUpload).not.toHaveBeenCalled();
    expect(mockedCreate).toHaveBeenCalledWith("检查整个项目", "workspace-zip");
  });

  it("rejects mixing a ZIP archive with direct Python files", async () => {
    render(<App />);

    fireEvent.change(screen.getByLabelText("选择 Python 文件或项目 ZIP（可选）"), {
      target: {
        files: [
          new File(["zip"], "project.zip", { type: "application/zip" }),
          new File(["pass\n"], "main.py", { type: "text/x-python" }),
        ],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ZIP 需要单独上传",
    );
    expect(mockedUploadArchive).not.toHaveBeenCalled();
  });

  it("opens a persisted task from the history drawer", async () => {
    mockedListTasks.mockResolvedValue([
      {
        task_id: "task-old",
        original_request: "恢复旧任务",
        workspace_id: "workspace-old",
        status: "completed",
        revision: 4,
      },
    ]);
    mockedGetTask.mockResolvedValue({
      task_id: "task-old",
      original_request: "恢复旧任务",
      status: "completed",
      revision: 4,
      actions: [],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "历史任务" }));
    await user.click(await screen.findByRole("button", { name: /恢复旧任务/ }));

    await waitFor(() => expect(mockedGetTask).toHaveBeenCalledWith("task-old"));
    expect(window.location.search).toBe("?task=task-old");
    expect((await screen.findAllByText("恢复旧任务")).length).toBeGreaterThan(0);
  });

  it("restores and answers an Agent question", async () => {
    window.history.replaceState({}, "", "/?task=task-question");
    const waitingState = {
      task_id: "task-question",
      original_request: "修改 value",
      status: "waiting_user" as const,
      revision: 2,
      actions: [
        {
          sequence: 1,
          action: {
            action_id: "question-1",
            action_type: "ask_user",
            reason: "缺少目标值",
            question: "value 应改成多少？",
            options: ["2", "3"],
          },
          user_response: null,
          permission_request: null,
          permission_decision: null,
          observation: null,
        },
      ],
    };
    mockedGetTask
      .mockResolvedValueOnce(waitingState)
      .mockResolvedValueOnce({
        ...waitingState,
        status: "running",
        revision: 3,
        actions: [
          {
            ...waitingState.actions[0],
            user_response: { raw_response: "2", selected_option: "2" },
          },
        ],
      });
    mockedAnswer.mockResolvedValue({
      response_id: "response-1",
      task_id: "task-question",
      question_action_id: "question-1",
      status: "running",
      revision: 3,
    });
    const user = userEvent.setup();
    render(<App />);

    expect((await screen.findAllByText("value 应改成多少？")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("radio", { name: "2" }));
    await user.click(screen.getByRole("button", { name: "提交回答" }));

    await waitFor(() =>
      expect(mockedAnswer).toHaveBeenCalledWith(
        "task-question",
        "question-1",
        "2",
        "2",
      ),
    );
    expect(await screen.findByText("已回答")).toBeInTheDocument();
    expect(mockedGetTask).toHaveBeenCalledTimes(2);
    expect(mockedConnect).toHaveBeenCalled();
  });

  it("restores a permission request and lets the user approve it", async () => {
    window.history.replaceState({}, "", "/?task=task-permission");
    const publicState = {
      task_id: "task-permission",
      original_request: "修改 main.py",
      status: "waiting_user" as const,
      revision: 2,
      actions: [
        {
          sequence: 1,
          action: {
            action_id: "action-1",
            action_type: "tool_call",
            tool_name: "edit_file",
            reason: "修复返回值",
            arguments: { path: "main.py" },
          },
          user_response: null,
          permission_request: {
            permission_request_id: "permission-1",
            tool_name: "edit_file",
            reason: "修改文件需要确认",
            arguments: { path: "main.py" },
          },
          permission_decision: null,
          observation: null,
        },
      ],
    };
    mockedGetTask.mockResolvedValue(publicState);
    mockedPermission.mockResolvedValue({
      ...publicState,
      status: "running",
      revision: 4,
      actions: [
        {
          ...publicState.actions[0],
          permission_decision: { decision: "approve", raw_response: "批准" },
        },
      ],
    });
    const user = userEvent.setup();
    render(<App />);

    expect((await screen.findAllByText("修改文件需要确认")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "批准并执行" }));

    await waitFor(() =>
      expect(mockedPermission).toHaveBeenCalledWith(
        "task-permission",
        "permission-1",
        "approve",
        "批准本次 edit_file 操作",
      ),
    );
    expect(await screen.findByText("已批准")).toBeInTheDocument();
  });

  it("pauses at the batch limit and only reconnects after the user continues", async () => {
    window.history.replaceState({}, "", "/?task=task-long");
    mockedGetTask.mockResolvedValue({
      task_id: "task-long",
      original_request: "检查整个项目",
      status: "running",
      revision: 1,
      actions: [],
    });
    const user = userEvent.setup();
    render(<App />);

    expect((await screen.findAllByText("检查整个项目")).length).toBeGreaterThan(0);
    await waitFor(() => expect(mockedConnect).toHaveBeenCalledTimes(1));

    act(() => {
      mockedConnect.mock.calls[0][1].onEvent({
        type: "task.step_limit_reached",
        sequence: 21,
        data: {
          max_steps: 20,
          message: "本轮已执行 20 步，任务仍未结束。请检查结果后再继续。",
        },
      });
    });

    expect(await screen.findByRole("button", { name: "继续运行" })).toBeInTheDocument();
    expect(mockedConnect).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "继续运行" }));
    await waitFor(() => expect(mockedConnect).toHaveBeenCalledTimes(2));
  });

  it("toggles the project files drawer from the header button", async () => {
    window.history.replaceState({}, "", "/?task=task-files");
    mockedGetTask.mockResolvedValue({
      task_id: "task-files",
      original_request: "检查项目文件",
      status: "completed",
      revision: 2,
      actions: [],
    });
    mockedListFiles.mockResolvedValue([
      {
        path: "calculator.py",
        size_bytes: 128,
        sha256: "a".repeat(64),
        state: "active",
      },
    ]);
    const user = userEvent.setup();
    render(<App />);

    const trigger = await screen.findByRole("button", { name: "项目文件 · 1" });
    await user.click(trigger);
    expect(screen.getByRole("complementary", { name: "项目文件" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载工作区 ZIP" })).toHaveAttribute(
      "href",
      "/tasks/task-files/workspace.zip",
    );

    await user.click(trigger);
    expect(screen.queryByRole("complementary", { name: "项目文件" })).not.toBeInTheDocument();
  });

  it("renders a long completion summary as readable body text", async () => {
    const summary = "已完成读取与分析。这里包含文件定位、依赖说明和执行结果，不应整段显示成巨大的粗体标题。";
    window.history.replaceState({}, "", "/?task=task-complete");
    mockedGetTask.mockResolvedValue({
      task_id: "task-complete",
      original_request: "分析示例代码",
      status: "completed",
      revision: 2,
      actions: [
        {
          sequence: 1,
          action: { action_id: "complete-1", action_type: "complete", reason: "分析结束", summary },
          user_response: null,
          permission_request: null,
          permission_decision: null,
          observation: null,
        },
      ],
    });
    render(<App />);

    expect(screen.queryByRole("heading", { name: summary })).not.toBeInTheDocument();
    const answer = await screen.findByText(summary);
    expect(answer.tagName).toBe("P");
    expect(answer.closest(".chat-row--assistant")).toBeInTheDocument();
  });

  it("groups each follow-up with the ForgeMind answer produced after it", async () => {
    window.history.replaceState({}, "", "/?task=task-conversation");
    mockedGetTask.mockResolvedValue({
      task_id: "task-conversation",
      original_request: "第一个问题",
      status: "completed",
      revision: 5,
      actions: [
        {
          sequence: 1,
          action: { action_id: "complete-1", action_type: "complete", reason: "第一轮完成", summary: "第一个回答" },
          user_response: null,
          permission_request: null,
          permission_decision: null,
          observation: null,
        },
        {
          sequence: 2,
          action: { action_id: "complete-2", action_type: "complete", reason: "第二轮完成", summary: "第二个回答" },
          user_response: null,
          permission_request: null,
          permission_decision: null,
          observation: null,
        },
      ],
      messages: [
        {
          message_id: "message-1",
          sequence: 1,
          content: "第二个问题",
          delivery: "applied",
          applied_after_action_sequence: 1,
          attachments: [],
        },
        {
          message_id: "message-2",
          sequence: 2,
          content: "第二个问题的补充",
          delivery: "applied",
          applied_after_action_sequence: 1,
          attachments: [],
        },
      ],
    });
    render(<App />);

    const firstRound = await screen.findByRole("region", { name: "对话第 1 轮" });
    const secondRound = screen.getByRole("region", { name: "对话第 2 轮" });
    expect(screen.getAllByRole("region", { name: /对话第 \d+ 轮/ })).toHaveLength(2);
    expect(firstRound).toHaveTextContent("第一个问题");
    expect(firstRound).toHaveTextContent("第一个回答");
    expect(firstRound).not.toHaveTextContent("第二个回答");
    expect(secondRound).toHaveTextContent("第二个问题");
    expect(secondRound).toHaveTextContent("第二个问题的补充");
    expect(secondRound).toHaveTextContent("第二个回答");
    expect(secondRound).not.toHaveTextContent("第一个回答");
  });
});
