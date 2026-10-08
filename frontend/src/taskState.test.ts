import { describe, expect, it } from "vitest";

import { hydrateTaskUiState, initialTaskUiState, taskStateReducer } from "./taskState";
import type { PublicTaskState, TaskEvent } from "./types";


function reduce(event: TaskEvent) {
  return taskStateReducer(initialTaskUiState("task-1"), event);
}

describe("taskStateReducer", () => {
  it("adds a completed Agent step to the timeline", () => {
    const state = reduce({
      type: "agent.step",
      sequence: 1,
      data: {
        step_number: 1,
        decision: { action_type: "tool_call", tool_name: "read_file" },
        runtime: { observation: { status: "success" } },
      },
    });

    expect(state.timeline).toHaveLength(1);
    expect(state.timeline[0].kind).toBe("step");
    expect(state.status).toBe("running");
  });

  it("stores the exact pending user question", () => {
    const state = reduce({
      type: "task.waiting_user",
      sequence: 2,
      data: {
        question_action_id: "action-question",
        reason: "缺少选择",
        question: "请选择目标值",
        options: ["2", "3"],
      },
    });

    expect(state.status).toBe("waiting_user");
    expect(state.pendingQuestion?.question_action_id).toBe("action-question");
  });

  it("stores the exact pending permission request", () => {
    const state = reduce({
      type: "task.permission_required",
      sequence: 2,
      data: {
        permission_request_id: "permission-1",
        tool_name: "edit_file",
        reason: "修改文件需要确认",
        arguments: { path: "main.py" },
      },
    });

    expect(state.status).toBe("waiting_user");
    expect(state.pendingPermission?.permission_request_id).toBe("permission-1");
  });

  it("records completion and clears interactive waits", () => {
    const state = reduce({
      type: "task.completed",
      sequence: 3,
      data: { summary: "修改完成，测试通过" },
    });

    expect(state.status).toBe("completed");
    expect(state.summary).toBe("修改完成，测试通过");
    expect(state.pendingQuestion).toBeNull();
  });

  it("records a safe public failure", () => {
    const state = reduce({
      type: "task.failed",
      sequence: 4,
      data: { category: "internal_error", message: "任务执行失败" },
    });

    expect(state.error).toBe("任务执行失败");
    expect(state.status).toBe("failed");
    expect(state.timeline.at(-1)?.kind).toBe("failure");
  });

  it("pauses after one execution batch until the user continues", () => {
    const state = reduce({
      type: "task.step_limit_reached",
      sequence: 21,
      data: {
        max_steps: 20,
        message: "本轮已执行 20 步，任务仍未结束。请检查结果后再继续。",
      },
    });

    expect(state.status).toBe("paused");
    expect(state.timeline.at(-1)?.kind).toBe("pause");
  });

  it("keeps answered questions and decided permissions in the restored audit trail", () => {
    const task: PublicTaskState = {
      task_id: "task-audit",
      original_request: "修改并测试项目",
      status: "running",
      revision: 8,
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
          user_response: { raw_response: "2", selected_option: "2" },
          permission_request: null,
          permission_decision: null,
          observation: null,
        },
        {
          sequence: 2,
          action: { action_id: "edit-1", action_type: "tool_call", tool_name: "edit_file" },
          user_response: null,
          permission_request: {
            permission_request_id: "permission-1",
            tool_name: "edit_file",
            reason: "修改文件需要确认",
            arguments: { path: "main.py" },
          },
          permission_decision: { decision: "approve", raw_response: "批准" },
          observation: { status: "success" },
        },
      ],
    };

    const state = hydrateTaskUiState(task);
    const question = state.timeline.find((item) => item.kind === "question");
    const permission = state.timeline.find((item) => item.kind === "permission");

    expect(question).toMatchObject({ response: { raw_response: "2" } });
    expect(permission).toMatchObject({ decision: { decision: "approve" } });
    expect(state.pendingQuestion).toBeNull();
    expect(state.pendingPermission).toBeNull();
  });

  it("does not expose an old completion as the current result after a follow-up resumes the task", () => {
    const task: PublicTaskState = {
      task_id: "task-follow-up",
      original_request: "先分析文件",
      status: "running",
      revision: 4,
      actions: [
        {
          sequence: 1,
          action: {
            action_id: "complete-1",
            action_type: "complete",
            reason: "第一轮完成",
            summary: "第一轮回答",
          },
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
          content: "继续解释",
          delivery: "applied",
          applied_after_action_sequence: 1,
          attachments: [],
        },
      ],
    };

    expect(hydrateTaskUiState(task).summary).toBeNull();
  });
});
