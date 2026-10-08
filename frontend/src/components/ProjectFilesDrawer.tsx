import type { TaskFile } from "../types";

interface Props { taskId: string; open: boolean; files: TaskFile[]; onClose: () => void; onDeleteStaged: (uploadId: string) => void; }

export function ProjectFilesDrawer({ taskId, open, files, onClose, onDeleteStaged }: Props) {
  if (!open) return null;
  return <>
    <button className="drawer-backdrop" type="button" onClick={onClose} aria-label="关闭项目文件" />
    <aside id="project-files-drawer" className="files-drawer" aria-label="项目文件">
      <header><div><strong>项目文件</strong><span>{files.length} 个文件</span></div><button type="button" onClick={onClose} aria-label="关闭项目文件抽屉">×</button></header>
      <a className="workspace-download" href={`/tasks/${encodeURIComponent(taskId)}/workspace.zip`} download>下载工作区 ZIP</a>
      {files.length === 0 ? <p className="files-empty">当前任务还没有项目文件。</p> : <ul>{files.map((file) => <li key={`${file.state}-${file.path}`}>
        <span className={`file-state file-state--${file.state}`}>{file.state === "active" ? "已保存" : "等待应用"}</span>
        <strong>{file.path}</strong>
        <span>{(file.size_bytes / 1024).toFixed(1)} KiB · {file.sha256.slice(0, 8)}</span>
        {file.state === "staged" && file.upload_id && <button className="file-delete" type="button" onClick={() => onDeleteStaged(file.upload_id!)}>删除暂存文件</button>}
      </li>)}</ul>}
    </aside>
  </>;
}
