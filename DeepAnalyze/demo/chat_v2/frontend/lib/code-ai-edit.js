function splitCodeLines(code) {
  const normalized = String(code ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

function buildLineDiff(oldCode, newCode) {
  const oldLines = splitCodeLines(oldCode);
  const newLines = splitCodeLines(newCode);
  const table = Array.from({ length: oldLines.length + 1 }, () =>
    Array(newLines.length + 1).fill(0)
  );

  for (let i = oldLines.length - 1; i >= 0; i -= 1) {
    for (let j = newLines.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        oldLines[i] === newLines[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const rows = [];
  let oldIndex = 0;
  let newIndex = 0;
  while (oldIndex < oldLines.length || newIndex < newLines.length) {
    if (
      oldIndex < oldLines.length &&
      newIndex < newLines.length &&
      oldLines[oldIndex] === newLines[newIndex]
    ) {
      rows.push({
        id: `same-${oldIndex + 1}-${newIndex + 1}`,
        type: "unchanged",
        oldLineNumber: oldIndex + 1,
        newLineNumber: newIndex + 1,
        content: oldLines[oldIndex],
      });
      oldIndex += 1;
      newIndex += 1;
      continue;
    }

    if (
      newIndex >= newLines.length ||
      (oldIndex < oldLines.length &&
        table[oldIndex + 1][newIndex] >= table[oldIndex][newIndex + 1])
    ) {
      rows.push({
        id: `remove-${oldIndex + 1}-${newIndex + 1}`,
        type: "removed",
        oldLineNumber: oldIndex + 1,
        newLineNumber: null,
        content: oldLines[oldIndex],
      });
      oldIndex += 1;
      continue;
    }

    rows.push({
      id: `add-${oldIndex + 1}-${newIndex + 1}`,
      type: "added",
      oldLineNumber: null,
      newLineNumber: newIndex + 1,
      content: newLines[newIndex],
    });
    newIndex += 1;
  }

  return rows;
}

module.exports = {
  buildLineDiff,
  splitCodeLines,
};
