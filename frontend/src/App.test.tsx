import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import {
  answerQuestion,
  connectTaskEvents,
  createTask,
  decidePermission,
  getTask,
  uploadWorkspace,
} from "./api";

vi.mock("./api", () => ({
  answerQuestion: vi.fn(),
  connectTaskEvents: vi.fn(() => vi.fn()),
  createTask: vi.fn(),
  decidePermission: vi.fn(),
  getTask: vi.fn(),
  uploadWorkspace: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadWorkspace);
const mockedCreate = vi.mocked(createTask);
const mockedGetTask = vi.mocked(getTask);
const mockedAnswer = vi.mocked(answerQuestion);
const mockedPermission = vi.mocked(decidePermission);
const mockedConnect = vi.mocked(connectTaskEvents);

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("ForgeMind App", () => {
  it("rejects a non-Python file before uploading", async () => {
    render(<App />);

    fireEvent.change(screen.getByLabelText("选择 Python 文件"), {
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
      screen.getByLabelText("选择 Python 文件"),
      new File(["value = 1\n"], "main.py", { type: "text/x-python" }),
    );
    await user.type(screen.getByLabelText("任务目标"), "检查价格计算");
    await user.click(screen.getByRole("button", { name: "启动 Agent" }));

    expect(await screen.findByText("检查价格计算")).toBeInTheDocument();
    expect(screen.getByText("task-1")).toBeInTheDocument();
    expect(mockedUpload).toHaveBeenCalledTimes(1);
    expect(mockedCreate).toHaveBeenCalledWith("检查价格计算", "workspace-1");
    expect(mockedConnect).toHaveBeenCalled();
  });

  it("restores and answers an Agent question", async () => {
    window.history.replaceState({}, "", "/?task=task-question");
    mockedGetTask.mockResolvedValue({
      task_id: "task-question",
      original_request: "修改 value",
      status: "waiting_user",
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

    expect(await screen.findByText("value 应改成多少？")).toBeInTheDocument();
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
    mockedPermission.mockResolvedValue({ ...publicState, status: "running", revision: 4 });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("修改文件需要确认")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "批准并执行" }));

    await waitFor(() =>
      expect(mockedPermission).toHaveBeenCalledWith(
        "task-permission",
        "permission-1",
        "approve",
        "批准本次 edit_file 操作",
      ),
    );
  });
});
