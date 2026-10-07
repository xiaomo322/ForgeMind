import { useState, type FormEvent } from "react";

const MAX_FILES = 20;
const MAX_FILE_SIZE = 1024 * 1024;
const MAX_TOTAL_SIZE = 5 * 1024 * 1024;

function validateFiles(files: File[]): string | null {
  if (files.length === 0) return "请至少选择一个 Python 文件。";
  if (files.length > MAX_FILES) return "一次最多上传 20 个文件。";
  const names = new Set<string>();
  let total = 0;
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith(".py")) return "只支持 .py 文件。";
    if (names.has(file.name.toLowerCase())) return "文件名不能重复。";
    if (file.size > MAX_FILE_SIZE) return `${file.name} 超过 1 MiB。`;
    names.add(file.name.toLowerCase());
    total += file.size;
  }
  return total > MAX_TOTAL_SIZE ? "文件总大小不能超过 5 MiB。" : null;
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB`;
}

interface WorkspaceFormProps {
  onStart: (files: File[], request: string) => Promise<void>;
}

export function WorkspaceForm({ onStart }: WorkspaceFormProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [request, setRequest] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function selectFiles(selected: File[]) {
    const validationError = validateFiles(selected);
    setFiles(validationError ? [] : selected);
    setError(validationError);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const validationError = validateFiles(files);
    if (validationError) return setError(validationError);
    if (!request.trim()) return setError("请说明希望 Agent 完成的任务。");
    setSubmitting(true);
    setError(null);
    try {
      await onStart(files, request);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务创建失败。请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="launch-form" onSubmit={submit}>
      <div className="launch-copy">
        <p className="machine-label">NEW WORKSPACE</p>
        <h1>把代码交给 Agent，保留每一步证据。</h1>
        <p>
          上传 1–20 个 UTF-8 Python 文件，再描述目标。ForgeMind 会读取、检索、修改和验证；高风险操作先等你确认。
        </p>
      </div>

      <div className="form-field file-field">
        <label htmlFor="python-files">选择 Python 文件</label>
        <input
          id="python-files"
          type="file"
          accept=".py,text/x-python"
          multiple
          onChange={(event) => selectFiles(Array.from(event.target.files ?? []))}
        />
        <span className="field-help">单个文件 ≤ 1 MiB，总计 ≤ 5 MiB</span>
      </div>

      {files.length > 0 && (
        <ul className="selected-files" aria-label="已选择文件">
          {files.map((file) => (
            <li key={file.name}>
              <span>{file.name}</span>
              <span>{formatSize(file.size)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="form-field">
        <label htmlFor="task-request">任务目标</label>
        <textarea
          id="task-request"
          rows={5}
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          placeholder="例如：检查价格计算逻辑，修复折扣错误并运行测试验证。"
        />
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={submitting}>
        {submitting ? "正在创建工作区…" : "启动 Agent"}
      </button>
    </form>
  );
}
