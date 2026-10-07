import { useState, type FormEvent } from "react";
import type { WaitingUserData } from "../types";

export function UserPrompt({
  prompt,
  disabled,
  onSubmit,
}: {
  prompt: WaitingUserData;
  disabled: boolean;
  onSubmit: (rawResponse: string, selectedOption: string | null) => Promise<void>;
}) {
  const [answer, setAnswer] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (answer.trim()) await onSubmit(answer, prompt.options ? answer : null);
  }
  return (
    <aside className="interaction-panel" aria-labelledby="question-title">
      <p className="machine-label">AGENT QUESTION</p>
      <h2 id="question-title">{prompt.question}</h2>
      <p>{prompt.reason}</p>
      <form onSubmit={submit}>
        {prompt.options ? (
          <fieldset className="option-list">
            <legend>选择一个选项</legend>
            {prompt.options.map((option) => (
              <label key={option}>
                <input type="radio" name="answer" value={option} checked={answer === option} onChange={() => setAnswer(option)} />
                <span>{option}</span>
              </label>
            ))}
          </fieldset>
        ) : (
          <div className="form-field">
            <label htmlFor="user-answer">你的回答</label>
            <textarea id="user-answer" rows={3} value={answer} onChange={(event) => setAnswer(event.target.value)} />
          </div>
        )}
        <button className="primary-button" disabled={disabled || !answer.trim()}>提交回答</button>
      </form>
    </aside>
  );
}
