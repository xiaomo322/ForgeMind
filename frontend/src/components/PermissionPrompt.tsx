import type { PermissionRequiredData } from "../types";

export function PermissionPrompt({
  prompt,
  disabled,
  onDecision,
}: {
  prompt: PermissionRequiredData;
  disabled: boolean;
  onDecision: (decision: "approve" | "reject") => Promise<void>;
}) {
  return (
    <aside className="interaction-panel interaction-panel--permission" aria-labelledby="permission-title">
      <p className="machine-label">PERMISSION REQUIRED</p>
      <h2 id="permission-title">{prompt.reason}</h2>
      <p>Runtime 已暂停，只有这条已登记的 {prompt.tool_name} Action 会受到你的决定影响。</p>
      <pre>{JSON.stringify(prompt.arguments, null, 2)}</pre>
      <div className="button-row">
        <button className="primary-button" type="button" disabled={disabled} onClick={() => onDecision("approve")}>批准并执行</button>
        <button className="danger-button" type="button" disabled={disabled} onClick={() => onDecision("reject")}>拒绝本次操作</button>
      </div>
    </aside>
  );
}
