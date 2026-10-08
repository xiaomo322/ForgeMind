import { TaskTimeline } from "./TaskTimeline";
import { timelineItemsFromActions } from "../taskState";
import type { PublicActionState, PublicAttachment, PublicTaskMessage } from "../types";

interface RoundMessage {
  id: string;
  content: string | null;
  delivery: "queued" | "applied";
  attachments: PublicAttachment[];
}

interface ConversationRound {
  key: string;
  messages: RoundMessage[];
  actions: PublicActionState[];
}

function buildRounds(
  originalRequest: string,
  messages: PublicTaskMessage[],
  actions: PublicActionState[],
): ConversationRound[] {
  const orderedActions = [...actions].sort((left, right) => left.sequence - right.sequence);
  const appliedMessages = messages
    .filter((message) => message.delivery === "applied" && message.applied_after_action_sequence !== null)
    .sort((left, right) => left.sequence - right.sequence);
  const queuedMessages = messages
    .filter((message) => message.delivery === "queued" || message.applied_after_action_sequence === null)
    .sort((left, right) => left.sequence - right.sequence);

  const rounds: ConversationRound[] = [];
  let actionCursor = 0;
  let currentMessages: RoundMessage[] = [{
    id: "original-request",
    content: originalRequest,
    delivery: "applied",
    attachments: [],
  }];

  appliedMessages.forEach((message) => {
    const boundary = message.applied_after_action_sequence ?? actionCursor;
    const roundMessage: RoundMessage = {
      id: message.message_id,
      content: message.content,
      delivery: message.delivery,
      attachments: message.attachments,
    };
    if (boundary > actionCursor) {
      rounds.push({
        key: currentMessages[0].id,
        messages: currentMessages,
        actions: orderedActions.filter((action) => action.sequence > actionCursor && action.sequence <= boundary),
      });
      actionCursor = boundary;
      currentMessages = [roundMessage];
      return;
    }
    // 同一安全边界应用的多条消息会一起进入下一次模型上下文，
    // 因而应连续显示为用户输入，随后只配一个真实的 Agent 回复。
    currentMessages.push(roundMessage);
  });

  rounds.push({
    key: currentMessages[0].id,
    messages: currentMessages,
    actions: orderedActions.filter((action) => action.sequence > actionCursor),
  });

  if (queuedMessages.length > 0) {
    rounds.push({
      key: queuedMessages[0].message_id,
      messages: queuedMessages.map((message) => ({
      id: message.message_id,
      content: message.content,
      delivery: message.delivery,
      attachments: message.attachments,
      })),
      actions: [],
    });
  }
  return rounds;
}

function text(record: Record<string, unknown>, key: string): string {
  return typeof record[key] === "string" ? record[key] as string : "";
}

function answerParagraphs(summary: string): string[] {
  const cleaned = summary
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
  return cleaned.split(/\n\s*\n/).filter(Boolean);
}

export function ConversationFeed({
  originalRequest,
  messages,
  actions,
}: {
  originalRequest: string;
  messages: PublicTaskMessage[];
  actions: PublicActionState[];
}) {
  const rounds = buildRounds(originalRequest, messages, actions);

  return <section className="conversation-feed" aria-label="对话记录">
    {rounds.map((round, index) => {
      const completion = [...round.actions]
        .reverse()
        .find((action) => action.action.action_type === "complete");
      const summary = completion ? text(completion.action, "summary") : "";
      const trace = timelineItemsFromActions(round.actions).filter((item) =>
        item.kind !== "completion" && !(item.kind === "step" && item.data.decision.action_type === "complete")
      );
      const waitingLabel = round.messages.some((message) => message.delivery === "queued")
        ? "消息已排队，等待当前步骤结束后处理。"
        : "ForgeMind 正在处理这条消息…";

      return <section className="conversation-round" aria-label={`对话第 ${index + 1} 轮`} key={round.key}>
        {round.messages.map((message) => <div className="chat-row chat-row--user" key={message.id}>
            <article className="chat-bubble chat-bubble--user">
              {message.content && <p>{message.content}</p>}
              {message.attachments.length > 0 && <div className="message-attachments">
                {message.attachments.map((file) => <span className="file-chip" key={file.upload_id}>📄 {file.path}</span>)}
              </div>}
              {message.id !== "original-request" && <small className={`delivery delivery--${message.delivery}`}>
                {message.delivery === "queued" ? "已排队" : "已应用"}
              </small>}
            </article>
            <span className="message-avatar" aria-hidden="true">你</span>
          </div>)}

        <div className="chat-row chat-row--assistant">
          <span className="message-avatar assistant-avatar" aria-hidden="true">FM</span>
          <article className="chat-bubble chat-bubble--assistant">
            <header><strong>ForgeMind</strong><span>{summary ? "已回答" : round.actions.length > 0 ? "处理中" : "等待中"}</span></header>
            {trace.length > 0 && <TaskTimeline timeline={trace} titleId={`timeline-title-${index}`} />}
            {summary ? <div className="assistant-answer">
              {answerParagraphs(summary).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>{paragraph}</p>)}
            </div> : <p className="assistant-waiting"><span className="pulse-mark" aria-hidden="true" />{waitingLabel}</p>}
          </article>
        </div>
      </section>;
    })}
  </section>;
}
