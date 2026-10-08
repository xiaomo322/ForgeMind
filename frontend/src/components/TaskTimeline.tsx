import type { TimelineItem } from "../taskState";

function value(record: Record<string, unknown>, key: string): string {
  const result = record[key];
  return typeof result === "string" ? result : "";
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : null;
}

const TOOL_LABELS: Record<string, string> = {
  read_file: "读取文件",
  search_code: "搜索代码",
  edit_file: "修改文件",
  run_tests: "运行测试",
  run_command: "运行命令",
};

function stepLabel(toolName: string, actionType: string): string {
  if (toolName) return TOOL_LABELS[toolName] ?? toolName;
  if (actionType === "complete") return "整理结果";
  return actionType || "Agent 决策";
}

function observationSummary(toolName: string, runtime: Record<string, unknown>): string {
  const observation = record(runtime.observation);
  const result = record(observation?.result);
  if (!observation) return "等待 Runtime 处理";

  const status = value(observation, "status");
  if (status === "rejected") return "操作已被 Runtime 或用户拒绝";
  if (status === "failed") return value(observation, "error") || "工具执行失败，详情可在结构化事实中查看";
  if (!result) return status === "success" ? "执行成功" : "已记录执行结果";

  if (toolName === "search_code") {
    const count = typeof result.returned_count === "number" ? result.returned_count : null;
    return count === null ? "代码搜索完成" : `找到 ${count} 个匹配结果`;
  }
  if (toolName === "read_file") {
    const path = value(result, "path");
    const start = result.start_line;
    const end = result.end_line;
    const range = typeof start === "number" ? `第 ${start}${typeof end === "number" ? `–${end}` : ""} 行` : "";
    return [path, range, result.eof === true ? "已到文件末尾" : "仍有后续内容"].filter(Boolean).join(" · ");
  }
  if (toolName === "edit_file") return `${value(result, "path") || "文件"} 已更新`;
  if (toolName === "run_tests") {
    const outcome = value(result, "test_outcome");
    const passed = typeof result.passed === "number" ? result.passed : 0;
    const failed = typeof result.failed === "number" ? result.failed : 0;
    return `测试 ${outcome || "已结束"} · ${passed} 通过 · ${failed} 失败`;
  }
  if (toolName === "run_command") {
    return typeof result.exit_code === "number" ? `命令结束，退出码 ${result.exit_code}` : "命令执行结束";
  }
  return status === "success" ? "执行成功" : "已记录执行结果";
}

export function TaskTimeline({ timeline, titleId = "timeline-title" }: { timeline: TimelineItem[]; titleId?: string }) {
  return (
    <section className="timeline-panel" aria-labelledby={titleId} aria-live="polite">
      <div className="section-heading">
        <div>
          <p className="machine-label">LIVE TRACE</p>
          <h2 id={titleId}>执行过程</h2>
        </div>
        <span>{timeline.length} 条事件</span>
      </div>
      {timeline.length === 0 ? (
        <div className="timeline-empty" role="status">
          <span className="pulse-mark" aria-hidden="true" />
          <p>连接已建立，正在等待 Agent 的第一步决策。</p>
        </div>
      ) : (
        <ol className="timeline-list">
          {timeline.map((item, index) => {
            const key = `${item.kind}-${item.sequence}-${index}`;
            if (item.kind === "step") {
              const decision = item.data.decision;
              const toolName = value(decision, "tool_name");
              const actionType = value(decision, "action_type");
              const reason = value(decision, "reason");
              const observation = record(item.data.runtime.observation);
              const observationStatus = observation ? value(observation, "status") : "pending";
              return (
                <li className="timeline-item" key={key}>
                  <div className="timeline-index">{(index + 1).toString().padStart(2, "0")}</div>
                  <article>
                    <div className="timeline-meta">
                      <span>{stepLabel(toolName, actionType)}</span>
                      <span className={`event-status event-status--${observationStatus}`}>{observationStatus === "success" ? "成功" : observationStatus === "failed" ? "失败" : observationStatus === "rejected" ? "已拒绝" : "已记录"}</span>
                    </div>
                    <h3>{reason || "Agent 已完成一轮决策"}</h3>
                    <p className="timeline-result">{observationSummary(toolName, item.data.runtime)}</p>
                    <details>
                      <summary>查看执行详情</summary>
                      <pre>{pretty({ decision, runtime: item.data.runtime })}</pre>
                    </details>
                  </article>
                </li>
              );
            }
            if (item.kind === "question") {
              const answer = item.response ? value(item.response, "raw_response") : "";
              return (
                <li className="timeline-item timeline-interaction" key={key}>
                  <div className="timeline-index">{(index + 1).toString().padStart(2, "0")}</div>
                  <article>
                    <div className="timeline-meta"><span>用户问题</span><span>{item.response ? "已回答" : "等待回答"}</span></div>
                    <h3>{item.data.question}</h3>
                    {answer && <p>你的回答：{answer}</p>}
                    <details><summary>查看问答事实</summary><pre>{pretty({ question: item.data, response: item.response })}</pre></details>
                  </article>
                </li>
              );
            }
            if (item.kind === "permission") {
              const decision = item.decision ? value(item.decision, "decision") : "";
              const decisionLabel = decision === "approve" ? "已批准" : decision === "reject" ? "已拒绝" : "等待决定";
              return (
                <li className="timeline-item timeline-interaction" key={key}>
                  <div className="timeline-index">{(index + 1).toString().padStart(2, "0")}</div>
                  <article>
                    <div className="timeline-meta"><span>{item.data.tool_name} 权限</span><span>{decisionLabel}</span></div>
                    <h3>{item.data.reason}</h3>
                    <details><summary>查看权限事实</summary><pre>{pretty({ request: item.data, decision: item.decision })}</pre></details>
                  </article>
                </li>
              );
            }
            if (item.kind === "completion") {
              return <li className="terminal-note terminal-note--success" key={key}>Agent 已完成本次任务，完整结果见下方。</li>;
            }
            if (item.kind === "pause") {
              return <li className="terminal-note terminal-note--pause" key={key}>{item.message}</li>;
            }
            if (item.kind === "failure") {
              return <li className="terminal-note terminal-note--danger" key={key}>{item.message}</li>;
            }
            return null;
          })}
        </ol>
      )}
    </section>
  );
}
