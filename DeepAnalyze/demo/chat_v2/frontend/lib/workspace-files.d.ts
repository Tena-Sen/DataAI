export type WorkspaceFileLike = {
  name?: string;
  path?: string;
  extension?: string;
  is_generated?: boolean;
};

export type WorkspaceView = "all" | "uploaded" | "generated";

export function normalizeWorkspacePath(path?: string | null): string;
export function isGeneratedWorkspaceFile(
  file?: WorkspaceFileLike | null
): boolean;
export function isPythonWorkspaceFile(
  file?: WorkspaceFileLike | string | null
): boolean;
export function filterPythonFileLinks(content?: string | null): string;
export function countWorkspaceFiles(files: WorkspaceFileLike[]): {
  uploaded: number;
  generated: number;
  all: number;
};
export function filterWorkspaceFiles<T extends WorkspaceFileLike>(
  files: T[],
  view: WorkspaceView,
  query?: string
): T[];
