import { useRef, useState, type FormEvent } from "react";

interface Props {
  busy: boolean;
  running: boolean;
  onSend: (content: string, files: File[]) => Promise<void>;
}

export function MessageComposer({ busy, running, onSend }: Props) {
  const [content, setContent] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const input = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!content.trim() && files.length === 0) return;
    await onSend(content, files);
    setContent("");
    setFiles([]);
    if (input.current) input.current.value = "";
  }

  return <form className="message-composer" onSubmit={submit}>
    {files.length > 0 && <div className="composer-files">{files.map((file) =>
      <span className="file-chip" key={file.name}>📄 {file.name}<button type="button" aria-label={`移除 ${file.name}`} onClick={() => setFiles(files.filter((item) => item !== file))}>×</button></span>
    )}</div>}
    <textarea aria-label="继续输入任务要求" value={content} onChange={(event) => setContent(event.target.value)} placeholder="继续告诉 ForgeMind 要检查或修改什么…" />
    <div className="composer-footer">
      <label className="attach-control">＋<span className="sr-only">添加 Python 文件</span><input ref={input} aria-label="添加 Python 文件" type="file" accept=".py" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} /></label>
      <span>{running ? "Agent 正在运行；新消息将在安全边界应用" : "消息会保存在当前任务"}</span>
      <button className="composer-send" type="submit" disabled={busy} aria-label="发送">↑</button>
    </div>
  </form>;
}
