import type { TaskFile } from "../types";

interface Props { open: boolean; files: TaskFile[]; onClose: () => void; onDeleteStaged: (uploadId: string) => void; }

export function ProjectFilesDrawer({ open, files, onClose, onDeleteStaged }: Props) {
  if (!open) return null;
  return <aside className="files-drawer" aria-label="项目文件">
    <header><strong>项目文件</strong><button type="button" onClick={onClose} aria-label="关闭项目文件">×</button></header>
    <ul>{files.map((file) => <li key={`${file.state}-${file.path}`}>
      <strong>{file.path}</strong>
      <span>{file.state === "active" ? "已保存" : "等待应用"} · {(file.size_bytes / 1024).toFixed(1)} KiB</span>
      <code>{file.sha256.slice(0, 12)}…</code>
      {file.state === "staged" && file.upload_id && <button type="button" onClick={() => onDeleteStaged(file.upload_id!)}>删除暂存文件</button>}
    </li>)}</ul>
  </aside>;
}
