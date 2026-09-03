import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { buildLineDiff } = require("./code-ai-edit.js");

test("buildLineDiff marks unchanged, removed, and added lines", () => {
  const rows = buildLineDiff("a\nb\nc", "a\nB\nc\nd");

  assert.deepEqual(
    rows.map((row) => ({
      type: row.type,
      oldLineNumber: row.oldLineNumber,
      newLineNumber: row.newLineNumber,
      content: row.content,
    })),
    [
      { type: "unchanged", oldLineNumber: 1, newLineNumber: 1, content: "a" },
      { type: "removed", oldLineNumber: 2, newLineNumber: null, content: "b" },
      { type: "added", oldLineNumber: null, newLineNumber: 2, content: "B" },
      { type: "unchanged", oldLineNumber: 3, newLineNumber: 3, content: "c" },
      { type: "added", oldLineNumber: null, newLineNumber: 4, content: "d" },
    ]
  );
});

test("buildLineDiff keeps identical code as unchanged rows", () => {
  const rows = buildLineDiff("print(1)\n", "print(1)\n");

  assert.deepEqual(rows, [
    {
      id: "same-1-1",
      type: "unchanged",
      oldLineNumber: 1,
      newLineNumber: 1,
      content: "print(1)",
    },
  ]);
});
