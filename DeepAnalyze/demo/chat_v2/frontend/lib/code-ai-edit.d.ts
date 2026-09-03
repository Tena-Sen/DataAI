export type CodeDiffRow = {
  id: string;
  type: "unchanged" | "removed" | "added";
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
};

export function splitCodeLines(code: string): string[];

export function buildLineDiff(oldCode: string, newCode: string): CodeDiffRow[];
