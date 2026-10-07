import { describe, expect, it } from "vitest";

import { initialTaskUiState, taskStateReducer } from "./taskState";
import type { TaskEvent } from "./types";


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
    expect(state.timeline.at(-1)?.kind).toBe("failure");
  });
});
