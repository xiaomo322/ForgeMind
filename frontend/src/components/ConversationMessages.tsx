import type { PublicTaskMessage } from "../types";

export function ConversationMessages({ originalRequest, messages }: { originalRequest: string; messages: PublicTaskMessage[] }) {
  return <section className="conversation-messages" aria-label="用户消息">
    <article className="conversation-message"><span className="message-avatar">你</span><div><p>{originalRequest}</p></div></article>
    {messages.map((message) => <article className="conversation-message" key={message.message_id}>
      <span className="message-avatar">你</span><div>{message.content && <p>{message.content}</p>}
      {message.attachments.length > 0 && <div className="message-attachments">{message.attachments.map((file) => <span className="file-chip" key={file.upload_id}>📄 {file.path}</span>)}</div>}
      <small className={`delivery delivery--${message.delivery}`}>{message.delivery === "queued" ? "已排队" : "已应用"}</small></div>
    </article>)}
  </section>;
}
