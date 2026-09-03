import assert from "node:assert/strict";
import test from "node:test";
import {
  countWorkspaceFiles,
  filterPythonFileLinks,
  filterWorkspaceFiles,
  isGeneratedWorkspaceFile,
  isPythonWorkspaceFile,
} from "./workspace-files.js";

const files = [
  { name: "sales.csv", path: "sales.csv", is_generated: false },
  { name: "report.md", path: "report.md", is_generated: true },
  { name: "chart.png", path: "generated/chart.png", is_generated: true },
  { name: "notes.txt", path: "generated/notes.txt" },
  { name: "analysis.py", path: "generated/analysis.py", is_generated: true },
];

test("classifies generated files from backend metadata or generated paths", () => {
  assert.equal(isGeneratedWorkspaceFile(files[0]), false);
  assert.equal(isGeneratedWorkspaceFile(files[1]), true);
  assert.equal(isGeneratedWorkspaceFile(files[2]), true);
  assert.equal(isGeneratedWorkspaceFile(files[3]), true);
});

test("uploaded view never includes generated files with matching names", () => {
  const uploaded = filterWorkspaceFiles(
    [
      { name: "report.md", path: "report.md", is_generated: false },
      { name: "report.md", path: "generated/report.md", is_generated: true },
    ],
    "uploaded"
  );
  assert.deepEqual(uploaded.map((file) => file.path), ["report.md"]);
});

test("counts are mutually exclusive and exhaustive", () => {
  assert.deepEqual(countWorkspaceFiles(files), {
    uploaded: 1,
    generated: 3,
    all: 4,
  });
});

test("generated Python files are excluded while uploaded Python files remain visible", () => {
  const uploadedScript = {
    name: "source.py",
    path: "source.py",
    extension: ".PY",
    is_generated: false,
  };
  assert.equal(isPythonWorkspaceFile(uploadedScript), true);
  assert.deepEqual(
    filterWorkspaceFiles([...files, uploadedScript], "all").map((file) => file.name),
    ["sales.csv", "source.py", "chart.png", "notes.txt", "report.md"]
  );
  assert.deepEqual(
    filterWorkspaceFiles(files, "generated").map((file) => file.name),
    ["chart.png", "notes.txt", "report.md"]
  );
});

test("Python links are removed from File block content", () => {
  const content = [
    "- [analysis.py](/workspace/download?path=generated%2Fanalysis.py)",
    "- [report.md](/workspace/download?path=generated%2Freport.md)",
    "![chart.png](/workspace/download?path=generated%2Fchart.png)",
  ].join("\n");
  assert.equal(
    filterPythonFileLinks(content),
    [
      "- [report.md](/workspace/download?path=generated%2Freport.md)",
      "![chart.png](/workspace/download?path=generated%2Fchart.png)",
    ].join("\n")
  );
});
