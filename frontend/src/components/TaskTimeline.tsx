import type { TimelineItem } from "../taskState";

function value(record: Record<string, unknown>, key: string): string {
  const result = record[key];
  return typeof result === "string" ? result : "";
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function TaskTimeline({ timeline }: { timeline: TimelineItem[] }) {
  return (
    <section className="timeline-panel" aria-labelledby="timeline-title" aria-live="polite">
      <div className="section-heading">
        <div>
          <p className="machine-label">LIVE TRACE</p>
          <h2 id="timeline-title">执行时间线</h2>
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
          {timeline.map((item) => {
            if (item.kind === "step") {
              const decision = item.data.decision;
              const toolName = value(decision, "tool_name");
              const actionType = value(decision, "action_type");
              const reason = value(decision, "reason");
              return (
                <li className="timeline-item" key={`${item.kind}-${item.sequence}`}>
                  <div className="timeline-index">{item.data.step_number.toString().padStart(2, "0")}</div>
                  <article>
                    <div className="timeline-meta">
                      <span>{toolName || actionType || "agent"}</span>
                      <span>已记录</span>
                    </div>
                    <h3>{reason || "Agent 已完成一轮决策"}</h3>
                    <details>
                      <summary>查看结构化事实</summary>
                      <pre>{pretty({ decision, runtime: item.data.runtime })}</pre>
                    </details>
                  </article>
                </li>
              );
            }
            if (item.kind === "completion") {
              return <li className="terminal-note terminal-note--success" key={`done-${item.sequence}`}>{item.summary}</li>;
            }
            if (item.kind === "failure") {
              return <li className="terminal-note terminal-note--danger" key={`failed-${item.sequence}`}>{item.message}</li>;
            }
            return null;
          })}
        </ol>
      )}
    </section>
  );
}
