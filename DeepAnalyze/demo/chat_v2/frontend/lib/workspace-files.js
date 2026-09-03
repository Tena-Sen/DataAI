function normalizeWorkspacePath(path) {
  return String(path || "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "")
    .trim();
}

function isGeneratedWorkspaceFile(file) {
  if (!file) return false;
  if (file.is_generated === true) return true;
  const path = normalizeWorkspacePath(file.path);
  return path === "generated" || path.startsWith("generated/");
}

function isPythonWorkspaceFile(file) {
  const values =
    typeof file === "string"
      ? [file]
      : [file?.extension, file?.name, file?.path];
  return values.some((value) => {
    if (!value) return false;
    let normalized = String(value).trim().toLowerCase();
    try {
      normalized = decodeURIComponent(normalized);
    } catch {}
    return (
      normalized === "py" ||
      normalized === ".py" ||
      /\.py(?:$|[?#&])/.test(normalized)
    );
  });
}

function filterPythonFileLinks(content) {
  return String(content || "")
    .split(/\r?\n/)
    .filter((line) => {
      const links = line.matchAll(/!?\[([^\]]*)\]\(([^)]+)\)/g);
      return !Array.from(links).some((match) =>
        isPythonWorkspaceFile({ name: match[1], path: match[2] })
      );
    })
    .join("\n")
    .trim();
}

function isVisibleWorkspaceFile(file) {
  return !(isGeneratedWorkspaceFile(file) && isPythonWorkspaceFile(file));
}

function countWorkspaceFiles(files) {
  const list = (Array.isArray(files) ? files : []).filter(isVisibleWorkspaceFile);
  const generated = list.filter(isGeneratedWorkspaceFile).length;
  return {
    uploaded: list.length - generated,
    generated,
    all: list.length,
  };
}

function filterWorkspaceFiles(files, view, query = "") {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  return (Array.isArray(files) ? files : [])
    .filter(isVisibleWorkspaceFile)
    .filter((file) => {
      const generated = isGeneratedWorkspaceFile(file);
      if (view === "generated" && !generated) return false;
      if (view === "uploaded" && generated) return false;
      if (!normalizedQuery) return true;
      return [file.name, file.path].some((value) =>
        String(value || "").toLowerCase().includes(normalizedQuery)
      );
    })
    .sort((left, right) => {
      const leftGenerated = isGeneratedWorkspaceFile(left);
      const rightGenerated = isGeneratedWorkspaceFile(right);
      if (leftGenerated !== rightGenerated) return leftGenerated ? 1 : -1;
      return String(left.name || "").localeCompare(String(right.name || ""));
    });
}

module.exports = {
  countWorkspaceFiles,
  filterPythonFileLinks,
  filterWorkspaceFiles,
  isGeneratedWorkspaceFile,
  isPythonWorkspaceFile,
  normalizeWorkspacePath,
};
