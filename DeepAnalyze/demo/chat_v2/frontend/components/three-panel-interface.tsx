"use client";

import type React from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import Editor from "@monaco-editor/react";
import { useState, useRef, useEffect, useCallback, useMemo, memo } from "react";
import { configureMonaco } from "@/lib/monaco-config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API_URLS, API_CONFIG, buildApiUrlWithParams } from "@/lib/config";
import { buildLineDiff } from "@/lib/code-ai-edit";
import {
  buildSessionStorageKey,
  getActiveAnalysisAssistantMessageIndexes,
  isAwaitingManualContinuation,
  normalizeSessionMessages,
  normalizeInteractionMode,
  serializeSessionMessages,
  toServerMessages,
  toggleSelectedPath,
} from "@/lib/session-state";
import {
  countWorkspaceFiles,
  filterPythonFileLinks,
  filterWorkspaceFiles,
  isGeneratedWorkspaceFile,
  isPythonWorkspaceFile,
  normalizeWorkspacePath,
} from "@/lib/workspace-files";
import {
  findSampleSelection,
  normalizeSampleCatalog,
} from "@/lib/sample-catalog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import {
  Send,
  Sparkles,
  User,
  Plus,
  X,
  FileText,
  ImageIcon,
  ChevronDown,
  ChevronRight,
  Trash2,
  Download,
  Play,
  Save,
  FolderOpen,
  RefreshCw,
  Moon,
  Sun,
  Eraser,
  Copy,
  Check,
  Edit,
  Upload,
  Square,
  Code2,
  Eye,
  PanelRightOpen,
  Languages,
  FileSpreadsheet,
  Package,
  Archive,
  FileImage,
  FileCode2,
  FileJson,
  ChevronLeft,
  Database,
  Hand,
  CirclePause,
  Settings2,
  LogOut,
} from "lucide-react";
import { UNAUTHORIZED_EVENT, getUsername } from "@/components/auth-gate";
import { Tree, NodeApi } from "react-arborist";
import { useToast } from "@/hooks/use-toast";
import { FileIcon, defaultStyles } from "react-file-icon";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

interface Message {
  id: string;
  content: string;
  sender: "user" | "ai";
  timestamp: Date;
  attachments?: FileAttachment[];
  localOnly?: boolean;
}

const getWelcomeMessage = (language: UILanguage) =>
  language === "zh"
    ? "你好，我是 DeepAnalyze-8B。加载示例数据或上传你的文件，然后直接描述想要得到的分析结论。"
    : "Hi, I'm DeepAnalyze-8B. Load the sample data or upload your files, then describe the analysis outcome you need.";

interface FileAttachment {
  id: string;
  name: string;
  size: number;
  type: string;
  url: string;
}

interface WorkspaceFile {
  name: string;
  path: string;
  size: number;
  modified_at_ns?: number;
  extension: string;
  icon: string;
  category?: "table" | "image" | "other";
  is_generated?: boolean;
  download_url: string;
  preview_url?: string;
}

interface LocalizedText {
  zh: string;
  en: string;
}

interface SampleQuestion {
  id: string;
  title: LocalizedText;
  prompt: LocalizedText;
}

interface SampleDataset {
  id: string;
  kind: "single_file" | "multi_file";
  title: LocalizedText;
  description: LocalizedText;
  files: string[];
  questions: SampleQuestion[];
}

interface PreviewTableData {
  kind?: "table" | "database";
  title?: string;
  columns: string[];
  rows: Array<Array<string | number | boolean>>;
  row_count?: number;
  column_count?: number;
  truncated?: boolean;
  page?: number;
  page_size?: number;
  total_pages?: number;
  sheet_name?: string;
  sheet_names?: string[];
  table_name?: string;
  total_rows?: number;
}

interface PreviewPayload {
  kind: "text" | "markdown" | "table" | "database" | "image" | "pdf" | "binary";
  view?: "tables" | "table";
  title?: string;
  content?: string;
  columns?: string[];
  rows?: Array<Array<string | number | boolean>>;
  row_count?: number;
  column_count?: number;
  truncated?: boolean;
  page?: number;
  page_size?: number;
  total_pages?: number;
  sheet_name?: string;
  sheet_names?: string[];
  tables?: PreviewTableData[];
  table_names?: string[];
  table_name?: string;
  total_rows?: number;
}

interface ExportedFileMeta {
  name: string;
  path: string;
  download_url: string;
}

interface ExportResponsePayload {
  message?: string;
  md?: string | null;
  pdf?: string | null;
  pdf_status?: string | null;
  pdf_error?: string | null;
  files?: {
    md?: ExportedFileMeta | null;
    pdf?: ExportedFileMeta | null;
  };
  download_urls?: {
    md?: string | null;
    pdf?: string | null;
  };
}

interface SessionStatePayload {
  messages?: Array<{
    id?: string;
    role: "user" | "assistant";
    content: string;
    timestamp?: string;
    attachments?: FileAttachment[];
  }>;
  task_config?: {
    selected_files?: string[];
    provider?: LlmProvider;
    model?: string;
    temperature?: number;
    system_prompt?: string;
    ui_language?: UILanguage;
    interaction_mode?: InteractionMode;
  };
  interaction_state?: {
    status?: "idle" | "awaiting_user";
    paused_at?: string;
  };
}

type CodeDiffRow = {
  id: string;
  type: "unchanged" | "removed" | "added";
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
};

const PREVIEW_TABLE_PAGE_SIZE = 10;
const BLOCKED_UPLOAD_EXTENSIONS = new Set(["py"]);
const ACTIVE_SECTION_UPDATE_INTERVAL_MS = 80;
const SCROLL_BOTTOM_THRESHOLD_PX = 8;
const STREAMING_SECTION_FIXED_HEIGHT_PX = 140;
const UPLOAD_ACCEPT_TYPES =
  ".csv,.tsv,.xlsx,.xls,.parquet,.sqlite,.db,.json,.txt,.log,.md,.markdown,.yml,.yaml,.pdf,image/*,.zip";
type LlmProvider = "local" | "heywhale" | "custom";
type UILanguage = "en" | "zh";
type InteractionMode = "auto" | "manual";
const DEFAULT_MODEL_NAME = "DeepAnalyze-8B";
const EXECUTE_RESULT_PREFIX = "# Execute Result\n";
const EXECUTE_RESULT_NOTICE_EN =
  "Code execution feedback will be returned as a user message starting with `# Execute Result\\n`.";
const EXECUTE_RESULT_NOTICE_ZH =
  "代码执行结果会以用户消息回传，且内容开头固定为 `# Execute Result\\n`。";
const isDeepAnalyzeModelName = (modelName: string) =>
  /deep[\s\-_]*analyze/i.test(String(modelName || "").trim());
const CUSTOM_MODEL_SYSTEM_PREFIX_EN = `# Role

You are an intelligent agent designed for **data analysis** scenarios. Your goal is to follow user instructions, continuously **analyze**, **write executable code**, and **understand the data based on the output**, ultimately producing high-quality **answers**. Each time you output, you decide the next action on your own.

---

# Input Format: \`# Instruction\` and \`# Data\`

You will receive user instructions structured as follows:

- \`# Instruction\`: The user's task instructions (what you need to do).
- \`# Data\`: A contextual data block containing file names and file sizes.

You must:

- Strictly follow the instructions in \`# Instruction\`;
- Treat \`# Data\` only as available reference material and do not fabricate non-existent data.

---

# Output Format (Must Follow)

You must organize your output using the following XML-style tags (tag names are case-sensitive):

- \`<Analyze>...</Analyze>\`: Your analysis, assumptions, solution selection, risks, and trade-offs.
- \`<Code>...</Code>\`: Code to be executed in Python.
- \`<Understand>...</Understand>\`: Your confirmation and understanding of the data content and context.
- \`<Answer>...</Answer>\`: The final conclusion and deliverables (reports/explanations/table conclusions, etc.) for the user.
- After outputting \`</Code>\`, you should end your output. The code you just wrote will be sent to the Python execution environment, and the execution results will be returned to you.

---

# Interaction Process (How the System Uses Your Output)

The system will interact with you as follows:

1. After receiving \`# Instruction/# Data\`, you will formulate a plan in \`<Analyze>\` and produce the next executable action in \`<Code>\`.
2. The system will execute the code in \`<Code>\` and return the execution output to you as an "execution result" message.
3. After reviewing the execution result, you will decide whether to proceed with data understanding (\`<Understand>\`), analysis (\`<Analyze>\`), or deliver the final answer (\`<Answer>\`).

---

# WrenAI Semantic Layer (Governed Data Access)

This environment is connected to the **WrenAI semantic layer**. Business data must be queried through the pre-defined \`wren_query(sql)\` function (automatically available in every \`<Code>\` block, no import needed). It returns a **pandas DataFrame** and enforces governed, metric-consistent SQL:

\`\`\`python
df = wren_query("SELECT customer_name, SUM(amount) AS revenue FROM customer_orders GROUP BY customer_name ORDER BY revenue DESC LIMIT 10")
print(df.head())
\`\`\`

Available semantic objects (SQL must use these names, not raw table names):

- Models: \`orders\` (id, customer_id, amount), \`customers\` (id, name)
- View: \`customer_orders\` (customer_name, order_id, amount)
- Cube \`order_metrics\`: measures \`total_revenue\` (SUM of amount), \`order_count\` (COUNT *)

Rules:

- Prefer \`wren_query\` for business metrics; read workspace files only for data outside the semantic layer.
- Pass \`limit=\` for exploratory queries to keep result sets small (e.g. \`limit=100\`).
- If a query fails, read the error message, fix the SQL, and retry with corrected semantic names.

---

# Additional Constraints (Must Follow)

- Each \`<Code>\` block runs as an independent Python script and does not inherit variables from previous \`<Code>\` blocks. Therefore, each piece of code in your \`<Code>\` must be a complete, standalone Python script that can run independently.
- When generating files or charts, save them directly in the current directory and do not create subdirectories.
- In the final answer, you need to reference the relevant generated images in Markdown format like ![xxx](xxx.png).`;

const CUSTOM_MODEL_SYSTEM_PREFIX_ZH = `# 角色（Role）

你是一个面向 **数据分析** 场景的智能体。你的目标是遵循用户指令，不断**分析（Analyze）、 编写可执行代码（Code）、根据输出理解数据（Understand），**，并最终产出高质量的** 答案(Answer) **。每次输出时，由你自己决定下一步的动作。

---
# 输入格式：\`# Instruction\` 与 \`# Data\`

你会收到用户指令，内容采用如下结构：

- \`# Instruction\`：用户的任务指令（你需要做什么）。
- \`# Data\`：上下文数据块，包含文件名和文件大小。

你必须：

- 严格按 \`# Instruction\` 执行；
- 仅把 \`# Data\` 作为可获取的参考，不要凭空杜撰不存在的数据；

---
# 输出范式（必须遵守）

你必须用以下 XML 风格标签组织输出（标签名区分大小写）：

- \`<Analyze>...</Analyze>\`：你的分析、假设、方案选择、风险与取舍。
- \`<Code>...</Code>\`：要在Python 中执行的代码。
- \`<Understand>...</Understand>\`：你对数据内容、上下文的确认与理解。
- \`<Answer>...</Answer>\`：最终对用户的结论与交付物（报告/解释/表格结论等）。
- 你在输出\`</Code>\`之后，应结束输出。此时你刚才写的代码会送到python执行环境中执行，并将执行结果返回给你。

---

# 交互流程（系统如何使用你的输出）

系统会按如下方式与你交互：

1. 你收到 \`# Instruction/# Data\` 后，在 \`<Analyze>\` 中制定计划，然后用 \`<Code>\` 产出下一步可执行动作。
2. 系统会执行 \`<Code>\` 中的代码，并把执行输出以“执行结果”消息回传给你。
3. 你阅读执行结果后，决定进行数据理解\`<Understand>\`、分析\`<Analyze>\`还是得出最终的答案\`<Answer>\`。

---

# WrenAI 语义层（治理数据访问）

本环境已接入 **WrenAI 语义层**。业务数据必须通过预定义的 \`wren_query(sql)\` 函数查询（每个 \`<Code>\` 块中自动可用，无需 import）。它返回 **pandas DataFrame**，并强制执行治理过的、口径一致的 SQL：

\`\`\`python
df = wren_query("SELECT customer_name, SUM(amount) AS revenue FROM customer_orders GROUP BY customer_name ORDER BY revenue DESC LIMIT 10")
print(df.head())
\`\`\`

可用语义对象（SQL 必须使用以下名称，而非底层数据库表名）：

- 模型：\`orders\`（id, customer_id, amount）、\`customers\`（id, name）
- 视图：\`customer_orders\`（customer_name, order_id, amount）
- Cube \`order_metrics\`：指标 \`total_revenue\`（amount 求和）、\`order_count\`（计数）

规则：

- 涉及业务指标时优先使用 \`wren_query\`；仅当数据不在语义层内时才读取工作区文件。
- 探索性查询请传 \`limit=\`（如 \`limit=100\`）控制返回行数。
- 查询失败时阅读报错信息，修正 SQL 后重试。

---

# 额外约束（必须遵守）

- 每个 \`<Code>\` 块都会作为独立的 Python 脚本运行，不会继承之前 \`<Code>\` 块中的变量。因此你的每次\`<Code>\`里的代码都需要是独立可运行的完整python代码。
- 生成文件或图表时，请直接保存在当前目录，不要创建子目录。`;
type WorkspaceNode = {
  name: string;
  path: string; // relative path
  is_dir: boolean;
  size?: number;
  extension?: string;
  icon?: string;
  download_url?: string;
  preview_url?: string;
  children?: WorkspaceNode[];
  is_generated?: boolean; // 标识是否为代码生成的文件或文件夹
};

interface AnalysisSection {
  type: "Analyze" | "Understand" | "Code" | "Execute" | "Answer";
  content: string;
  icon: string;
  color: string;
}

type CodeBlockViewProps = {
  language: string;
  code: string;
  showHeader?: boolean;
  isDarkMode: boolean;
  onEdit: (code: string) => void;
};

const CodeBlockView = memo(function CodeBlockView({
  language,
  code,
  showHeader = false,
  isDarkMode,
  onEdit,
}: CodeBlockViewProps) {
  const { toast } = useToast();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code.trim());
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 1500);
      toast({ description: "已复制代码" });
    } catch {
      toast({ description: "复制失败", variant: "destructive" });
    }
  };

  const isLargeCode = code.length > 8000;

  return (
    <div className="code-block my-3 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      {showHeader && (
        <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-800 px-3 py-2 text-xs">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="h-5 w-5 p-0 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              {isCollapsed ? (
                <ChevronRight className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </Button>
            <span className="text-gray-600 dark:text-gray-300">Code</span>
            <span className="text-gray-500 font-mono">{language || "text"}</span>
            {isLargeCode && (
              <span className="text-[10px] text-gray-400">
                （代码较长，已关闭高亮）
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              {isCopied ? (
                <Check className="h-3 w-3" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(code.trim())}
              className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              <Edit className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}
      {!showHeader || !isCollapsed ? (
        isLargeCode ? (
          <pre className="m-0 p-3 text-xs overflow-x-auto whitespace-pre-wrap font-mono bg-transparent">
            {code.trim()}
          </pre>
        ) : (
          <SyntaxHighlighter
            language={language || "text"}
            style={isDarkMode ? oneDark : oneLight}
            customStyle={{
              margin: 0,
              background: "transparent",
              overflowX: "hidden",
              whiteSpace: "pre-wrap",
            }}
            codeTagProps={{
              style: {
                fontFamily: "var(--font-mono)",
                fontSize: "0.875rem",
                whiteSpace: "pre-wrap",
              },
            }}
          >
            {code.trim()}
          </SyntaxHighlighter>
        )
      ) : null}
    </div>
  );
});

type ChatMessageItemProps = {
  message: Message;
  messageIndex: number;
  isStreaming: boolean;
  renderAssistant: (content: string, messageIndex?: number) => React.ReactNode;
  renderAssistantStreaming: (content: string, messageIndex?: number) => React.ReactNode;
};

const ChatMessageItem = memo(
  function ChatMessageItem({
    message,
    messageIndex,
    isStreaming,
    renderAssistant,
    renderAssistantStreaming,
  }: ChatMessageItemProps) {
    return (
      <div
        className="space-y-2"
        style={{
          contentVisibility: "auto",
          containIntrinsicSize: message.sender === "ai" ? "520px" : "96px",
        }}
      >
        {message.sender === "user" ? (
          <div className="flex items-start justify-end gap-2">
            <div className="max-w-[80%] bg-black text-white dark:bg-white dark:text-black rounded-lg px-4 py-3 message-bubble message-appear">
              <div className="text-sm break-words whitespace-pre-wrap">
                {message.content}
              </div>
            </div>
            <Avatar>
              <AvatarFallback className="text-[10px]">U</AvatarFallback>
            </Avatar>
          </div>
        ) : (
          <div className="flex items-start gap-2 min-w-0">
            <Avatar>
              <AvatarFallback className="text-[10px]">
                <Sparkles className="h-3 w-3" />
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1 message-appear">
              <div className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">
                DA-Studio
              </div>
              <div className="space-y-4 min-w-0">
                {isStreaming ? (
                  renderAssistantStreaming(message.content, messageIndex)
                ) : (
                  renderAssistant(message.content, messageIndex)
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.message === next.message &&
      prev.messageIndex === next.messageIndex &&
      prev.isStreaming === next.isStreaming &&
      prev.renderAssistant === next.renderAssistant &&
      prev.renderAssistantStreaming === next.renderAssistantStreaming
    );
  }
);

type StructuredSectionType =
  | "Analyze"
  | "Understand"
  | "Code"
  | "Execute"
  | "Answer"
  | "File";

const normalizeCodeBlockForSection = (
  content: string
): { language: string; code: string } => {
  const codeBlockMatch = content.match(/```([\w+-]+)?\n?([\s\S]*?)```/);
  if (codeBlockMatch) {
    return {
      language: codeBlockMatch[1]?.trim() || "python",
      code: codeBlockMatch[2].trim(),
    };
  }
  return {
    language: "python",
    code: content.trim(),
  };
};

const buildCodeFenceForSection = (content: string): string => {
  const normalized = normalizeCodeBlockForSection(content);
  return `\`\`\`${normalized.language}\n${normalized.code}\n\`\`\``;
};

const StreamingMarkdownBlock = memo(
  function StreamingMarkdownBlock({
    content,
    renderMarkdownContent,
    className,
  }: {
    content: string;
    renderMarkdownContent: (content: string) => React.ReactNode;
    className?: string;
  }) {
    if (!content.trim()) return null;
    return <div className={className}>{renderMarkdownContent(content)}</div>;
  },
  (prev, next) =>
    prev.content === next.content &&
    prev.renderMarkdownContent === next.renderMarkdownContent &&
    prev.className === next.className
);

const StreamingSectionBody = memo(
  function StreamingSectionBody({
    type,
    content,
    isComplete,
    renderSectionContent,
  }: {
    type: StructuredSectionType;
    content: string;
    isComplete: boolean;
    renderSectionContent: (content: string) => React.ReactNode;
  }) {
    if (!content.trim()) return null;
    if (type === "Code" && isComplete) {
      return (
        <div className="markdown-content">
          {renderSectionContent(buildCodeFenceForSection(content))}
        </div>
      );
    }
    if (!isComplete) {
      if (type === "Code" || type === "Execute") {
        return (
          <pre className="m-0 text-xs overflow-x-auto whitespace-pre-wrap font-mono">
            {content}
          </pre>
        );
      }
      return (
        <div className="text-sm break-words whitespace-pre-wrap">{content}</div>
      );
    }
    return <div className="markdown-content">{renderSectionContent(content)}</div>;
  },
  (prev, next) =>
    prev.type === next.type &&
    prev.content === next.content &&
    prev.isComplete === next.isComplete &&
    prev.renderSectionContent === next.renderSectionContent
);

const StreamingSectionViewport = memo(function StreamingSectionViewport({
  enabled,
  bodyClassName,
  children,
}: {
  enabled: boolean;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const syncOverflowState = useCallback(() => {
    const el = containerRef.current;
    if (!el || !enabled) {
      setIsOverflowing(false);
      setIsAtBottom(true);
      return;
    }
    const overflowing = el.scrollHeight - el.clientHeight > 1;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
    setIsOverflowing(overflowing);
    setIsAtBottom(atBottom || !overflowing);
  }, [enabled]);

  useEffect(() => {
    let rafId: number | null = null;
    const scheduleSync = () => {
      if (typeof window === "undefined") return;
      if (rafId !== null) {
        window.cancelAnimationFrame(rafId);
      }
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        syncOverflowState();
      });
    };

    scheduleSync();
    const el = containerRef.current;
    if (!enabled || !el) {
      return () => {
        if (rafId !== null && typeof window !== "undefined") {
          window.cancelAnimationFrame(rafId);
        }
      };
    }

    let resizeObserver: ResizeObserver | null = null;
    let mutationObserver: MutationObserver | null = null;

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        scheduleSync();
      });
      resizeObserver.observe(el);
      if (el.firstElementChild) {
        resizeObserver.observe(el.firstElementChild);
      }
    }

    if (typeof MutationObserver !== "undefined") {
      mutationObserver = new MutationObserver(() => {
        scheduleSync();
      });
      mutationObserver.observe(el, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }

    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      if (rafId !== null && typeof window !== "undefined") {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [enabled, children, syncOverflowState]);

  return (
    <div className="relative">
      <div
        ref={containerRef}
        onScroll={enabled ? syncOverflowState : undefined}
        className={`p-3 ${bodyClassName || ""} ${
          enabled ? "overflow-y-auto overflow-x-hidden" : ""
        }`}
        style={
          enabled
            ? { height: `${STREAMING_SECTION_FIXED_HEIGHT_PX}px` }
            : undefined
        }
      >
        {children}
      </div>
      {enabled && isOverflowing && !isAtBottom && (
        <div className="pointer-events-none absolute bottom-1 right-2">
          <div className="flex h-5 w-5 items-center justify-center rounded-full border border-gray-300/70 bg-white/85 text-gray-500 shadow-sm dark:border-gray-600/70 dark:bg-black/65 dark:text-gray-300 animate-pulse">
            <ChevronDown className="h-3 w-3" />
          </div>
        </div>
      )}
    </div>
  );
});

const COMPOSER_MIN_HEIGHT_PX = 40;
const COMPOSER_MAX_HEIGHT_PX = 160;

function AutoGrowingTextarea({
  onChange,
  value,
  ...props
}: Omit<React.ComponentProps<typeof Textarea>, "ref">) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resizeTextarea = useCallback((textarea: HTMLTextAreaElement) => {
    if (!textarea.value) {
      textarea.style.height = `${COMPOSER_MIN_HEIGHT_PX}px`;
      textarea.style.overflowY = "hidden";
      return;
    }

    textarea.style.height = "0px";
    const nextHeight = Math.min(
      Math.max(textarea.scrollHeight, COMPOSER_MIN_HEIGHT_PX),
      COMPOSER_MAX_HEIGHT_PX
    );
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY =
      textarea.scrollHeight > COMPOSER_MAX_HEIGHT_PX ? "auto" : "hidden";
  }, []);

  useEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [resizeTextarea, value]);

  return (
    <Textarea
      {...props}
      ref={textareaRef}
      rows={1}
      value={value}
      onChange={(event) => {
        resizeTextarea(event.currentTarget);
        onChange?.(event);
      }}
    />
  );
}

export function ThreePanelInterface() {
  const { toast } = useToast();
  const [isDarkMode, setIsDarkMode] = useState(false); // 服务端默认 false
  const [mounted, setMounted] = useState(false);
  const [editorHeight, setEditorHeight] = useState(60); // 编辑器高度百分比
  const [collapsedSections, setCollapsedSections] = useState<
    Record<string, boolean>
  >({});
  const [autoCollapseEnabled, setAutoCollapseEnabled] = useState(true);
  const [fixedStreamingSectionHeightEnabled, setFixedStreamingSectionHeightEnabled] =
    useState(false);
  const [moveDialogToLeftPanel, setMoveDialogToLeftPanel] = useState(false);
  const [manualLocks, setManualLocks] = useState<Record<string, boolean>>({});

  // Session ID：会话按登录用户隔离（u{username}__ 前缀）
  const [sessionId, setSessionId] = useState<string>("");
  // 当前登录用户与其会话列表
  const [currentUsername, setCurrentUsername] = useState<string>("");
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const [sessionList, setSessionList] = useState<Array<{
      session_id: string;
      instruction: string;
      message_count: number;
      updated_at: string;
    }>
  >([]);

  // 步骤导航相关状态
  const [activeSection, setActiveSection] = useState<string>("");
  const stepNavigatorRef = useRef<HTMLDivElement>(null);
  const activeStepRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // 组件挂载后从 localStorage 读取主题
  useEffect(() => {
    setMounted(true);
    if (typeof window !== "undefined") {
      // 配置 Monaco Editor
      configureMonaco();

      // 初始化或获取 sessionId（按用户隔离：带 u{username}__ 前缀）
      const username = getUsername();
      setCurrentUsername(username);
      const sidKey = `sessionId:${username}`;
      const sidPrefix = `u${username}__`;
      let sid = localStorage.getItem(sidKey);
      if (!sid || !sid.startsWith(sidPrefix)) {
        sid = `${sidPrefix}session_${Date.now()}_${Math.random()
          .toString(36)
          .substr(2, 9)}`;
        localStorage.setItem(sidKey, sid);
      }
      setSessionId(sid);

      const savedTheme = localStorage.getItem("theme");
      const shouldBeDark = savedTheme === "dark";
      setIsDarkMode(shouldBeDark);
      updateThemeClass(shouldBeDark);
      const savedAuto = localStorage.getItem("autoCollapseEnabled");
      if (savedAuto !== null) {
        setAutoCollapseEnabled(savedAuto !== "false");
      }
      const savedFixedStreamingHeight = localStorage.getItem(
        "fixedStreamingSectionHeightEnabled"
      );
      if (savedFixedStreamingHeight !== null) {
        setFixedStreamingSectionHeightEnabled(
          savedFixedStreamingHeight === "true"
        );
      }
      const savedMoveDialog = localStorage.getItem("moveDialogToLeftPanel");
      if (savedMoveDialog !== null) {
        setMoveDialogToLeftPanel(savedMoveDialog === "true");
      }

      const savedLanguage = localStorage.getItem("deepanalyze.uiLanguage");
      if (savedLanguage === "en" || savedLanguage === "zh") {
        setUiLanguage(savedLanguage);
      }

      setInteractionMode(
        normalizeInteractionMode(
          localStorage.getItem("deepanalyze.interactionMode")
        )
      );

      const savedRequirements =
        localStorage.getItem("deepanalyze.systemPrompt");
      if (savedRequirements) {
        setSystemPrompt(savedRequirements);
      }

      const savedProvider = localStorage.getItem("deepanalyze.llmProvider");
      if (
        savedProvider === "local" ||
        savedProvider === "heywhale" ||
        savedProvider === "custom"
      ) {
        setLlmProvider(savedProvider as LlmProvider);
      }

      const savedCustomModelName =
        localStorage.getItem("deepanalyze.customModelName") ||
        localStorage.getItem("deepanalyze.modelName");
      if (savedCustomModelName) {
        setCustomModelName(savedCustomModelName);
      }

      const savedTemperature = localStorage.getItem("deepanalyze.modelTemperature");
      if (savedTemperature) {
        setModelTemperature(savedTemperature);
      }

      const savedApiKey = sessionStorage.getItem("deepanalyze.heywhaleApiKey");
      if (savedApiKey) {
        setHeywhaleApiKey(savedApiKey);
      }

      const savedCustomApiBase = localStorage.getItem("deepanalyze.customApiBase");
      if (savedCustomApiBase) {
        setCustomApiBase(savedCustomApiBase);
      }

      const savedCustomApiKey = sessionStorage.getItem("deepanalyze.customApiKey");
      if (savedCustomApiKey) {
        setCustomApiKey(savedCustomApiKey);
      }

      // 用户级模型配置（服务端）优先于本地缓存
      void (async () => {
        try {
          const res = await fetch(API_URLS.USER_MODEL_CONFIG);
          if (!res.ok) return;
          const data = await res.json();
          const cfg = data.config || {};
          if (
            cfg.provider === "local" ||
            cfg.provider === "heywhale" ||
            cfg.provider === "custom"
          ) {
            setLlmProvider(cfg.provider as LlmProvider);
          }
          if (cfg.model) setCustomModelName(cfg.model);
          if (cfg.api_base) setCustomApiBase(cfg.api_base);
          if (cfg.api_key) setCustomApiKey(cfg.api_key);
          if (cfg.heywhale_api_key) setHeywhaleApiKey(cfg.heywhale_api_key);
          if (
            cfg.temperature !== undefined &&
            cfg.temperature !== null &&
            !Number.isNaN(Number(cfg.temperature))
          ) {
            setModelTemperature(String(cfg.temperature));
          }
        } catch (error) {
          console.warn("load user model config failed", error);
        }
      })();

    }
  }, []);

  // 按 session 维度持久化/恢复 折叠状态 与 手动锁
  useEffect(() => {
    if (!sessionId) return;
    try {
      const cs = localStorage.getItem(`collapsedSections:${sessionId}`);
      if (cs) setCollapsedSections(JSON.parse(cs));
      const ml = localStorage.getItem(`manualLocks:${sessionId}`);
      if (ml) setManualLocks(JSON.parse(ml));
    } catch { }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    try {
      localStorage.setItem(
        `collapsedSections:${sessionId}`,
        JSON.stringify(collapsedSections)
      );
      localStorage.setItem(
        `manualLocks:${sessionId}`,
        JSON.stringify(manualLocks)
      );
    } catch { }
  }, [sessionId, collapsedSections, manualLocks]);

  // 当 activeSection 变化时自动滚动到对应步骤
  useEffect(() => {
    if (activeSection && stepNavigatorRef.current) {
      const activeStepElement = activeStepRefs.current.get(activeSection);
      if (activeStepElement) {
        const container = stepNavigatorRef.current;
        const stepRect = activeStepElement.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();

        // 计算需要滚动的距离
        const scrollLeft =
          activeStepElement.offsetLeft -
          containerRect.width / 2 +
          stepRect.width / 2;

        // 平滑滚动到目标位置
        container.scrollTo({
          left: scrollLeft,
          behavior: "smooth",
        });
      }
    }
  }, [activeSection]);

  // 更新主题 class
  const updateThemeClass = (isDark: boolean) => {
    if (typeof document !== "undefined") {
      if (isDark) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  };

  // 获取某条消息之前最近的用户问题内容
  const getPrevUserQuestionText = (index: number): string => {
    for (let i = index - 1; i >= 0; i--) {
      const m = messages[i];
      if (m && m.sender === "user") return m.content || "";
    }
    return "";
  };

  const buildReportFilename = (question: string) => {
    const clean = (question || "").replace(/\s+/g, " ").trim();
    let tokens = clean.split(/\s+/).filter(Boolean);
    let base = "";
    if (tokens.length <= 1) {
      // 中文/无空格：直接取前 5 个字符，不再用下划线
      base = clean.replace(/\s+/g, "").slice(0, 5);
    } else {
      // 英文/有空格：取前 5 个词，用下划线连接
      base = tokens
        .slice(0, 5)
        .map((t) => t.replace(/[\\/:*?"<>|]/g, ""))
        .filter(Boolean)
        .join("_");
    }
    base = base.slice(0, 120);
    return `Report_${base || "Untitled"}.pdf`;
  };

  const exportReportBackend = async () => {
    try {
      const payloadMessages = messages
        .filter((m) => !m.localOnly)
        .map((msg) => ({
          role: msg.sender === "user" ? "user" : "assistant",
          content: msg.content,
        }));
      const title = getPrevUserQuestionText(messages.length);
      const res = await fetch(API_URLS.EXPORT_REPORT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: payloadMessages,
          title,
          session_id: sessionId,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const md = data?.md;
      toast({ description: `已提交并生成: ${md}` });
      await loadWorkspaceFiles();
      await loadWorkspaceTree?.();
    } catch (e) {
      console.error("backend export error", e);
      toast({ description: "导出失败", variant: "destructive" });
    }
  };
  const exportReportBackendRef = useRef(exportReportBackend);
  useEffect(() => {
    exportReportBackendRef.current = exportReportBackend;
  }, [exportReportBackend]);

  // 切换主题
  const toggleTheme = () => {
    const newDarkMode = !isDarkMode;
    setIsDarkMode(newDarkMode);
    updateThemeClass(newDarkMode);

    // 保存到 localStorage
    if (typeof window !== "undefined") {
      localStorage.setItem("theme", newDarkMode ? "dark" : "light");
    }
  };

  // 处理拖动调整大小
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = editorHeight;

    const handleMouseMove = (e: MouseEvent) => {
      const container = document.querySelector(".editor-container");
      if (!container) return;

      const containerRect = container.getBoundingClientRect();
      const deltaY = e.clientY - startY;
      const containerHeight = containerRect.height;
      const deltaPercent = (deltaY / containerHeight) * 100;

      const newHeight = Math.min(Math.max(startHeight + deltaPercent, 20), 80);
      setEditorHeight(newHeight);
    };

    const handleMouseUp = () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  };

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-1",
      content: getWelcomeMessage("en"),
      sender: "ai",
      timestamp: new Date(),
      localOnly: true,
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFile[]>([]);
  const workspaceFilesRef = useRef<WorkspaceFile[]>([]);
  useEffect(() => {
    workspaceFilesRef.current = workspaceFiles;
  }, [workspaceFiles]);
  const [workspaceTree, setWorkspaceTree] = useState<WorkspaceNode | null>(
    null
  );
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const treeContainerRef = useRef<HTMLDivElement>(null);
  const [selectedCodeSection, setSelectedCodeSection] = useState<string>("");
  const [codeEditorContent, setCodeEditorContent] = useState("");
  const [showCodeEditor, setShowCodeEditor] = useState(false);
  const [isExecutingCode, setIsExecutingCode] = useState(false);
  const [codeExecutionResult, setCodeExecutionResult] = useState("");
  const [codeEditInstruction, setCodeEditInstruction] = useState("");
  const [codeEditorOriginalCode, setCodeEditorOriginalCode] = useState("");
  const [appliedCodeEdit, setAppliedCodeEdit] = useState<{
    originalCode: string;
    instruction: string;
  } | null>(null);
  const [isEditingCodeWithAi, setIsEditingCodeWithAi] = useState(false);
  const [pendingCodeEdit, setPendingCodeEdit] = useState<{
    originalCode: string;
    modifiedCode: string;
    instruction: string;
    diffRows: CodeDiffRow[];
  } | null>(null);
  const [workspaceView, setWorkspaceView] = useState<
    "all" | "uploaded" | "generated"
  >("generated");
  const [workspaceSearch, setWorkspaceSearch] = useState("");
  const [selectedWorkspacePath, setSelectedWorkspacePath] = useState("");
  const [selectedAnalysisFiles, setSelectedAnalysisFiles] = useState<Set<string>>(
    () => new Set()
  );
  const fileSelectionInitializedRef = useRef(false);
  const [uiLanguage, setUiLanguage] = useState<UILanguage>("en");
  const [interactionMode, setInteractionMode] =
    useState<InteractionMode>("auto");
  const [manualPaused, setManualPaused] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("local");
  const [customModelName, setCustomModelName] = useState(DEFAULT_MODEL_NAME);
  const [modelTemperature, setModelTemperature] = useState("0.4");
  const [heywhaleApiKey, setHeywhaleApiKey] = useState("");
  const [customApiBase, setCustomApiBase] = useState("");
  const [customApiKey, setCustomApiKey] = useState("");
  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.uiLanguage", uiLanguage);
  }, [uiLanguage]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.interactionMode", interactionMode);
  }, [interactionMode]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(
      "deepanalyze.systemPrompt",
      systemPrompt
    );
  }, [systemPrompt]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.llmProvider", llmProvider);
  }, [llmProvider]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.customModelName", customModelName);
  }, [customModelName]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.modelTemperature", modelTemperature);
  }, [modelTemperature]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    sessionStorage.setItem("deepanalyze.heywhaleApiKey", heywhaleApiKey);
  }, [heywhaleApiKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("deepanalyze.customApiBase", customApiBase);
  }, [customApiBase]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    sessionStorage.setItem("deepanalyze.customApiKey", customApiKey);
  }, [customApiKey]);

  // 预览弹窗状态
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState<string>("");
  const [previewContent, setPreviewContent] = useState<string>("");
  const [previewType, setPreviewType] = useState<
    "text" | "markdown" | "table" | "database" | "image" | "pdf" | "binary"
  >("text");
  const [previewPayload, setPreviewPayload] = useState<PreviewPayload | null>(
    null
  );
  const [previewPage, setPreviewPage] = useState(1);
  const [previewTableName, setPreviewTableName] = useState("");
  const [previewSheetName, setPreviewSheetName] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewDownloadUrl, setPreviewDownloadUrl] = useState<string>("");
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const previewRequestIdRef = useRef(0);
  const [deleteConfirmPath, setDeleteConfirmPath] = useState<string | null>(
    null
  );
  const [deleteIsDir, setDeleteIsDir] = useState<boolean>(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const singleClickTimerRef = useRef<number | null>(null);
  const [contextPos, setContextPos] = useState<{ x: number; y: number } | null>(
    null
  );
  const [contextTarget, setContextTarget] = useState<WorkspaceNode | null>(
    null
  );
  const [dragOverPath, setDragOverPath] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingSample, setIsLoadingSample] = useState(false);
  const [isSampleDialogOpen, setIsSampleDialogOpen] = useState(false);
  const [isSampleCatalogLoading, setIsSampleCatalogLoading] = useState(false);
  const [sampleCatalog, setSampleCatalog] = useState<SampleDataset[]>([]);
  const [selectedSampleId, setSelectedSampleId] = useState("");
  const [selectedSampleQuestionId, setSelectedSampleQuestionId] = useState("");
  const [uploadMsg, setUploadMsg] = useState<string>("");
  const [exportingFormat, setExportingFormat] = useState<"md" | "pdf" | null>(
    null
  );
  const selectedSample = useMemo(
    () => sampleCatalog.find((dataset) => dataset.id === selectedSampleId) || null,
    [sampleCatalog, selectedSampleId]
  );
  const selectedSampleQuestion = useMemo(
    () =>
      selectedSample?.questions.find(
        (question) => question.id === selectedSampleQuestionId
      ) || null,
    [selectedSample, selectedSampleQuestionId]
  );

  const scrollRafRef = useRef<number | null>(null);
  const stickToBottomRef = useRef(true);
  // const aiUpdateTimerRef = useRef<number | null>(null); // Removed in favor of RAF
  const streamAbortControllerRef = useRef<AbortController | null>(null);
  const workspaceFilesAbortRef = useRef<AbortController | null>(null);
  const workspaceFilesLoadingRef = useRef(false);
  const workspaceFilesPendingRefreshRef = useRef(false);
  const lastWorkspaceFilesErrorRef = useRef("");
  const isTypingRef = useRef(false);
  const toastRef = useRef(toast);
  const collapsedSectionsRef = useRef<Record<string, boolean>>({});
  const lastActiveSectionUpdateAtRef = useRef(0);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(
    null
  );
  const updateTypingState = useCallback((value: boolean) => {
    isTypingRef.current = value;
    setIsTyping(value);
  }, []);
  // const [clearChatOpen, setClearChatOpen] = useState(false); // Removed redundant state

  // 节流滚动到底部

  useEffect(() => {
    isTypingRef.current = isTyping;
  }, [isTyping]);

  useEffect(() => {
    toastRef.current = toast;
  }, [toast]);

  useEffect(() => {
    collapsedSectionsRef.current = collapsedSections;
  }, [collapsedSections]);

  const scrollToBottom = useCallback(() => {
    if (!stickToBottomRef.current) return;

    if (scrollRafRef.current) {
      cancelAnimationFrame(scrollRafRef.current);
    }

    scrollRafRef.current = requestAnimationFrame(() => {
      if (!stickToBottomRef.current) {
        scrollRafRef.current = null;
        return;
      }
      if (messagesContainerRef.current) {
        const container = messagesContainerRef.current;
        // 使用 behavior: auto (默认) 以确保瞬间跳转，避免 smooth 带来的滞后叠加
        container.scrollTop = container.scrollHeight;
      }
      scrollRafRef.current = null;
    });
  }, []);

  useEffect(() => {
    return () => {
      if (scrollRafRef.current) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, []);

  // 输入完成后平滑滚动到底部（避免流式期间 setInterval 导致频繁布局计算）
  useEffect(() => {
    if (isTyping) return;
    if (!stickToBottomRef.current) return;
    const timeoutId = window.setTimeout(() => {
      const container = messagesContainerRef.current;
      if (!container || !stickToBottomRef.current) return;
      container.scrollTo({
        top: container.scrollHeight,
        behavior: "auto",
      });
    }, 100);
    return () => window.clearTimeout(timeoutId);
  }, [isTyping]);

  // 监听消息变化
  useEffect(() => {
    if (stickToBottomRef.current) {
      // 只有仍在底部时才跟随消息增量滚动。
      scrollToBottom();
    }
  }, [messages, scrollToBottom]);

  // 服务端 session state 是主存储，本地缓存仅用于离线回退。
  const [chatLoaded, setChatLoaded] = useState(false);

  useEffect(() => {
    if (!sessionId || typeof window === "undefined") return;
    let cancelled = false;
    setChatLoaded(false);
    setManualPaused(false);

    const restoreSession = async () => {
      let restoredMessages: Message[] = [];
      try {
        const response = await fetch(
          `${API_URLS.SESSION_STATE}?session_id=${encodeURIComponent(sessionId)}`
        );
        if (response.status === 401) {
          window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
          return;
        }
        if (response.ok) {
          const state = (await response.json()) as SessionStatePayload;
          restoredMessages = normalizeSessionMessages(state.messages || []) as Message[];
          const task = state.task_config || {};
          const selectedFiles = Array.isArray(task.selected_files)
            ? task.selected_files
            : [];
          setSelectedAnalysisFiles(new Set(selectedFiles));
          fileSelectionInitializedRef.current = selectedFiles.length > 0;
          if (task.provider) setLlmProvider(task.provider);
          if (task.model) setCustomModelName(task.model);
          if (typeof task.temperature === "number") {
            setModelTemperature(String(task.temperature));
          }
          if (task.system_prompt) setSystemPrompt(task.system_prompt);
          if (task.ui_language === "zh" || task.ui_language === "en") {
            setUiLanguage(task.ui_language);
          }
          if (task.interaction_mode) {
            setInteractionMode(normalizeInteractionMode(task.interaction_mode));
          }
          setManualPaused(
            isAwaitingManualContinuation(state.interaction_state)
          );
        }
      } catch (error) {
        console.warn("load server session state failed", error);
      }

      if (!restoredMessages.length) {
        try {
          const raw = localStorage.getItem(
            buildSessionStorageKey(sessionId)
          );
          const cached = raw ? (JSON.parse(raw) as any[]) : [];
          if (Array.isArray(cached)) {
            restoredMessages = normalizeSessionMessages(cached) as Message[];
          }
        } catch (error) {
          console.warn("load local session cache failed", error);
        }
      }

      if (!cancelled) {
        if (restoredMessages.length) {
          setMessages(restoredMessages);
        } else {
          // 空会话（新建/切换后）显示欢迎消息
          setMessages([
            {
              id: `welcome-${Date.now()}`,
              content: getWelcomeMessage(uiLanguage),
              sender: "ai",
              timestamp: new Date(),
              localOnly: true,
            },
          ]);
        }
        setChatLoaded(true);
      }
    };

    void restoreSession();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const saveChatTimerRef = useRef<number | null>(null);
  useEffect(() => {
    try {
      if (!chatLoaded || !sessionId) return;
      if (typeof window === "undefined") return;

      if (saveChatTimerRef.current) {
        window.clearTimeout(saveChatTimerRef.current);
        saveChatTimerRef.current = null;
      }

      const delay = isTyping ? 1500 : 200;
      saveChatTimerRef.current = window.setTimeout(() => {
        try {
          const data = JSON.stringify(serializeSessionMessages(messages));
          localStorage.setItem(buildSessionStorageKey(sessionId), data);
          const persistedMessages = toServerMessages(messages);
          void fetch(API_URLS.SESSION_MESSAGES, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: sessionId,
              messages: persistedMessages,
            }),
          }).catch((error) => console.warn("save server session failed", error));
        } catch (e) {
          console.warn("save chat cache failed", e);
        } finally {
          saveChatTimerRef.current = null;
        }
      }, delay);
    } catch (e) {
      console.warn("save chat cache failed", e);
    }
  }, [messages, chatLoaded, isTyping, sessionId]);

  const discardPendingContinuation = useCallback(() => {
    setManualPaused(false);
    if (!sessionId) return;
    void fetch(
      buildApiUrlWithParams(API_CONFIG.ENDPOINTS.SESSION_PENDING, {
        session_id: sessionId,
      }),
      { method: "DELETE" }
    ).catch((error) => console.warn("clear pending continuation failed", error));
  }, [sessionId]);

  // 一键清空聊天：保留欢迎消息（仅本地显示）
  const clearChat = () => {
    if (isTyping) {
      toast({ description: "执行中，暂时无法清空", variant: "destructive" });
      return;
    }
    const welcome: Message = {
      id: `welcome-${Date.now()}`,
      content: getWelcomeMessage(uiLanguage),
      sender: "ai",
      timestamp: new Date(),
      localOnly: true,
    };
    setMessages([welcome]);
    discardPendingContinuation();
    try {
      if (typeof window !== "undefined") {
        localStorage.setItem(
          buildSessionStorageKey(sessionId),
          JSON.stringify([welcome])
        );
      }
    } catch { }
    toast({ description: "已清空聊天" });
  };

  useEffect(() => {
    setMessages((current) =>
      current.map((message) =>
        message.localOnly && message.id.startsWith("welcome-")
          ? { ...message, content: getWelcomeMessage(uiLanguage) }
          : message
      )
    );
  }, [uiLanguage]);

  // ===== 会话管理（按登录用户隔离） =====

  const loadSessionList = useCallback(async () => {
    try {
      const res = await fetch(API_URLS.SESSIONS_LIST);
      if (res.ok) {
        const data = await res.json();
        setSessionList(data.sessions || []);
      }
    } catch (error) {
      console.warn("load session list failed", error);
    }
  }, []);

  const switchSession = (targetSessionId: string) => {
    if (isTyping) {
      toast({ description: "执行中，暂时无法切换会话", variant: "destructive" });
      return;
    }
    if (!targetSessionId || targetSessionId === sessionId) return;
    const username = getUsername();
    try {
      localStorage.setItem(`sessionId:${username}`, targetSessionId);
    } catch {}
    setSessionId(targetSessionId);
    setSessionListOpen(false);
  };

  const createNewSession = () => {
    if (isTyping) {
      toast({ description: "执行中，暂时无法新建会话", variant: "destructive" });
      return;
    }
    const username = getUsername();
    const sid = `u${username}__session_${Date.now()}_${Math.random()
      .toString(36)
      .substr(2, 9)}`;
    try {
      localStorage.setItem(`sessionId:${username}`, sid);
    } catch {}
    setSessionId(sid);
    setSessionListOpen(false);
    toast({ description: "已新建会话" });
  };

  const handleLogout = async () => {
    try {
      await fetch(API_URLS.AUTH_LOGOUT, { method: "POST" });
    } catch {}
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  };

  const formatSessionTime = (iso: string) => {
    if (!iso) return "";
    try {
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return "";
      const now = new Date();
      const sameYear = date.getFullYear() === now.getFullYear();
      const pad = (value: number) => String(value).padStart(2, "0");
      const monthDay = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
      const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
      return sameYear ? `${monthDay} ${time}` : `${date.getFullYear()}-${monthDay}`;
    } catch {
      return "";
    }
  };

  // ===== 用户级模型配置：保存与检测 =====

  const [modelConfigSaving, setModelConfigSaving] = useState(false);
  const [modelConfigTesting, setModelConfigTesting] = useState(false);
  const [modelTestResult, setModelTestResult] = useState<{
    success: boolean;
    detail: string;
    latency_ms?: number;
    model?: string;
  } | null>(null);

  const buildCurrentModelConfig = () => ({
    provider: llmProvider,
    model: llmProvider === "custom" ? customModelName.trim() : DEFAULT_MODEL_NAME,
    api_base: customApiBase.trim(),
    api_key: customApiKey,
    heywhale_api_key: heywhaleApiKey,
    temperature: normalizedTemperature,
  });

  const saveModelConfig = async () => {
    setModelConfigSaving(true);
    setModelTestResult(null);
    try {
      const res = await fetch(API_URLS.USER_MODEL_CONFIG, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: buildCurrentModelConfig() }),
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        toast({
          description: `保存失败: ${data.detail || res.status}`,
          variant: "destructive",
        });
        return;
      }
      toast({ description: uiLanguage === "zh" ? "模型配置已保存到当前用户" : "Model config saved for current user" });
    } catch (error) {
      console.error("save model config failed", error);
      toast({ description: "保存失败：无法连接服务器", variant: "destructive" });
    } finally {
      setModelConfigSaving(false);
    }
  };

  const testModelConfig = async () => {
    setModelConfigTesting(true);
    setModelTestResult(null);
    try {
      const res = await fetch(API_URLS.USER_MODEL_CONFIG_TEST, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: buildCurrentModelConfig() }),
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setModelTestResult({
          success: false,
          detail: data.detail || `HTTP ${res.status}`,
        });
        return;
      }
      const data = await res.json();
      setModelTestResult({
        success: !!data.success,
        detail: String(data.detail || ""),
        latency_ms: data.latency_ms,
        model: data.model,
      });
    } catch (error) {
      console.error("test model config failed", error);
      setModelTestResult({
        success: false,
        detail: "无法连接服务器",
      });
    } finally {
      setModelConfigTesting(false);
    }
  };

  const loadWorkspaceFiles = useCallback(async () => {
    if (!sessionId) return;
    if (workspaceFilesLoadingRef.current) {
      workspaceFilesPendingRefreshRef.current = true;
      return;
    }
    const controller = new AbortController();
    workspaceFilesAbortRef.current = controller;
    workspaceFilesLoadingRef.current = true;
    try {
      const response = await fetch(
        `${API_URLS.WORKSPACE_FILES}?session_id=${sessionId}`,
        {
          signal: controller.signal,
          cache: "no-store",
        }
      );
      if (response.ok) {
        const data = await response.json();
        setWorkspaceFiles((prev) => {
          const nextFiles = Array.isArray(data.files) ? data.files : [];
          if (
            prev.length === nextFiles.length &&
            prev.every(
              (item, index) =>
                item.path === nextFiles[index]?.path &&
                item.size === nextFiles[index]?.size &&
                item.modified_at_ns === nextFiles[index]?.modified_at_ns &&
                item.download_url === nextFiles[index]?.download_url &&
                item.is_generated === nextFiles[index]?.is_generated
            )
          ) {
            return prev;
          }
          return nextFiles;
        });
      }
    } catch (error) {
      if ((error as Error)?.name === "AbortError") {
        return;
      }
      const errorMsg =
        error instanceof Error ? error.message : String(error || "");
      const isTransientFetchError =
        /failed to fetch|networkerror|load failed/i.test(errorMsg);
      if (isTransientFetchError) {
        if (lastWorkspaceFilesErrorRef.current !== errorMsg) {
          lastWorkspaceFilesErrorRef.current = errorMsg;
          console.warn("Workspace files polling unavailable:", errorMsg);
        }
        return;
      }
      console.error("Failed to load workspace files:", error);
    } finally {
      if (workspaceFilesAbortRef.current === controller) {
        workspaceFilesAbortRef.current = null;
      }
      workspaceFilesLoadingRef.current = false;
      if (workspaceFilesPendingRefreshRef.current) {
        workspaceFilesPendingRefreshRef.current = false;
        void loadWorkspaceFiles();
      }
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    lastWorkspaceFilesErrorRef.current = "";
    workspaceFilesAbortRef.current?.abort();
    workspaceFilesLoadingRef.current = false;
    void loadWorkspaceFiles();
  }, [sessionId, loadWorkspaceFiles]);

  useEffect(() => {
    const intervalMs = isTyping ? 3000 : 10000;
    const id = window.setInterval(() => {
      const isVisible =
        typeof document !== "undefined" && document.visibilityState === "visible";
      if (!isUploading && isVisible) {
        void loadWorkspaceFiles();
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [isTyping, isUploading, loadWorkspaceFiles]);

  useEffect(() => {
    return () => {
      workspaceFilesAbortRef.current?.abort();
      workspaceFilesAbortRef.current = null;
      workspaceFilesLoadingRef.current = false;
    };
  }, []);

  const loadWorkspaceTree = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(
        `${API_URLS.WORKSPACE_TREE}?session_id=${sessionId}`
      );
      if (res.ok) {
        const data = await res.json();
        setWorkspaceTree(data);
        // 默认展开根与第一层，包括 generated 文件夹
        const init: Record<string, boolean> = { "": true };
        if (data?.children) {
          data.children.forEach((c: WorkspaceNode) => {
            if (c.is_dir) init[c.path] = true;
          });
        }
        setExpanded(init);
      }
    } catch (e) {
      console.error("load tree error", e);
    }
  };

  const toggleExpand = (p: string) =>
    setExpanded((prev) => ({ ...prev, [p]: !prev[p] }));

  const textLabels = useMemo(
    () => ({
      workspace: uiLanguage === "zh" ? "工作区" : "Workspace",
      workspaceHint:
        uiLanguage === "zh"
          ? "上传数据、选择分析文件并管理输出"
          : "Upload data, choose analysis files, and manage outputs.",
      language: uiLanguage === "zh" ? "系统语言" : "Language",
      uploaded: uiLanguage === "zh" ? "上传文件" : "Uploaded",
      generated: uiLanguage === "zh" ? "生成文件" : "Generated",
      all: uiLanguage === "zh" ? "全部文件" : "All Files",
      search: uiLanguage === "zh" ? "搜索文件名或路径..." : "Search by file name or path...",
      recentPreview: uiLanguage === "zh" ? "最近预览" : "Recent Preview",
      preview: uiLanguage === "zh" ? "预览" : "Preview",
      systemPrompt: "System Prompt",
      systemPromptPlaceholder:
        uiLanguage === "zh"
          ? "可选：追加到固定 System Prompt 后面"
          : "Optional: appended after the fixed system prompt.",
      bundleDownload:
        uiLanguage === "zh" ? "分类打包下载" : "Bundle Downloads",
      noFiles:
        uiLanguage === "zh"
          ? "当前筛选条件下没有文件"
          : "No files match the current filter.",
      tableBundle: uiLanguage === "zh" ? "表格文件" : "Tables",
      imageBundle: uiLanguage === "zh" ? "图片文件" : "Images",
      otherBundle: uiLanguage === "zh" ? "其他文件" : "Others",
      allBundle: uiLanguage === "zh" ? "全部打包" : "Download All",
      filesUnit: uiLanguage === "zh" ? "个文件" : "files",
      clickToPreview:
        uiLanguage === "zh" ? "点击卡片预览" : "Click a card to preview",
      relatedFiles:
        uiLanguage === "zh" ? "\u76f8\u5173\u6587\u4ef6" : "Related Files",
      assistantHint:
        uiLanguage === "zh"
          ? "中间只保留对话、流式分析和快捷操作"
          : "The center stays focused on chat, streaming analysis, and quick actions.",
      moveDialogToLeft:
        uiLanguage === "zh" ? "对话框移到左栏" : "Move Dialog Left",
      emptySystemPrompt:
        uiLanguage === "zh" ? "默认留空" : "Default empty",
      modelProvider: uiLanguage === "zh" ? "模型来源" : "Model Provider",
      providerLocal: uiLanguage === "zh" ? "本地" : "Local",
      providerHeywhale: uiLanguage === "zh" ? "和鲸 API" : "HeyWhale API",
      providerCustom: uiLanguage === "zh" ? "自定义模型" : "Custom Model",
      modelName: uiLanguage === "zh" ? "模型名称" : "Model Name",
      modelNamePlaceholder:
        uiLanguage === "zh"
          ? "例如：DeepAnalyze-8B 或 gpt-4o-mini"
          : "For example: DeepAnalyze-8B or gpt-4o-mini",
      temperature: uiLanguage === "zh" ? "温度" : "Temperature",
      temperatureHint:
        uiLanguage === "zh"
          ? "范围 0.0 - 2.0，默认 0.4"
          : "Range 0.0 - 2.0, default 0.4",
      heywhaleApiKey: uiLanguage === "zh" ? "和鲸 API Key" : "HeyWhale API Key",
      heywhaleApiKeyPlaceholder:
        uiLanguage === "zh"
          ? "输入和鲸平台申请的 API Key"
          : "Enter the API key issued by HeyWhale",
      customApiBase: uiLanguage === "zh" ? "自定义 API Base" : "Custom API Base",
      customApiBasePlaceholder:
        uiLanguage === "zh"
          ? "例如：https://api.example.com/v1"
          : "For example: https://api.example.com/v1",
      customApiKey: uiLanguage === "zh" ? "自定义 API Key" : "Custom API Key",
      customApiKeyPlaceholder:
        uiLanguage === "zh"
          ? "请输入你自己的 API Key（可选）"
          : "Enter your API key (optional)",
      needHeywhaleKey:
        uiLanguage === "zh"
          ? "请先填写和鲸 API Key"
          : "Please provide a HeyWhale API key first.",
      needCustomModel:
        uiLanguage === "zh"
          ? "请先填写自定义模型名称"
          : "Please provide a custom model name first.",
      needCustomApiBase:
        uiLanguage === "zh"
          ? "请先填写自定义 API Base 地址"
          : "Please provide a custom API base URL first.",
      exportCenter: uiLanguage === "zh" ? "导出中心" : "Export Center",
      exportHint:
        uiLanguage === "zh"
          ? "支持报告导出，结果会同步写入 generated 目录"
          : "Export reports into the generated folder.",
      exportMarkdown: uiLanguage === "zh" ? "MD 报告" : "MD Report",
      exportPdf: uiLanguage === "zh" ? "PDF 报告" : "PDF Report",
      exportMarkdownBusy:
        uiLanguage === "zh" ? "MD \u5bfc\u51fa\u4e2d..." : "Exporting MD...",
      exportPdfBusy:
        uiLanguage === "zh" ? "PDF \u7f16\u8bd1\u4e2d..." : "Compiling PDF...",
      exportPdfPending:
        uiLanguage === "zh"
          ? "PDF \u6b63\u5728\u7f16\u8bd1\u4e2d\uff0c\u8bf7\u7a0d\u7b49\u7247\u523b\u3002"
          : "PDF is compiling. Please wait for the download to start.",
      exportPdfPendingHint:
        uiLanguage === "zh"
          ? "PDF \u7f16\u8bd1\u4e2d\uff0c\u8bf7\u7a0d\u7b49\u3002\u542b\u56fe\u7247\u7684\u62a5\u544a\u901a\u5e38\u4f1a\u66f4\u6162\u3002"
          : "Compiling PDF. Please wait; reports with images usually take a bit longer.",
      exportCompilerMissing:
        uiLanguage === "zh"
          ? "\u672a\u68c0\u6d4b\u5230 PDF \u7f16\u8bd1\u5668\u3002\u8bf7\u5b89\u88c5 Pandoc \u548c XeLaTeX \u540e\u518d\u8bd5\u3002"
          : "PDF compiler not found. Install Pandoc and XeLaTeX, then try again.",
      exportCompilerMissingFallback:
        uiLanguage === "zh"
          ? "\u672a\u68c0\u6d4b\u5230 PDF \u7f16\u8bd1\u5668\uff0c\u5df2\u6539\u4e3a Markdown \u5bfc\u51fa\u3002\u8bf7\u5b89\u88c5 Pandoc \u548c XeLaTeX \u540e\u518d\u8bd5\u3002"
          : "PDF compiler not found. Exported Markdown instead. Install Pandoc and XeLaTeX, then try again.",
      exportDependencyMissing:
        uiLanguage === "zh"
          ? "PDF \u5bfc\u51fa\u4f9d\u8d56\u7f3a\u5931\u3002\u8bf7\u68c0\u67e5 Pandoc / pypandoc \u540e\u518d\u8bd5\u3002"
          : "PDF export dependency is missing. Check Pandoc / pypandoc and try again.",
      exportDependencyMissingFallback:
        uiLanguage === "zh"
          ? "PDF \u5bfc\u51fa\u4f9d\u8d56\u7f3a\u5931\uff0c\u5df2\u6539\u4e3a Markdown \u5bfc\u51fa\u3002\u8bf7\u68c0\u67e5 Pandoc / pypandoc \u540e\u518d\u8bd5\u3002"
          : "PDF export dependency is missing. Exported Markdown instead. Check Pandoc / pypandoc and try again.",
      exportFailed:
        uiLanguage === "zh" ? "\u5bfc\u51fa\u62a5\u544a\u5931\u8d25" : "Report export failed",
      exportBlockedWhileStreaming:
        uiLanguage === "zh"
          ? "\u6267\u884c\u4e2d\uff0c\u6682\u65f6\u65e0\u6cd5\u5bfc\u51fa"
          : "Export is unavailable while execution is still running.",
      exportActionTitle:
        uiLanguage === "zh"
          ? "\u540e\u7aef\u5bfc\u51fa PDF/MD \u5230 workspace"
          : "Export PDF/MD to the workspace from the backend",
      sectionGenerating:
        uiLanguage === "zh" ? "\uff08\u751f\u6210\u4e2d\uff09" : "(Generating)",
      uploadPanelTitle:
        uiLanguage === "zh" ? "上传文件到工作区" : "Upload files to workspace",
      uploadPanelHint:
        uiLanguage === "zh"
          ? "支持拖拽上传表格、数据库、文本。"
          : "Drag and drop tables, databases and text files.",
      uploadPanelMeta:
        uiLanguage === "zh"
          ? "例如 CSV / XLSX、SQLite / DB、TXT / MD 均可上传。"
          : "Examples: CSV / XLSX, SQLite / DB, TXT / MD .",
      streamInterrupted:
        uiLanguage === "zh"
          ? "⚠️ 与分析后端的连接已中断，你可以重新提交任务。"
          : "⚠️ Connection to the analysis backend was interrupted. You can resubmit the task.",
      appTitle: "DA-Studio",
      appSubtitle:
        uiLanguage === "zh" ? "由 DeepAnalyze 驱动" : "powered by DeepAnalyze",
    }),
    [uiLanguage]
  );

  const fileStatsTitle = uiLanguage === "zh" ? "生成结果" : "Generated Results";
  const fileStatsHint =
    uiLanguage === "zh"
      ? "这里集中展示分析过程生成的表格、图表和报告。"
      : "Tables, charts, and reports created by the analysis appear here.";

  const rightPanelSourceFiles = useMemo(
    () =>
      workspaceFiles.filter((file) => {
        const normalized = String(file.path || "")
          .replace(/\\/g, "/")
          .replace(/^\/+/, "")
          .trim();
        return !!normalized && !normalized.includes("/");
      }),
    [workspaceFiles]
  );

  useEffect(() => {
    if (
      !chatLoaded ||
      fileSelectionInitializedRef.current ||
      !rightPanelSourceFiles.length
    ) {
      return;
    }
    const uploadedPaths = rightPanelSourceFiles
      .filter((file) => !isGeneratedWorkspaceFile(file))
      .map((file) => file.path);
    setSelectedAnalysisFiles(new Set(uploadedPaths));
    fileSelectionInitializedRef.current = true;
  }, [chatLoaded, isGeneratedWorkspaceFile, rightPanelSourceFiles]);

  const toggleAnalysisFile = useCallback((path: string, selected: boolean) => {
    setSelectedAnalysisFiles((current) => {
      return toggleSelectedPath(current, path, selected);
    });
    fileSelectionInitializedRef.current = true;
  }, []);

  const isGeneratedBundleFile = useCallback(
    (file?: Pick<WorkspaceFile, "path"> | null) => {
      const normalized = normalizeWorkspacePath(file?.path);
      return normalized === "generated" || normalized.startsWith("generated/");
    },
    []
  );

  const dedupeGeneratedDisplayFiles = useCallback((files: WorkspaceFile[]) => {
    const result: WorkspaceFile[] = [];
    const generatedSlotByKey = new Map<string, number>();

    files.forEach((file) => {
      if (!isGeneratedWorkspaceFile(file)) {
        result.push(file);
        return;
      }

      const dedupeKey = `${file.name}::${file.size}::${file.extension || ""}`;
      const existingIndex = generatedSlotByKey.get(dedupeKey);
      if (existingIndex === undefined) {
        generatedSlotByKey.set(dedupeKey, result.length);
        result.push(file);
        return;
      }

      const existing = result[existingIndex];
      const shouldReplace =
        isGeneratedBundleFile(existing) && !isGeneratedBundleFile(file);
      if (shouldReplace) {
        result[existingIndex] = file;
      }
    });

    return result;
  }, [isGeneratedBundleFile]);

  const normalizedTemperature = useMemo(() => {
    const parsed = Number.parseFloat(modelTemperature);
    if (!Number.isFinite(parsed)) return 0.4;
    return Math.min(2, Math.max(0, parsed));
  }, [modelTemperature]);

  const baseSystemPrompt = useMemo(() => {
    let mergedPrompt = "";
    if (llmProvider === "custom") {
      const customPrefix =
        uiLanguage === "zh"
          ? CUSTOM_MODEL_SYSTEM_PREFIX_ZH
          : CUSTOM_MODEL_SYSTEM_PREFIX_EN;
      if (!mergedPrompt) {
        mergedPrompt = customPrefix;
      } else if (!mergedPrompt.startsWith(customPrefix)) {
        mergedPrompt = `${customPrefix}\n\n${mergedPrompt}`;
      }

    }

    if (
      !isDeepAnalyzeModelName(
        llmProvider === "custom" ? customModelName : DEFAULT_MODEL_NAME
      ) &&
      !mergedPrompt.includes(EXECUTE_RESULT_PREFIX)
    ) {
      const executeResultNotice =
        uiLanguage === "zh"
          ? EXECUTE_RESULT_NOTICE_ZH
          : EXECUTE_RESULT_NOTICE_EN;
      mergedPrompt = mergedPrompt
        ? `${mergedPrompt}\n\n${executeResultNotice}`
        : executeResultNotice;
    }

    return mergedPrompt;
  }, [customModelName, llmProvider, uiLanguage]);

  const effectiveSystemPrompt = useMemo(() => {
    const customPrompt = systemPrompt.trim();
    if (!customPrompt) return baseSystemPrompt;
    return baseSystemPrompt
      ? `${baseSystemPrompt}\n\n# User System Prompt\n${customPrompt}`
      : customPrompt;
  }, [baseSystemPrompt, systemPrompt]);

  const latestTaskInstruction = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (
        messages[index].sender === "user" &&
        !messages[index].id.startsWith("manual-instruction-")
      ) {
        return messages[index].content;
      }
    }
    return inputValue;
  }, [inputValue, messages]);

  useEffect(() => {
    if (!chatLoaded || !sessionId) return;
    const timer = window.setTimeout(() => {
      void fetch(API_URLS.SESSION_TASK, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          task_config: {
            instruction: latestTaskInstruction,
            selected_files: Array.from(selectedAnalysisFiles),
            provider: llmProvider,
            model: llmProvider === "custom" ? customModelName : DEFAULT_MODEL_NAME,
            temperature: normalizedTemperature,
            system_prompt: systemPrompt.trim(),
            ui_language: uiLanguage,
            interaction_mode: interactionMode,
          },
        }),
      }).catch((error) => console.warn("save task config failed", error));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [
    chatLoaded,
    customModelName,
    systemPrompt,
    latestTaskInstruction,
    interactionMode,
    llmProvider,
    normalizedTemperature,
    selectedAnalysisFiles,
    sessionId,
    uiLanguage,
  ]);

  const generatedBundleCounts = useMemo(() => {
    const generatedFiles = workspaceFiles.filter(
      (file) => isGeneratedBundleFile(file) && !isPythonWorkspaceFile(file)
    );
    return {
      all: generatedFiles.length,
      table: generatedFiles.filter((file) => file.category === "table").length,
      image: generatedFiles.filter((file) => file.category === "image").length,
      other: generatedFiles.filter((file) => (file.category || "other") === "other").length,
    };
  }, [isGeneratedBundleFile, workspaceFiles]);

  const workspaceFileCounts = useMemo(() => {
    return countWorkspaceFiles(rightPanelSourceFiles);
  }, [rightPanelSourceFiles]);

  const filteredWorkspaceFiles = useMemo(() => {
    return dedupeGeneratedDisplayFiles(
      filterWorkspaceFiles(rightPanelSourceFiles, workspaceView, workspaceSearch)
    );
  }, [
    dedupeGeneratedDisplayFiles,
    rightPanelSourceFiles,
    workspaceSearch,
    workspaceView,
  ]);

  const getLocalizedPreviewType = useCallback(
    (
      type:
        | "text"
        | "markdown"
        | "table"
        | "database"
        | "image"
        | "pdf"
        | "binary"
    ) => {
      if (uiLanguage === "zh") {
        return {
          image: "图片",
          pdf: "PDF",
          text: "文本",
          markdown: "Markdown",
          table: "表格",
          database: "数据库",
          binary: "二进制文件",
        }[type];
      }
      return {
        image: "Image",
        pdf: "PDF",
        text: "Text",
        markdown: "Markdown",
        table: "Table",
        database: "Database",
        binary: "Binary",
      }[type];
    },
    [uiLanguage]
  );

  const getFileAccentClasses = useCallback((file: WorkspaceFile) => {
    if (file.category === "table") {
      return "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900 dark:bg-emerald-950/20";
    }
    if (file.category == "image") {
      return "border-blue-200 bg-blue-50/70 dark:border-blue-900 dark:bg-blue-950/20";
    }
    return "border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900/60";
  }, []);

  const downloadGeneratedBundle = useCallback(
    async (category: "all" | "table" | "image" | "other") => {
      try {
        const url = buildApiUrlWithParams(
          API_CONFIG.ENDPOINTS.WORKSPACE_DOWNLOAD_BUNDLE,
          { category, session_id: sessionId }
        );
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = `generated_${category}.zip`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
      } catch (error) {
        toast({
          description:
            uiLanguage === "zh" ? "打包下载失败" : "Bundle download failed",
          variant: "destructive",
        });
      }
    },
    [sessionId, toast, uiLanguage]
  );

  const deleteFile = async (p: string) => {
    try {
      const url = `${API_URLS.WORKSPACE_DELETE_FILE}?path=${encodeURIComponent(
        p
      )}&session_id=${encodeURIComponent(sessionId)}`;
      const res = await fetch(url, { method: "DELETE" });
      if (res.ok) {
        setSelectedAnalysisFiles((current) => {
          const next = new Set(current);
          next.delete(p);
          return next;
        });
        await loadWorkspaceTree();
        await loadWorkspaceFiles();
      }
    } catch (e) {
      console.error("delete file error", e);
    }
  };

  const deleteDir = async (p: string) => {
    try {
      const url = `${API_URLS.WORKSPACE_DELETE_DIR}?path=${encodeURIComponent(
        p
      )}&recursive=true&session_id=${encodeURIComponent(sessionId)}`;
      const res = await fetch(url, { method: "DELETE" });
      if (res.ok) {
        await loadWorkspaceTree();
        await loadWorkspaceFiles();
      }
    } catch (e) {
      console.error("delete dir error", e);
    }
  };

  // 移动：将工作区内的文件/文件夹移动到指定目录（空字符串表示根目录）
  const moveToDir = async (srcPath: string, dstDir: string) => {
    try {
      const url = buildApiUrlWithParams(API_CONFIG.ENDPOINTS.WORKSPACE_MOVE, {
        src: srcPath,
        dst_dir: dstDir,
        session_id: sessionId,
      });
      const res = await fetch(url, { method: "POST" });
      if (res.ok) {
        await loadWorkspaceTree();
        await loadWorkspaceFiles();
      }
    } catch (e) {
      console.error("move to dir error", e);
    }
  };

  const uploadToDir = async (dirPath: string, files: FileList | File[]) => {
    try {
      setIsUploading(true);
      const form = new FormData();
      const arr: File[] = Array.from(files as File[]);
      const blockedFiles = arr.filter((file) => {
        const ext = file.name?.split(".").pop()?.toLowerCase() || "";
        return !!ext && BLOCKED_UPLOAD_EXTENSIONS.has(ext);
      });
      const uploadableFiles = arr.filter((file) => !blockedFiles.includes(file));
      if (!uploadableFiles.length) {
        setUploadMsg(
          uiLanguage === "zh"
            ? "已拦截 .py 文件，未执行上传"
            : "Blocked .py files. No files uploaded."
        );
        setTimeout(() => setUploadMsg(""), 2500);
        return;
      }
      uploadableFiles.forEach((f) => form.append("files", f));
      const url = `${API_URLS.WORKSPACE_UPLOAD_TO}?dir=${encodeURIComponent(
        dirPath || ""
      )}&session_id=${encodeURIComponent(sessionId)}`;
      const response = await fetch(url, { method: "POST", body: form });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const uploadedPaths = Array.isArray(payload?.files)
        ? payload.files.map((file: { path?: string }) => file.path).filter(Boolean)
        : [];
      if (!dirPath && uploadedPaths.length) {
        setSelectedAnalysisFiles((current) => {
          const next = new Set(current);
          uploadedPaths.forEach((path: string) => next.add(path));
          return next;
        });
        fileSelectionInitializedRef.current = true;
      }
      await loadWorkspaceTree();
      await loadWorkspaceFiles();
      if (blockedFiles.length) {
        setUploadMsg(
          uiLanguage === "zh"
            ? `上传 ${uploadableFiles.length} 个文件，已忽略 ${blockedFiles.length} 个 .py 文件`
            : `Uploaded ${uploadableFiles.length} file(s), ignored ${blockedFiles.length} .py file(s)`
        );
      } else {
        setUploadMsg(
          uiLanguage === "zh"
            ? `上传成功 ${uploadableFiles.length} 个文件`
            : `Uploaded ${uploadableFiles.length} file(s)`
        );
      }
      setTimeout(() => setUploadMsg(""), 2000);
    } catch (e) {
      console.error("upload to dir error", e);
      setUploadMsg(uiLanguage === "zh" ? "上传失败" : "Upload failed");
      setTimeout(() => setUploadMsg(""), 2500);
    } finally {
      setIsUploading(false);
    }
  };

  const openNode = async (node: WorkspaceNode) => {
    if (node.is_dir) return;
    setSelectedWorkspacePath(node.path);
    const ext = (node.extension || "").replace(/^\./, "").toLowerCase();
    const correctedDownloadUrl = resolveWorkspaceFileUrl(node.download_url || "", {
      download: true,
    });
    const correctedPreviewUrl = resolveWorkspaceFileUrl(
      node.preview_url || node.download_url || "",
      { download: false }
    );
    const mapped: WorkspaceFile = {
      name: node.name,
      path: node.path,
      size: node.size || 0,
      extension: ext,
      icon: node.icon || "",
      category: ["csv", "tsv", "xlsx", "xls", "parquet", "sqlite", "db"].includes(ext)
        ? "table"
        : ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"].includes(ext)
          ? "image"
          : "other",
      is_generated: node.is_generated,
      download_url: correctedDownloadUrl,
      preview_url: correctedPreviewUrl,
    };
    openPreview(mapped);
  };

  const onContextMenu = (e: React.MouseEvent, node: WorkspaceNode) => {
    e.preventDefault();
    setContextTarget(node);
    setContextPos({ x: e.clientX, y: e.clientY });
  };

  const closeContext = () => {
    setContextPos(null);
    setContextTarget(null);
  };

  // 将后端树转换为 Arborist 数据
  type ArborNode = {
    id: string;
    name: string;
    isDir: boolean;
    icon?: string;
    download_url?: string;
    preview_url?: string;
    extension?: string;
    size?: number;
    children?: ArborNode[];
    isGenerated?: boolean; // 标识是否为代码生成的文件
  };

  const toArbor = (node: WorkspaceNode): ArborNode => ({
    id: node.path || "",
    name: node.name || "workspace",
    isDir: node.is_dir,
    icon: node.icon,
    download_url: node.download_url,
    preview_url: node.preview_url,
    extension: node.extension,
    size: node.size,
    isGenerated: node.is_generated,
    children: node.children?.map(toArbor),
  });

  const getExt = (name?: string, ext?: string) => {
    const fromExt = (ext || "").replace(/^\./, "").toLowerCase();
    if (fromExt) return fromExt;
    if (!name) return "txt";
    const p = name.lastIndexOf(".");
    return p > -1 ? name.slice(p + 1).toLowerCase() : "txt";
  };

  const Row = ({
    node,
    style,
    dragHandle,
  }: {
    node: NodeApi<ArborNode>;
    style: React.CSSProperties;
    dragHandle?: (el: HTMLDivElement | null) => void;
  }) => {
    const data = node.data;
    const isDir = data.isDir;
    const isGenerated = data.isGenerated || false;
    const isGeneratedFolder = isDir && data.name === "generated";
    const ext = getExt(data.name, data.extension);

    return (
      <div style={style}>
        {/* Generated 分组标题 + 删除按钮（不遮挡、不受折叠影响） */}
        {isGeneratedFolder && (
          <div className="mt-2 mb-1 px-2 flex items-center justify-between select-none">
            <div className="flex items-center gap-2 text-[11px] text-purple-600 dark:text-purple-400">
              <span className="h-px w-4 bg-purple-200 dark:bg-purple-800" />
              <span className="font-medium">代码生成文件</span>
            </div>
            <button
              className="text-red-600 hover:text-red-700 p-1 rounded hover:bg-red-50 dark:hover:bg-red-950/20"
              aria-label="删除生成文件夹"
              title="删除生成文件夹"
              onClick={(e) => {
                e.stopPropagation();
                setDeleteIsDir(true);
                setDeleteConfirmPath(data.id);
              }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        <div
          className={`flex items-center justify-between rounded px-2 py-1 transition-colors ${
            data.id === selectedWorkspacePath
              ? "bg-blue-50 ring-1 ring-blue-200 dark:bg-blue-950/30 dark:ring-blue-800"
              : "hover:bg-gray-50 dark:hover:bg-gray-900"
          } ${isGenerated ? "bg-purple-50 dark:bg-purple-950/20" : ""}`}
          onClick={(e) => {
            if (isDir) {
              node.toggle();
              return;
            }
            if (singleClickTimerRef.current) {
              window.clearTimeout(singleClickTimerRef.current);
              singleClickTimerRef.current = null;
            }
            // 延迟触发预览，若短时间内发生双击会被取消
            singleClickTimerRef.current = window.setTimeout(() => {
              openNode({
                name: data.name,
                path: data.id,
                is_dir: false,
                download_url: data.download_url,
                extension: data.extension,
                size: data.size,
                icon: data.icon,
              } as any);
              singleClickTimerRef.current = null;
            }, 180);
          }}
          onDoubleClick={(e) => {
            if (isDir) return;
            e.stopPropagation();
            if (singleClickTimerRef.current) {
              window.clearTimeout(singleClickTimerRef.current);
              singleClickTimerRef.current = null;
            }
            if (data.download_url) {
              downloadFileByUrl(data.name, data.download_url);
            }
          }}
          onContextMenu={(e) =>
            onContextMenu(
              e as any,
              {
                name: data.name,
                path: data.id,
                is_dir: isDir,
                download_url: data.download_url,
                extension: data.extension,
                size: data.size,
                icon: data.icon,
              } as any
            )
          }
          onDragOver={(e) => {
            if (isDir) {
              e.preventDefault();
              e.dataTransfer.dropEffect = (e.dataTransfer.types || []).includes(
                "text/x-workspace-path"
              )
                ? "move"
                : "copy";
            }
          }}
          onDragEnter={(e) => {
            if (isDir) setDragOverPath(data.id);
          }}
          onDragLeave={(e) => {
            if (isDir) setDragOverPath(null);
          }}
          onDrop={(e) => {
            if (!isDir) return;
            e.preventDefault();
            uploadToDir(data.id, e.dataTransfer.files || []);
            setDragOverPath(null);
          }}
        >
          <div
            className="flex items-center gap-2 text-sm"
            ref={dragHandle}
            draggable={!isDir}
            onDragStart={(e) => {
              if (isDir) return;
              // 将工作区内路径放入自定义 MIME，供目标目录 onDrop 读取
              e.dataTransfer.setData("text/x-workspace-path", data.id);
              // 提示为移动操作
              e.dataTransfer.effectAllowed = "move";
            }}
          >
            {isDir ? (
              <>
                <span
                  className={
                    isGenerated
                      ? "text-purple-600 dark:text-purple-400"
                      : "text-gray-500"
                  }
                >
                  {node.isOpen ? "▾" : "▸"}
                </span>
                {isGenerated ? (
                  <Code2 className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                ) : (
                  <FolderOpen className="h-3.5 w-3.5 text-gray-500" />
                )}
              </>
            ) : (
              <div style={{ width: 16, height: 16 }}>
                {/* 动态扩展样式，fallback 到 txt */}
                {/* @ts-ignore */}
                <FileIcon
                  extension={ext}
                  {...((defaultStyles as any)[ext] ||
                    (defaultStyles as any).txt)}
                />
              </div>
            )}
            <span
              className={`truncate ${isGenerated
                ? "text-purple-700 dark:text-purple-300 font-medium"
                : ""
                }`}
            >
              {data.name}
            </span>
            {typeof data.size === "number" && !isDir && (
              <span className="text-[10px] text-gray-400 ml-2 shrink-0">
                {formatFileSize(data.size)}
              </span>
            )}
            {isGenerated && !isDir && (
              <Sparkles className="h-3 w-3 text-purple-500 ml-1 shrink-0" />
            )}
          </div>
          {/* 行尾不再展示下载/删除按钮。双击/点击行为保持不变；右键菜单提供下载/删除。*/}
        </div>
      </div>
    );
  };

  const renderTree = (node: WorkspaceNode, depth = 0) => {
    const isDir = node.is_dir;
    const isGenerated = node.is_generated || false;
    const isGeneratedFolder = isDir && node.name === "generated" && depth === 1;
    const pad = { paddingLeft: `${8 + depth * 14}px` } as React.CSSProperties;

    return (
      <div key={node.path || "root"}>
        {/* Generated 文件夹上方添加分隔线 */}
        {isGeneratedFolder && (
          <div className="mb-2 mt-2 ml-2 border-t-2 border-purple-200 dark:border-purple-800 relative">
            <div className="absolute -top-2.5 left-2 bg-white dark:bg-gray-950 px-2 text-[10px] text-purple-600 dark:text-purple-400 font-medium">
              代码生成文件
            </div>
          </div>
        )}
        <div
          className={`flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-900 rounded px-2 py-1 cursor-default ${isGenerated ? "bg-purple-50 dark:bg-purple-950/20" : ""
            }`}
          style={pad}
          onClick={(e) => {
            if (isDir) return toggleExpand(node.path);
            if (singleClickTimerRef.current) {
              window.clearTimeout(singleClickTimerRef.current);
              singleClickTimerRef.current = null;
            }
            singleClickTimerRef.current = window.setTimeout(() => {
              openNode(node);
              singleClickTimerRef.current = null;
            }, 180);
          }}
          onDoubleClick={(e) => {
            if (isDir) return;
            e.stopPropagation();
            if (singleClickTimerRef.current) {
              window.clearTimeout(singleClickTimerRef.current);
              singleClickTimerRef.current = null;
            }
            if (node.download_url) {
              downloadFileByUrl(node.name, node.download_url);
            } else {
              openNode(node);
            }
          }}
          onContextMenu={(e) => onContextMenu(e, node)}
          onDragOver={(e) => {
            if (isDir) e.preventDefault();
          }}
          onDrop={async (e) => {
            if (!isDir) return;
            e.preventDefault();
            const dt = e.dataTransfer;
            // 1) 如果是从 OS 拖入文件
            if (dt.files && dt.files.length) {
              uploadToDir(node.path, dt.files || []);
              return;
            }
            // 2) 如果是从 generated/ 内部拖动的文件，使用自定义 data 传递路径
            const srcPath = dt.getData("text/x-workspace-path");
            if (srcPath) {
              try {
                const url = buildApiUrlWithParams(
                  API_CONFIG.ENDPOINTS.WORKSPACE_MOVE,
                  {
                    src: srcPath,
                    dst_dir: node.path,
                    session_id: sessionId,
                  }
                );
                const res = await fetch(url, { method: "POST" });
                if (res.ok) {
                  await loadWorkspaceTree();
                  await loadWorkspaceFiles();
                }
              } catch (err) {
                console.error("move error", err);
              }
            }
          }}
        >
          <div className="flex items-center gap-2 text-sm">
            {isDir ? (
              <>
                <span
                  className={
                    isGenerated
                      ? "text-purple-600 dark:text-purple-400"
                      : "text-gray-500"
                  }
                >
                  {expanded[node.path] ? "▾" : "▸"}
                </span>
                {isGenerated ? (
                  <Code2
                    className={`h-3.5 w-3.5 ${isGenerated
                      ? "text-purple-600 dark:text-purple-400"
                      : "text-gray-500"
                      }`}
                  />
                ) : (
                  <FolderOpen className="h-3.5 w-3.5 text-gray-500" />
                )}
              </>
            ) : (
              <span
                className={isGenerated ? "text-purple-400" : "text-gray-400"}
              >
                •
              </span>
            )}
            <span
              className={`truncate ${isGenerated
                ? "text-purple-700 dark:text-purple-300 font-medium"
                : ""
                }`}
            >
              {node.icon && !isGenerated ? `${node.icon} ` : ""}
              {node.name || "workspace"}
            </span>
            {!isDir && typeof node.size === "number" && (
              <span className="text-[10px] text-gray-400 ml-2 shrink-0">
                {formatFileSize(node.size)}
              </span>
            )}
            {isGenerated && !isDir && (
              <Sparkles className="h-3 w-3 text-purple-500 ml-1 shrink-0" />
            )}
          </div>
          {/* 双击/点击行为已经在容器上：目录展开，文件预览/下载保持一致 */}
        </div>
        {isDir && expanded[node.path] && node.children && (
          <div>{node.children.map((c) => renderTree(c, depth + 1))}</div>
        )}
      </div>
    );
  };

  const clearWorkspace = async () => {
    if (!sessionId) return;
    try {
      const clearUrl = buildApiUrlWithParams(
        API_CONFIG.ENDPOINTS.WORKSPACE_CLEAR,
        { session_id: sessionId }
      );
      let response: Response;
      try {
        response = await fetch(clearUrl, { method: "DELETE" });
      } catch (deleteError) {
        console.warn(
          "clear workspace DELETE failed, fallback to POST:",
          deleteError
        );
        response = await fetch(clearUrl, { method: "POST" });
      }

      if (response.status === 405) {
        response = await fetch(clearUrl, { method: "POST" });
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      if (response.ok) {
        setWorkspaceFiles([]);
        setSelectedAnalysisFiles(new Set());
        fileSelectionInitializedRef.current = false;
        discardPendingContinuation();
        await loadWorkspaceTree();
        await loadWorkspaceFiles();
        toast({
          description: "工作区已清空",
        });
      }
    } catch (error) {
      console.error("Failed to clear workspace:", error);
      toast({
        description: "清空失败",
        variant: "destructive",
      });
    }
  };

  const copyToClipboard = async (text: string): Promise<boolean> => {
    try {
      // 优先使用安全的 Clipboard API
      if (
        typeof navigator !== "undefined" &&
        (navigator as any).clipboard &&
        typeof (navigator as any).clipboard.writeText === "function"
      ) {
        await (navigator as any).clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // 继续尝试后备方案
    }
    try {
      // 后备方案：隐形 textarea + execCommand
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      textarea.style.pointerEvents = "none";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(textarea);
      return ok;
    } catch (e) {
      return false;
    }
  };

  const extractCode = (content: string): string => {
    const codeBlockMatch = content.match(/```(?:python)?\n?([\s\S]*?)```/);
    return codeBlockMatch ? codeBlockMatch[1].trim() : content;
  };

  const getUrlFileName = useCallback((url: string): string => {
    if (!url) return "";
    try {
      const parsed = new URL(url, "http://local");
      if (parsed.pathname === "/workspace/download") {
        const rawPath = parsed.searchParams.get("path") || "";
        return decodeURIComponent(rawPath).split("/").pop() || "";
      }
      return decodeURIComponent(parsed.pathname.split("/").pop() || "");
    } catch {
      return url.split(/[/?#]/).pop() || "";
    }
  }, []);

  const isImageAssetUrl = useCallback(
    (url: string, fileName?: string): boolean => {
      const target = fileName || getUrlFileName(url) || url;
      return /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(target);
    },
    [getUrlFileName]
  );

  const guessLanguageByExtension = (ext: string): string => {
    const e = ext.toLowerCase();
    const map: Record<string, string> = {
      js: "javascript",
      jsx: "jsx",
      ts: "typescript",
      tsx: "tsx",
      json: "json",
      py: "python",
      md: "markdown",
      html: "html",
      css: "css",
      sh: "bash",
      yml: "yaml",
      yaml: "yaml",
      csv: "csv",
      txt: "text",
      go: "go",
      rs: "rust",
      java: "java",
      php: "php",
      sql: "sql",
    };
    return map[e] || "text";
  };

  const buildWorkspaceTransferUrl = useCallback(
    (
      relativePath: string,
      options?: {
        sessionId?: string;
        download?: boolean;
      }
    ) => {
      const params = new URLSearchParams();
      params.set("session_id", options?.sessionId || sessionId || "default");
      params.set("path", relativePath.replace(/^\/+/, ""));
      if (options?.download) {
        params.set("download", "1");
      }
      return `/workspace/download?${params.toString()}`;
    },
    [sessionId]
  );

  const resolveWorkspaceRelativePath = useCallback(
    (rawPath: string): string => {
      const decodeSafe = (value: string): string => {
        try {
          return decodeURIComponent(value);
        } catch {
          return value;
        }
      };

      const stripped = String(rawPath || "")
        .trim()
        .replace(/^<(.+)>$/, "$1");
      if (!stripped) {
        return "";
      }

      const normalizedRawPath = stripped
        .replace(/\\/g, "/")
        .replace(/^\.\/+/, "")
        .replace(/^\/+/, "");
      const [pathWithoutQuery] = normalizedRawPath.split(/[?#]/, 1);
      if (!pathWithoutQuery) {
        return "";
      }

      const normalizedSegments: string[] = [];
      for (const segment of pathWithoutQuery.split("/")) {
        const current = segment.trim();
        if (!current || current === ".") continue;
        if (current === "..") {
          if (normalizedSegments.length > 0) {
            normalizedSegments.pop();
          }
          continue;
        }
        normalizedSegments.push(current);
      }

      const normalizedPath = normalizedSegments.join("/");
      if (!normalizedPath) {
        return "";
      }

      const normalizedTarget = decodeSafe(normalizedPath).toLowerCase();
      const hasSlash = normalizedPath.includes("/");
      const matchedFile = workspaceFilesRef.current
        .filter((file) => {
          const filePath = String(file.path || "")
            .replace(/\\/g, "/")
            .replace(/^\/+/, "")
            .trim();
          if (!filePath) {
            return false;
          }
          const lowerFilePath = decodeSafe(filePath).toLowerCase();
          const lowerFileName = decodeSafe(String(file.name || "")).toLowerCase();
          return (
            lowerFilePath === normalizedTarget ||
            (!hasSlash &&
              (lowerFileName === normalizedTarget ||
                lowerFilePath.endsWith(`/${normalizedTarget}`)))
          );
        })
        .sort((left, right) => {
          const score = (file: WorkspaceFile) => {
            const filePath = decodeSafe(
              String(file.path || "")
              .replace(/\\/g, "/")
              .replace(/^\/+/, "")
              .trim()
            ).toLowerCase();
            let current = 0;
            if (filePath === normalizedTarget) current += 100;
            if (
              !hasSlash &&
              decodeSafe(String(file.name || "")).toLowerCase() === normalizedTarget
            ) {
              current += 20;
            }
            if (filePath.startsWith("generated/")) current += 10;
            if (file.category === "image") current += 5;
            return current;
          };
          return score(right) - score(left);
        })[0];

      return matchedFile?.path || normalizedPath;
    },
    []
  );

  const normalizeToLocalFileUrl = useCallback(
    (
      rawUrl: string,
      options?: {
        download?: boolean;
      }
    ): string => {
      if (!rawUrl) {
        return "";
      }

      const trimmed = String(rawUrl)
        .trim()
        .replace(/^<(.+)>$/, "$1")
        .trim();
      if (!trimmed) {
        return "";
      }
      const desiredDownload = options?.download ?? false;
      if (/^(data:|blob:)/i.test(trimmed)) {
        return trimmed;
      }

      if (/^\/\//.test(trimmed)) {
        const proto =
          typeof window !== "undefined" ? window.location.protocol : "http:";
        return `${proto}${trimmed}`;
      }

      const parseCandidate = (value: string) => {
        try {
          if (/^https?:\/\//i.test(value)) {
            return new URL(value);
          }
          return new URL(value, "http://local");
        } catch {
          return null;
        }
      };

      const parsed = parseCandidate(trimmed);
      const isAbsoluteHttp = /^https?:\/\//i.test(trimmed);
      const isLocalLikeHost =
        !!parsed &&
        (parsed.hostname === "local" ||
          parsed.hostname === "localhost" ||
          parsed.hostname.startsWith("127.") ||
          parsed.origin === API_CONFIG.BACKEND_BASE_URL);

      if (parsed && parsed.pathname === "/workspace/download") {
        const nextUrl = new URL(parsed.pathname, "http://local");
        const relativePath = resolveWorkspaceRelativePath(
          parsed.searchParams.get("path") || ""
        );
        nextUrl.searchParams.set(
          "session_id",
          parsed.searchParams.get("session_id") || sessionId || "default"
        );
        nextUrl.searchParams.set("path", relativePath);
        if (desiredDownload) {
          nextUrl.searchParams.set("download", "1");
        } else {
          nextUrl.searchParams.delete("download");
        }
        const version = parsed.searchParams.get("v");
        if (version) {
          nextUrl.searchParams.set("v", version);
        }
        return `${nextUrl.pathname}${nextUrl.search}`;
      }

      if (parsed && isLocalLikeHost) {
        const normalizedPath = parsed.pathname.replace(/^\/+/, "");
        const parts = normalizedPath.split("/").filter(Boolean);

        if (parts[0] === "workspace" && parts.length >= 3) {
          return buildWorkspaceTransferUrl(
            resolveWorkspaceRelativePath(parts.slice(2).join("/")),
            {
            sessionId: parts[1],
            download: desiredDownload,
            }
          );
        }

        if (parts.length >= 2) {
          return buildWorkspaceTransferUrl(
            resolveWorkspaceRelativePath(parts.slice(1).join("/")),
            {
            sessionId: parts[0],
            download: desiredDownload,
            }
          );
        }

        if (parts.length === 1 && sessionId) {
          return buildWorkspaceTransferUrl(resolveWorkspaceRelativePath(parts[0]), {
            sessionId,
            download: desiredDownload,
          });
        }
      }

      if (isAbsoluteHttp) {
        return trimmed;
      }

      const rel = resolveWorkspaceRelativePath(trimmed);
      if (!rel) {
        return "";
      }

      return buildWorkspaceTransferUrl(resolveWorkspaceRelativePath(rel), {
        sessionId,
        download: desiredDownload,
      });
    },
    [buildWorkspaceTransferUrl, resolveWorkspaceRelativePath, sessionId]
  );

  const resolveWorkspaceFileUrl = useCallback(
    (
      rawUrl: string,
      options?: {
        download?: boolean;
      }
    ): string => {
      return normalizeToLocalFileUrl(rawUrl || "", options);
    },
    [normalizeToLocalFileUrl]
  );

  const loadPreview = useCallback(
    async (
      file: WorkspaceFile,
      options?: {
        openModal?: boolean;
        page?: number;
        tableName?: string;
        sheetName?: string;
      }
    ) => {
      const nextPage = options?.page ?? 1;
      const nextTableName = options?.tableName ?? "";
      const nextSheetName = options?.sheetName ?? "";

      const requestId = ++previewRequestIdRef.current;

      setPreviewTitle(file.name);
      setPreviewDownloadUrl(
        resolveWorkspaceFileUrl(file.download_url || file.preview_url || "", {
          download: true,
        })
      );
      setPreviewPage(nextPage);
      setPreviewTableName(nextTableName);
      setPreviewSheetName(nextSheetName);
      if (options?.openModal) {
        setIsPreviewOpen(true);
      }
      setPreviewLoading(true);
      setPreviewPayload(null);

      const ext = (file.extension || "").replace(/^\./, "").toLowerCase();
      if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) {
        setPreviewType("image");
        const correctedUrl = resolveWorkspaceFileUrl(
          file.preview_url || file.download_url,
          { download: false }
        );
        setPreviewContent(correctedUrl);
        setPreviewPayload({
          kind: "image",
          title: file.name,
          content: correctedUrl,
        });
        setPreviewLoading(false);
        return;
      }
      if (ext === "pdf") {
        setPreviewType("pdf");
        const correctedUrl = resolveWorkspaceFileUrl(
          file.preview_url || file.download_url,
          { download: false }
        );
        setPreviewContent(correctedUrl);
        setPreviewPayload({
          kind: "pdf",
          title: file.name,
          content: correctedUrl,
        });
        setPreviewLoading(false);
        return;
      }

      try {
        const previewPath = file.path || file.name;
        const res = await fetch(
          buildApiUrlWithParams(API_CONFIG.ENDPOINTS.WORKSPACE_PREVIEW, {
            path: previewPath,
            session_id: sessionId,
            page: nextPage,
            page_size: PREVIEW_TABLE_PAGE_SIZE,
            table_name: nextTableName,
            sheet_name: nextSheetName,
          })
        );
        if (!res.ok) throw new Error("failed to fetch preview");
        const payload = (await res.json()) as PreviewPayload;
        if (previewRequestIdRef.current !== requestId) return;
        setPreviewPayload(payload);
        setPreviewType(payload.kind);
        setPreviewContent(payload.content || "");
      } catch (e) {
        if (previewRequestIdRef.current !== requestId) return;
        setPreviewType("binary");
        setPreviewContent(file.download_url);
        setPreviewPayload({
          kind: "binary",
          title: file.name,
          content: file.download_url,
        });
      } finally {
        if (previewRequestIdRef.current === requestId) {
          setPreviewLoading(false);
        }
      }
    },
    [sessionId]
  );

  const openFullPreview = useCallback(
    async (file: WorkspaceFile) => {
      await loadPreview(file, {
        openModal: true,
        page: 1,
        tableName: "",
        sheetName: "",
      });
    },
    [loadPreview]
  );

  const openPreview = async (file: WorkspaceFile) => {
    setPreviewTitle(file.name);
    await loadPreview(file, {
      openModal: false,
      page: 1,
      tableName: "",
      sheetName: "",
    });
  };

  const openSampleDialog = async () => {
    setIsSampleDialogOpen(true);
    if (sampleCatalog.length || isSampleCatalogLoading) return;

    setIsSampleCatalogLoading(true);
    try {
      const response = await fetch(API_URLS.WORKSPACE_SAMPLES);
      if (!response.ok) throw new Error(await response.text());
      const payload = await response.json();
      const datasets = normalizeSampleCatalog(payload) as SampleDataset[];
      if (!datasets.length) throw new Error("sample catalog is empty");
      setSampleCatalog(datasets);
      setSelectedSampleId(datasets[0].id);
      setSelectedSampleQuestionId(datasets[0].questions[0].id);
    } catch (error) {
      console.error("load sample catalog failed", error);
      toast({
        description:
          uiLanguage === "zh" ? "示例数据目录加载失败" : "Failed to load sample catalog",
        variant: "destructive",
      });
    } finally {
      setIsSampleCatalogLoading(false);
    }
  };

  const loadSampleData = async () => {
    if (!sessionId || isLoadingSample) return;
    const selection = findSampleSelection(
      sampleCatalog,
      selectedSampleId,
      selectedSampleQuestionId
    ) as { dataset: SampleDataset; question: SampleQuestion } | null;
    if (!selection) return;

    setIsLoadingSample(true);
    try {
      const response = await fetch(
        buildApiUrlWithParams(API_CONFIG.ENDPOINTS.WORKSPACE_SAMPLE, {
          session_id: sessionId,
          sample_id: selection.dataset.id,
          clear_existing: true,
        }),
        { method: "POST" }
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = await response.json();
      const files = Array.isArray(data.files) ? (data.files as WorkspaceFile[]) : [];
      if (!files.length) throw new Error("sample response has no files");
      setAttachments([]);
      setUploadMsg("");
      setSelectedAnalysisFiles(new Set(files.map((file) => file.path)));
      fileSelectionInitializedRef.current = true;
      discardPendingContinuation();
      setInputValue(selection.question.prompt[uiLanguage]);
      setSelectedWorkspacePath(files[0].path);
      await Promise.all([loadWorkspaceFiles(), loadWorkspaceTree()]);
      await openPreview(files[0]);
      setIsSampleDialogOpen(false);
      toast({
        description:
          uiLanguage === "zh"
            ? `已加载“${selection.dataset.title.zh}”并填入问题`
            : `Loaded “${selection.dataset.title.en}” and filled in the question`,
      });
    } catch (error) {
      console.error("load sample data failed", error);
      toast({
        description:
          uiLanguage === "zh" ? "示例数据加载失败" : "Failed to load sample data",
        variant: "destructive",
      });
    } finally {
      setIsLoadingSample(false);
    }
  };

  useEffect(() => {
    if (isPreviewOpen && !previewLoading && previewScrollRef.current) {
      previewScrollRef.current.scrollTop = 0;
    }
  }, [isPreviewOpen, previewLoading, previewType, previewContent]);

  const handleDownload = async () => {
    try {
      if (previewType === "text" && typeof previewContent === "string") {
        const blob = new Blob([previewContent], {
          type: "text/plain;charset=utf-8",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = previewTitle || "file.txt";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        return;
      }

      const target = resolveWorkspaceFileUrl(previewDownloadUrl || previewContent, {
        download: true,
      });
      if (!target) {
        throw new Error("download failed");
      }
      const a = document.createElement("a");
      a.href = target;
      a.download = previewTitle || "download";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      const url = resolveWorkspaceFileUrl(previewDownloadUrl || previewContent, {
        download: true,
      });
      window.open(url, "_blank");
    }
  };

  const downloadFileByUrl = async (fileName: string, rawUrl: string) => {
    try {
      const target = resolveWorkspaceFileUrl(rawUrl, { download: true });
      if (!target) {
        throw new Error("download failed");
      }
      const a = document.createElement("a");
      a.href = target;
      a.download = fileName || "download";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      const fallbackUrl = resolveWorkspaceFileUrl(rawUrl, { download: true });
      window.open(fallbackUrl, "_blank");
    }
  };

  const buildExportMessages = () =>
    messages
      .filter((message) => !message.localOnly)
      .map((message) => ({
        role: message.sender === "user" ? "user" : "assistant",
        content: message.content,
        timestamp:
          message.timestamp instanceof Date
            ? message.timestamp.toISOString()
            : new Date(message.timestamp).toISOString(),
        attachments: (message.attachments || []).map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          size: attachment.size,
          type: attachment.type,
          url: attachment.url,
        })),
      }));

  const pickExportedFile = (
    payload: ExportResponsePayload,
    format: "md" | "pdf"
  ): ExportedFileMeta | null => {
    const exact = payload.files?.[format];
    if (exact?.download_url) {
      return exact;
    }
    const name = payload[format];
    const downloadUrl = payload.download_urls?.[format];
    if (name && downloadUrl) {
      return {
        name,
        path: "",
        download_url: downloadUrl,
      };
    }
    return null;
  };

  const requestExport = async (
    endpoint: string,
    payload: Record<string, unknown>
  ) => {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const errorPayload = await response.json();
        if (typeof errorPayload?.detail === "string" && errorPayload.detail.trim()) {
          detail = errorPayload.detail.trim();
        } else if (
          typeof errorPayload?.message === "string" &&
          errorPayload.message.trim()
        ) {
          detail = errorPayload.message.trim();
        }
      } catch {
        // ignore parse failures and keep fallback detail
      }
      throw new Error(detail);
    }
    return (await response.json()) as ExportResponsePayload;
  };

  const handleReportExport = async (
    format: "md" | "pdf" = "pdf",
    options?: { download?: boolean }
  ) => {
    const isPdfRequest = format === "pdf";
    setExportingFormat(format);
    if (isPdfRequest) {
      toast({
        description: textLabels.exportPdfPending,
      });
    }
    try {
      void buildReportFilename(getPrevUserQuestionText(messages.length));
      const payload = {
        messages: buildExportMessages(),
        title: getPrevUserQuestionText(messages.length),
        session_id: sessionId,
      };
      const data = await requestExport(API_URLS.EXPORT_REPORT, payload);
      const pdfStatus = data.pdf_status || (data.files?.pdf ? "ok" : null);
      const pdfError = (data.pdf_error || "").trim();
      const withPdfErrorDetail = (base: string) =>
        isPdfRequest && pdfError ? `${base} (${pdfError})` : base;
      const preferredFile =
        pickExportedFile(data, format) ||
        (format === "pdf"
          ? pickExportedFile(data, "md")
          : pickExportedFile(data, "pdf"));

      if (!preferredFile?.download_url) {
        if (isPdfRequest && pdfStatus === "missing_compiler") {
          throw new Error(withPdfErrorDetail(textLabels.exportCompilerMissing));
        }
        if (isPdfRequest && pdfStatus === "missing_dependency") {
          throw new Error(withPdfErrorDetail(textLabels.exportDependencyMissing));
        }
        throw new Error(pdfError || "missing exported report");
      }

      const resolvedFormat = preferredFile.name.toLowerCase().endsWith(".pdf")
        ? "pdf"
        : "md";
      const hasPdfCompilerIssue =
        isPdfRequest &&
        (pdfStatus === "missing_compiler" || pdfStatus === "missing_dependency");

      await loadWorkspaceFiles();
      await loadWorkspaceTree();

      if (!hasPdfCompilerIssue && options?.download !== false) {
        await downloadFileByUrl(preferredFile.name, preferredFile.download_url);
      }

      if (isPdfRequest && pdfStatus === "missing_compiler") {
        toast({
          description: withPdfErrorDetail(
            resolvedFormat === "md"
              ? textLabels.exportCompilerMissingFallback
              : textLabels.exportCompilerMissing
          ),
          variant: "destructive",
        });
        return;
      }

      if (isPdfRequest && pdfStatus === "missing_dependency") {
        toast({
          description: withPdfErrorDetail(
            resolvedFormat === "md"
              ? textLabels.exportDependencyMissingFallback
              : textLabels.exportDependencyMissing
          ),
          variant: "destructive",
        });
        return;
      }

      toast({
        description:
          uiLanguage === "zh"
            ? resolvedFormat !== format
              ? `PDF 不可用，已导出 ${preferredFile.name}`
              : `已导出报告：${preferredFile.name}`
            : resolvedFormat !== format
              ? `PDF is unavailable. Exported ${preferredFile.name} instead.`
              : `Report exported: ${preferredFile.name}`,
      });
    } catch (error) {
      console.error("report export error", error);
      const detail =
        error instanceof Error && error.message.trim()
          ? error.message.trim()
          : textLabels.exportFailed;
      toast({
        description: detail,
        variant: "destructive",
      });
    } finally {
      setExportingFormat(null);
    }
  };

  useEffect(() => {
    exportReportBackendRef.current = async () => {
      await handleReportExport("pdf");
    };
  }, [handleReportExport]);

  const activePreviewFile = useMemo(() => {
    if (!selectedWorkspacePath) return null;
    return (
      workspaceFiles.find((file) => file.path === selectedWorkspacePath) || null
    );
  }, [selectedWorkspacePath, workspaceFiles]);

  const previewedPathRef = useRef("");
  const previewedVersionRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!activePreviewFile || !selectedWorkspacePath) return;
    const version = activePreviewFile.modified_at_ns;
    const changed =
      previewedPathRef.current !== activePreviewFile.path ||
      previewedVersionRef.current !== version;
    if (!changed) return;
    previewedPathRef.current = activePreviewFile.path;
    previewedVersionRef.current = version;
    if (previewTitle === activePreviewFile.name) {
      void loadPreview(activePreviewFile, {
        openModal: isPreviewOpen,
        page: previewPage,
        tableName: previewTableName,
        sheetName: previewSheetName,
      });
    }
  }, [
    activePreviewFile,
    isPreviewOpen,
    loadPreview,
    previewPage,
    previewSheetName,
    previewTableName,
    previewTitle,
    selectedWorkspacePath,
  ]);


  const handlePreviewPageChange = useCallback(
    async (nextPage: number) => {
      if (!activePreviewFile) return;
      await loadPreview(activePreviewFile, {
        page: nextPage,
        tableName: previewTableName,
        sheetName: previewSheetName,
        openModal: isPreviewOpen,
      });
    },
    [activePreviewFile, isPreviewOpen, loadPreview, previewSheetName, previewTableName]
  );

  const handlePreviewTableSelect = useCallback(
    async (tableName: string) => {
      if (!activePreviewFile) return;
      await loadPreview(activePreviewFile, {
        page: 1,
        tableName,
        sheetName: "",
        openModal: isPreviewOpen,
      });
    },
    [activePreviewFile, isPreviewOpen, loadPreview]
  );

  const handlePreviewBackToTables = useCallback(async () => {
    if (!activePreviewFile) return;
    await loadPreview(activePreviewFile, {
      page: 1,
      tableName: "",
      sheetName: "",
      openModal: isPreviewOpen,
    });
  }, [activePreviewFile, isPreviewOpen, loadPreview]);

  const handlePreviewSheetChange = useCallback(
    async (sheetName: string) => {
      if (!activePreviewFile) return;
      await loadPreview(activePreviewFile, {
        page: 1,
        tableName: "",
        sheetName,
        openModal: isPreviewOpen,
      });
    },
    [activePreviewFile, isPreviewOpen, loadPreview]
  );

  const recentGeneratedFiles = useMemo(
    () =>
      dedupeGeneratedDisplayFiles(
        rightPanelSourceFiles
          .filter(
            (file) =>
              isGeneratedWorkspaceFile(file) && !isPythonWorkspaceFile(file)
          )
          .sort((left, right) => right.name.localeCompare(left.name))
      ).slice(0, 8),
    [dedupeGeneratedDisplayFiles, isGeneratedWorkspaceFile, rightPanelSourceFiles]
  );

  const updateActiveSectionFromScroll = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const sections = container.querySelectorAll<HTMLElement>("[data-section-key]");
    const viewportTop = container.scrollTop;
    const viewportBottom = viewportTop + container.clientHeight;
    const containerMiddle = viewportTop + container.clientHeight / 2;

    let closestSection = "";
    let closestDistance = Infinity;

    sections.forEach((section) => {
      const sectionTop = section.offsetTop;
      const sectionBottom = sectionTop + section.offsetHeight;
      if (sectionBottom < viewportTop || sectionTop > viewportBottom) {
        return;
      }
      const sectionMiddle = sectionTop + section.offsetHeight / 2;
      const distance = Math.abs(sectionMiddle - containerMiddle);

      // 找到离容器中心最近的 section
      if (distance < closestDistance) {
        closestDistance = distance;
        closestSection = section.getAttribute("data-section-key") || "";
      }
    });

    if (closestSection) {
      setActiveSection(closestSection);
    }
  }, []);

  // 监听滚动，更新当前激活的步骤（避免 messages 更新时反复解绑/绑定 scroll 事件）
  const activeSectionRafRef = useRef<number | null>(null);
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const onScroll = () => {
      // 只有用户当前在底部时才自动跟随输出
      const distanceToBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      stickToBottomRef.current = distanceToBottom <= SCROLL_BOTTOM_THRESHOLD_PX;

      if (activeSectionRafRef.current) return;
      activeSectionRafRef.current = window.requestAnimationFrame(() => {
        activeSectionRafRef.current = null;
        const now = performance.now();
        if (
          now - lastActiveSectionUpdateAtRef.current <
          ACTIVE_SECTION_UPDATE_INTERVAL_MS
        ) {
          return;
        }
        lastActiveSectionUpdateAtRef.current = now;
        updateActiveSectionFromScroll();
      });
    };

    onScroll(); // 初始化
    container.addEventListener("scroll", onScroll);
    return () => {
      container.removeEventListener("scroll", onScroll);
      if (activeSectionRafRef.current) {
        window.cancelAnimationFrame(activeSectionRafRef.current);
        activeSectionRafRef.current = null;
      }
    };
  }, [updateActiveSectionFromScroll]);

  // 新消息追加/清空时刷新一次 active section（不在流式内容每次变化时都跑）
  useEffect(() => {
    if (!messagesContainerRef.current) return;
    window.requestAnimationFrame(() => updateActiveSectionFromScroll());
  }, [messages.length, updateActiveSectionFromScroll]);

  // 流式阶段的轻量渲染：支持 <Analyze>/<Code> 等块，但避免高开销的 Markdown/高亮解析
  const parseMessageIndexFromSectionKey = useCallback((sectionKey: string) => {
    const match = sectionKey.match(/^msg(\d+)-/);
    if (!match) return null;
    const parsed = Number.parseInt(match[1], 10);
    return Number.isFinite(parsed) ? parsed : null;
  }, []);

  const touchMessageAt = useCallback((messageIndex?: number | null) => {
    if (messageIndex === undefined || messageIndex === null) return;
    setMessages((prev) => {
      if (messageIndex < 0 || messageIndex >= prev.length) return prev;
      const next = [...prev];
      next[messageIndex] = { ...next[messageIndex] };
      return next;
    });
  }, []);

  const buildSectionKey = useCallback(
    (type: StructuredSectionType, position: number, messageIndex?: number) => {
      const suffix = `${type}-pos${position}`;
      return messageIndex !== undefined ? `msg${messageIndex}-${suffix}` : suffix;
    },
    []
  );

  const renderMarkdownContent = useCallback((
    content: string,
    options?: { withinSection?: boolean }
  ) => {
    const withinSection = options?.withinSection ?? false;
    // 鍏堝鐞嗕唬鐮佸潡锛屽皢鍏跺垎绂诲嚭鏉?
    const parts = content.split(/(```[\w]*\n[\s\S]*?```)/g);

    return (
      <div className="prose prose-sm max-w-none dark:prose-invert break-words [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5">
        {parts.map((part, index) => {
          // 妫€鏌ユ槸鍚︽槸浠ｇ爜鍧?
          const codeBlockMatch = part.match(/```(\w+)?\n([\s\S]*?)```/);
          if (codeBlockMatch) {
            const [, language, code] = codeBlockMatch;
            return (
              <CodeBlockView
                key={index}
                language={language || "python"}
                code={code}
                showHeader={!withinSection}
                isDarkMode={isDarkMode}
                onEdit={(c) => {
                  setCodeEditorContent(c);
                  setCodeEditorOriginalCode(c);
                  setAppliedCodeEdit(null);
                  setSelectedCodeSection(c);
                  setShowCodeEditor(true);
                }}
              />
            );
          }

          // 澶勭悊鏅€?markdown 鍐呭
          if (part.trim()) {
            return (
              <ReactMarkdown
                key={index}
                remarkPlugins={[remarkGfm]}
                components={{
                  code: ({ children, ...props }: any) => (
                    <code
                      className="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded text-sm font-mono"
                      {...props}
                    >
                      {children}
                    </code>
                  ),
                  h1: ({ children }) => (
                    <h1 className="text-2xl font-bold mt-4 mb-2">{children}</h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-xl font-semibold mt-4 mb-2">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-lg font-semibold mt-4 mb-2">
                      {children}
                    </h3>
                  ),
                  a: ({ href, children }) => {
                    const resolved = resolveWorkspaceFileUrl(String(href || ""), {
                      download: true,
                    });
                    return (
                      <a
                        href={resolved}
                        className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {children}
                      </a>
                    );
                  },
                  img: ({ src, alt }: any) => {
                    const resolvedSrc = resolveWorkspaceFileUrl(src || "", {
                      download: false,
                    });
                    return (
                      <img
                        src={resolvedSrc}
                        alt={alt || ""}
                        className="max-w-full h-auto rounded-lg my-2"
                      />
                    );
                  },
                  ol: ({ children }) => (
                    <ol className="list-decimal pl-5 space-y-1">{children}</ol>
                  ),
                  ul: ({ children }) => (
                    <ul className="list-disc pl-5 space-y-1">{children}</ul>
                  ),
                }}
              >
                {part}
              </ReactMarkdown>
            );
          }

          return null;
        })}
      </div>
    );
  }, [isDarkMode, resolveWorkspaceFileUrl]);

  const renderSectionContent = useCallback(
    (content: string) => {
      return renderMarkdownContent(content, { withinSection: true });
    },
    [renderMarkdownContent]
  );

  const renderMessageWithSectionsStreaming = useCallback(
    (content: string, messageIndex?: number) => {
      const sectionTypes = [
        "Analyze",
        "Understand",
        "Code",
        "Execute",
        "Answer",
        "File",
      ] as const;
      const sectionConfigs: Record<
        (typeof sectionTypes)[number],
        { icon: string; color: string }
      > = {
        Analyze: {
          icon: "🔍",
          color:
            "bg-blue-50 border-blue-200 dark:bg-blue-950/30 dark:border-blue-800",
        },
        Understand: {
          icon: "🧠",
          color:
            "bg-cyan-50 border-cyan-200 dark:bg-cyan-950/30 dark:border-cyan-800",
        },
        Code: {
          icon: "💻",
          color:
            "bg-gray-50 border-gray-200 dark:bg-gray-950/30 dark:border-gray-700",
        },
        Execute: {
          icon: "⚡",
          color:
            "bg-orange-50 border-orange-200 dark:bg-orange-950/30 dark:border-orange-800",
        },
        Answer: {
          icon: "✅",
          color:
            "bg-green-50 border-green-200 dark:bg-green-950/30 dark:border-green-800",
        },
        File: {
          icon: "📎",
          color:
            "bg-purple-50 border-purple-200 dark:bg-purple-950/30 dark:border-purple-800",
        },
      };

      // 没有结构化标签时，保持最轻量文本渲染（避免每个 chunk 都触发 Markdown/高亮重解析）
      if (!content.includes("<")) {
        return (
          <div className="text-sm break-words whitespace-pre-wrap">
            {content}
          </div>
        );
      }

      const parts: React.ReactNode[] = [];
      const openRe = /<(Analyze|Understand|Code|Execute|Answer|File)>/g;
      let cursor = 0;
      let m: RegExpExecArray | null;

      while ((m = openRe.exec(content)) !== null) {
        const type = m[1] as StructuredSectionType;
        const start = m.index;

        if (start > cursor) {
          const before = content.slice(cursor, start);
          parts.push(
            <StreamingMarkdownBlock
              key={`stream-md-${cursor}`}
              className="markdown-content mb-2"
              content={before}
              renderMarkdownContent={renderMarkdownContent}
            />
          );
        }

        const openTag = m[0];
        const openEnd = start + openTag.length;
        const closeTag = `</${type}>`;
        const closeIdx = content.indexOf(closeTag, openEnd);
        const isComplete = closeIdx !== -1;
        const bodyEnd = isComplete ? closeIdx : content.length;
        const body = content.slice(openEnd, bodyEnd).trim();

        const sectionKey = buildSectionKey(type, start, messageIndex);
        const collapseState = collapsedSectionsRef.current;
        const isCollapsed = autoCollapseEnabled
          ? !!(collapseState as any)[sectionKey]
          : !!manualLocks[sectionKey] && !!(collapseState as any)[sectionKey];

        const toggleSection = () => {
          setCollapsedSections((prev) => {
            const next = { ...prev } as Record<string, boolean>;
            const current = !!(prev as any)[sectionKey];
            next[sectionKey] = !current;
            return next;
          });
          setManualLocks((prev) => ({ ...prev, [sectionKey]: true }));
          touchMessageAt(messageIndex);
        };

        parts.push(
          <div
            key={`stream-section-${sectionKey}`}
            className={`mb-4 border rounded-lg overflow-hidden ${sectionConfigs[type].color}`}
            data-section={type}
            data-section-key={sectionKey}
            style={{
              contentVisibility: "auto",
              containIntrinsicSize: isCollapsed ? "56px" : "220px",
            }}
          >
            <div className="flex items-center justify-between px-3 py-2 bg-white/60 dark:bg-black/30 border-b border-black/5 dark:border-white/10">
              <div className="flex items-center gap-2 min-w-0">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={toggleSection}
                  className="h-5 w-5 p-0 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                >
                  {isCollapsed ? (
                    <ChevronRight className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                </Button>
                <span className="text-sm">{sectionConfigs[type].icon}</span>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {type}
                </span>
                {!isComplete && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {textLabels.sectionGenerating}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                {type === "Answer" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      if (isTypingRef.current) {
                        toastRef.current({
                          description: textLabels.exportBlockedWhileStreaming,
                          variant: "destructive",
                        });
                        return;
                      }
                      await exportReportBackendRef.current();
                    }}
                    className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    title={textLabels.exportActionTitle}
                  >
                    <Download className="h-3 w-3" />
                  </Button>
                )}
                {(type === "Code" ||
                  type === "Analyze" ||
                  type === "Understand") && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        const text =
                          type === "Code" ? extractCode(body || "") : body || "";
                        const ok = await copyToClipboard(text.trim());
                        toastRef.current({
                          description: ok ? "已复制" : "复制失败",
                          variant: ok ? undefined : "destructive",
                        });
                      }}
                      className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                    {type === "Code" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          const code = extractCode(body || "");
                          setCodeEditorContent(code);
                          setCodeEditorOriginalCode(code);
                          setAppliedCodeEdit(null);
                          setSelectedCodeSection(body || "");
                          setShowCodeEditor(true);
                        }}
                        className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                      >
                        <Edit className="h-3 w-3" />
                      </Button>
                    )}
                  </>
                )}
                {type === "Execute" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      const executionOutput = extractCode(body || "");
                      const textToCopy = executionOutput || body || "";
                      if (textToCopy.trim()) {
                        const ok = await copyToClipboard(textToCopy.trim());
                        toastRef.current({
                          description: ok ? "已复制" : "复制失败",
                          variant: ok ? undefined : "destructive",
                        });
                      }
                    }}
                    className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    title={uiLanguage === "zh" ? "复制 Execute 输出" : "Copy Execute Output"}
                  >
                    <Copy className="h-3 w-3" />
                  </Button>
                )}
              </div>
            </div>
            {!isCollapsed && (
              <StreamingSectionViewport
                enabled={fixedStreamingSectionHeightEnabled}
              >
                <StreamingSectionBody
                  type={type}
                  content={body}
                  isComplete={isComplete}
                  renderSectionContent={renderSectionContent}
                />
              </StreamingSectionViewport>
            )}
          </div>
        );

        cursor = isComplete ? closeIdx + closeTag.length : content.length;
        openRe.lastIndex = cursor;

        if (!isComplete) break;
      }

      if (cursor < content.length) {
        const after = content.slice(cursor);
        if (after.trim()) {
          parts.push(
            <div key="stream-text-end" className="text-sm break-words whitespace-pre-wrap">
              {after}
            </div>
          );
        }
      }

      if (parts.length === 0) {
        return (
          <div className="text-sm break-words whitespace-pre-wrap">
            {content}
          </div>
        );
      }

      return <>{parts}</>;
    },
    [
      autoCollapseEnabled,
      buildSectionKey,
      fixedStreamingSectionHeightEnabled,
      manualLocks,
      renderMarkdownContent,
      renderSectionContent,
      textLabels.exportActionTitle,
      textLabels.exportBlockedWhileStreaming,
      textLabels.sectionGenerating,
      touchMessageAt,
      uiLanguage,
    ]
  );

  const renderMessageWithSections = useCallback((
    content: string,
    messageIndex?: number
  ) => {
    const sectionConfigs = {
      Analyze: {
        icon: "🔍",
        color:
          "bg-blue-50 border-blue-200 dark:bg-blue-950/30 dark:border-blue-800",
      },
      Understand: {
        icon: "🧠",
        color:
          "bg-cyan-50 border-cyan-200 dark:bg-cyan-950/30 dark:border-cyan-800",
      },
      Code: {
        icon: "💻",
        color:
          "bg-gray-50 border-gray-200 dark:bg-gray-950/30 dark:border-gray-700",
      },
      Execute: {
        icon: "⚡",
        color:
          "bg-orange-50 border-orange-200 dark:bg-orange-950/30 dark:border-orange-800",
      },
      Answer: {
        icon: "✅",
        color:
          "bg-green-50 border-green-200 dark:bg-green-950/30 dark:border-green-800",
      },
      File: {
        icon: "📎",
        color:
          "bg-purple-50 border-purple-200 dark:bg-purple-950/30 dark:border-purple-800",
      },
    };

    // 首先分割内容，找出所有标签
    const allMatches: Array<{
      type: keyof typeof sectionConfigs;
      content: string;
      position: number;
      fullMatch: string;
    }> = [];

    Object.keys(sectionConfigs).forEach((type) => {
      // 使用 [\s\S]*? 以兼容不支持 s 标志的环境
      const regex = new RegExp(`<${type}>([\\s\\S]*?)</${type}>`, "g");
      let match;

      while ((match = regex.exec(content)) !== null) {
        allMatches.push({
          type: type as keyof typeof sectionConfigs,
          content: match[1].trim(),
          position: match.index,
          fullMatch: match[0],
        });
      }
    });

    // 如果没有找到结构化标签，渲染为 Markdown
    if (allMatches.length === 0) {
      return (
        <div className="markdown-content">{renderMarkdownContent(content)}</div>
      );
    }

    // 按位置排序
    allMatches.sort((a, b) => a.position - b.position);

    const parts = [];
    let lastPosition = 0;

    allMatches.forEach((match, index) => {
      // 添加标签前的普通文本
      if (match.position > lastPosition) {
        const beforeText = content.slice(lastPosition, match.position);
        if (beforeText.trim()) {
          parts.push(
            <div key={`text-${index}`} className="markdown-content mb-2">
              {renderMarkdownContent(beforeText)}
            </div>
          );
        }
      }

      // 添加结构化标签
      const config = sectionConfigs[match.type];
      const sectionKey = buildSectionKey(
        match.type as StructuredSectionType,
        match.position,
        messageIndex
      );
      const collapseState = collapsedSectionsRef.current;
      const isCollapsed = autoCollapseEnabled
        ? !!(collapseState as any)[sectionKey]
        : !!manualLocks[sectionKey] && !!(collapseState as any)[sectionKey];

      const toggleSection = () => {
        setCollapsedSections((prev) => {
          const next = { ...prev } as Record<string, boolean>;
          const current = !!(prev as any)[sectionKey];
          next[sectionKey] = !current;
          return next;
        });
        setManualLocks((prev) => ({
          ...prev,
          [sectionKey]: true,
        }));
        touchMessageAt(messageIndex);
      };

      // 如果是 File 标签，解析其中的链接为卡片
      let sectionBody = match.content;
      let fileGallery: JSX.Element | null = null;
      if (match.type === "File") {
        sectionBody = filterPythonFileLinks(match.content);
        const files = parseGeneratedFiles(sectionBody);
        if (files.length) {
          fileGallery = (
            <div className="mt-3">
              <div className="text-xs text-gray-500 mb-2">{textLabels.relatedFiles}</div>
              <div className="grid grid-cols-2 gap-2">
                {files.map((f, i) => {
                  const resolvedUrl = resolveWorkspaceFileUrl(f.url, {
                    download: false,
                  });
                  return (
                    <div
                      key={i}
                      className="border border-gray-200 dark:border-gray-700 rounded overflow-hidden bg-white dark:bg-black"
                    >
                      {f.isImage ? (
                        <a href={resolvedUrl} target="_blank" rel="noreferrer">
                          <img
                            src={resolvedUrl}
                            alt={f.name}
                            className="w-full h-28 object-contain bg-white dark:bg-black"
                          />
                        </a>
                      ) : (
                        <a
                          href={resolvedUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="block p-2 text-xs truncate hover:bg-gray-50 dark:hover:bg-gray-900"
                        >
                          {f.name}
                        </a>
                      )}
                      <div className="flex items-center justify-between px-2 py-1 border-t border-gray-200 dark:border-gray-800">
                        <div className="text-[10px] truncate max-w-[70%] text-gray-500">
                          {f.name}
                        </div>
                        <a
                          href={resolvedUrl}
                          download
                          className="text-[10px] text-blue-600 hover:underline"
                        >
                          下载
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        }
      }

      if (match.type === "File" && !sectionBody && !fileGallery) {
        lastPosition = match.position + match.fullMatch.length;
        return;
      }

      parts.push(
        <div
          key={`section-${sectionKey}`}
          className={`mb-4 border rounded-lg overflow-hidden ${config.color}`}
          data-section={match.type}
          data-section-key={sectionKey}
          style={{
            contentVisibility: "auto",
            containIntrinsicSize: isCollapsed ? "56px" : "240px",
          }}
        >
          <div className="flex items-center justify-between px-3 py-2 bg-white/60 dark:bg-black/30 border-b border-black/5 dark:border-white/10">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleSection}
                className="h-5 w-5 p-0 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
              </Button>
              <span className="text-sm">{config.icon}</span>
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                {match.type}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {match.type === "Answer" && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    if (isTypingRef.current) {
                      toastRef.current({
                        description: textLabels.exportBlockedWhileStreaming,
                        variant: "destructive",
                      });
                      return;
                    }
                    await exportReportBackendRef.current();
                  }}
                  className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                  title={textLabels.exportActionTitle}
                >
                  <Download className="h-3 w-3" />
                </Button>
              )}
              {(match.type === "Code" ||
                match.type === "Analyze" ||
                match.type === "Understand") && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        const text =
                          match.type === "Code"
                            ? extractCode(match.content)
                            : match.content;
                        const ok = await copyToClipboard(text.trim());
                        toastRef.current({
                          description: ok ? "已复制" : "复制失败",
                          variant: ok ? undefined : "destructive",
                        });
                      }}
                      className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                    {match.type === "Code" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          const code = extractCode(match.content);
                          setCodeEditorContent(code);
                          setCodeEditorOriginalCode(code);
                          setAppliedCodeEdit(null);
                          setSelectedCodeSection(match.content);
                          setShowCodeEditor(true);
                        }}
                        className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                      >
                        <Edit className="h-3 w-3" />
                      </Button>
                    )}
                  </>
                )}
              {match.type === "Execute" && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      const executionOutput = extractCode(
                        sectionBody || match.content || ""
                      );
                      const textToCopy = executionOutput || sectionBody || "";
                        if (textToCopy.trim()) {
                          const ok = await copyToClipboard(textToCopy.trim());
                          toastRef.current({
                          description: ok ? "已复制" : "复制失败",
                          variant: ok ? undefined : "destructive",
                        });
                      }
                    }}
                    className="h-5 px-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    title="复制此 Execute 的输出"
                  >
                    <Copy className="h-3 w-3" />
                  </Button>
                </>
              )}
            </div>
          </div>
          {!isCollapsed && (
            <StreamingSectionViewport
              enabled={fixedStreamingSectionHeightEnabled}
              bodyClassName={match.type === "Answer" ? "answer-body" : ""}
            >
              {match.type === "Code"
                ? renderSectionContent(buildCodeFenceForSection(sectionBody))
                : renderSectionContent(sectionBody)}
              {fileGallery}
            </StreamingSectionViewport>
          )}
        </div>
      );

      lastPosition = match.position + match.fullMatch.length;
    });

    // 添加最后剩余的文本
    if (lastPosition < content.length) {
      const afterText = content.slice(lastPosition);
      if (afterText.trim()) {
        parts.push(
          <div key="text-end" className="markdown-content mt-2">
            {renderMarkdownContent(afterText)}
          </div>
        );
      }
    }

    return <>{parts}</>;
  }, [autoCollapseEnabled, buildSectionKey, fixedStreamingSectionHeightEnabled, manualLocks, renderMarkdownContent, renderSectionContent, textLabels.exportActionTitle, textLabels.exportBlockedWhileStreaming, textLabels.relatedFiles, touchMessageAt]);

  // 根据完整内容自动折叠：除最后一个块外全部折叠
  const autoCollapseForContent = useCallback(
    (content: string, messageIndex?: number) => {
      if (!autoCollapseEnabled) return;
      const sectionTypes = [
        "Analyze",
        "Understand",
        "Code",
        "Execute",
        "File",
        "Answer",
      ] as const;
      const matches: Array<{ type: StructuredSectionType; pos: number }> = [];
      sectionTypes.forEach((t) => {
        const re = new RegExp(`<${t}>([\\s\\S]*?)</${t}>`, "g");
        let m: RegExpExecArray | null;
        while ((m = re.exec(content)) !== null) {
          matches.push({ type: t, pos: m.index });
        }
      });
      if (matches.length === 0) return;
      matches.sort((a, b) => a.pos - b.pos);
      const next: Record<string, boolean> = {};
      matches.forEach((m, i) => {
        const key = buildSectionKey(m.type, m.pos, messageIndex);
        next[key] = i !== matches.length - 1; // 最后一个不折叠
      });
      setCollapsedSections((prev) => {
        const merged: Record<string, boolean> = { ...prev };
        // 只在未手动锁定的 key 上更新，保留用户手动状态
        for (const key in next) {
          if (!manualLocks[key]) merged[key] = next[key];
        }
        return merged;
      });
    },
    [autoCollapseEnabled, buildSectionKey, manualLocks]
  );


  const renderPreviewTable = useCallback(
    (
      payload: {
        columns?: string[];
        rows?: Array<Array<string | number | boolean>>;
        truncated?: boolean;
        row_count?: number;
        title?: string;
        sheet_name?: string;
        sheet_names?: string[];
        total_rows?: number;
        page?: number;
        total_pages?: number;
      },
      options?: { compact?: boolean }
    ) => {
      const compact = options?.compact ?? false;
      const columns = payload.columns || [];
      const rows = compact ? (payload.rows || []).slice(0, 5) : payload.rows || [];
      return (
        <div className="space-y-2">
          {(payload.title || payload.sheet_name) && (
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {payload.title}
                {payload.sheet_name ? ` · ${payload.sheet_name}` : ""}
              </div>
              {!compact && payload.sheet_names && payload.sheet_names.length > 1 && (
                <Select
                  value={payload.sheet_name}
                  onValueChange={handlePreviewSheetChange}
                >
                  <SelectTrigger className="h-8 w-40 rounded-lg text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {payload.sheet_names.map((sheet) => (
                      <SelectItem key={sheet} value={sheet}>
                        {sheet}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}
          <div className="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  {columns.map((column) => (
                    <TableHead key={column}>{column}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length ? (
                  rows.map((row, rowIndex) => (
                    <TableRow key={`${payload.title || "row"}-${rowIndex}`}>
                      {row.map((cell, cellIndex) => (
                        <TableCell
                          key={`${payload.title || "cell"}-${rowIndex}-${cellIndex}`}
                          className="max-w-56 truncate"
                          title={String(cell ?? "")}
                        >
                          {String(cell ?? "")}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={Math.max(columns.length, 1)}
                      className="text-center text-gray-500"
                    >
                      {uiLanguage === "zh" ? "暂无数据" : "No rows"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {(payload.truncated || payload.row_count || payload.total_rows) && (
            <div className="text-[11px] text-gray-500 dark:text-gray-400">
              {uiLanguage === "zh"
                ? `显示 ${rows.length} 行${payload.total_rows || payload.row_count ? ` / 共 ${payload.total_rows || payload.row_count} 行` : ""}`
                : `Showing ${rows.length} row(s)${payload.total_rows || payload.row_count ? ` / ${payload.total_rows || payload.row_count} total` : ""}`}
            </div>
          )}
          {!compact && (payload.total_pages || 1) > 1 && (
            <div className="flex items-center justify-between gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                className="rounded-full"
                disabled={(payload.page || 1) <= 1}
                onClick={() => handlePreviewPageChange((payload.page || 1) - 1)}
              >
                {uiLanguage === "zh" ? "上一页" : "Prev"}
              </Button>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {uiLanguage === "zh"
                  ? `第 ${payload.page || 1} / ${payload.total_pages || 1} 页`
                  : `Page ${payload.page || 1} / ${payload.total_pages || 1}`}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="rounded-full"
                disabled={(payload.page || 1) >= (payload.total_pages || 1)}
                onClick={() => handlePreviewPageChange((payload.page || 1) + 1)}
              >
                {uiLanguage === "zh" ? "下一页" : "Next"}
              </Button>
            </div>
          )}
        </div>
      );
    },
    [handlePreviewPageChange, handlePreviewSheetChange, uiLanguage]
  );

  const renderPreviewContent = useCallback(
    (options?: { compact?: boolean }) => {
      const compact = options?.compact ?? false;
      if (previewLoading) {
        return (
          <div className="h-full flex items-center justify-center text-sm text-gray-500">
            {uiLanguage === "zh" ? "加载中..." : "Loading..."}
          </div>
        );
      }

      if (previewType === "image") {
        return (
          <div className={compact ? "" : "p-4 h-full flex items-center justify-center"}>
            <img
              src={previewContent}
              alt={previewTitle}
              className={compact ? "h-48 w-full object-cover" : "max-w-full max-h-full object-contain"}
            />
          </div>
        );
      }

      if (previewType === "pdf") {
        return <iframe src={previewContent} className="w-full h-full min-h-[320px]" />;
      }

      if (previewType === "markdown") {
        return (
          <div className={compact ? "max-h-48 overflow-auto p-3" : "p-4"}>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {compact ? previewContent.slice(0, 1600) : previewContent}
              </ReactMarkdown>
            </div>
          </div>
        );
      }

      if (previewType === "table" && previewPayload) {
        return (
          <div className={compact ? "p-3" : "p-4"}>
            {renderPreviewTable(previewPayload, { compact })}
          </div>
        );
      }

      if (previewType === "database" && previewPayload?.view === "tables") {
        const tables = compact ? (previewPayload.tables || []).slice(0, 5) : previewPayload.tables || [];
        return (
          <div className={compact ? "p-3 space-y-2" : "p-4 space-y-3"}>
            {tables.map((table) => (
              <button
                key={table.table_name || table.title}
                type="button"
                className="flex w-full items-center justify-between rounded-xl border border-gray-200 dark:border-gray-800 px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-900/60"
                onClick={() =>
                  table.table_name && handlePreviewTableSelect(table.table_name)
                }
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                    {table.table_name || table.title}
                  </div>
                  <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                    {uiLanguage === "zh"
                      ? `${table.row_count || 0} 行 · ${table.column_count || 0} 列`
                      : `${table.row_count || 0} rows · ${table.column_count || 0} cols`}
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 text-gray-400" />
              </button>
            ))}
          </div>
        );
      }

      if (previewType === "database" && previewPayload?.view === "table" && previewPayload) {
        return (
          <div className={compact ? "p-3 space-y-3" : "p-4 space-y-4"}>
            {(
              <Button
                variant={compact ? "ghost" : "outline"}
                size="sm"
                className={compact ? "h-8 rounded-full px-2 text-xs" : "rounded-full"}
                onClick={handlePreviewBackToTables}
              >
                <ChevronLeft className="mr-1 h-3.5 w-3.5" />
                {uiLanguage === "zh" ? "返回表列表" : "Back to Tables"}
              </Button>
            )}
            {renderPreviewTable(previewPayload, { compact })}
          </div>
        );
      }

      if (previewType === "text") {
        const previewExtension = (
          previewTitle.split(".").pop() || "text"
        ).toLowerCase();
        const previewLanguage = guessLanguageByExtension(previewExtension);
        if (compact) {
          if (previewLanguage === "json") {
            return (
              <div className="h-48 overflow-hidden p-2">
                <div className="h-full min-h-0 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
                  <Editor
                    height="100%"
                    defaultLanguage="json"
                    language="json"
                    value={previewContent.slice(0, 1200)}
                    theme={isDarkMode ? "vs-dark" : "light"}
                    options={{
                      readOnly: true,
                      wordWrap: "on",
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      fontFamily: "var(--font-mono), 'Courier New', monospace",
                      fontSize: 12,
                      lineNumbers: "off",
                      automaticLayout: true,
                    }}
                  />
                </div>
              </div>
            );
          }
          return (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap p-3 text-xs text-gray-700 dark:text-gray-300">
              {previewContent.slice(0, 1200)}
            </pre>
          );
        }
        return (
          <div className="h-full min-h-0 p-2">
            <div className="h-full min-h-0 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
              <div className="h-full min-h-0">
                <Editor
                  height="100%"
                  defaultLanguage={previewLanguage}
                  language={previewLanguage}
                  value={previewContent}
                  theme={isDarkMode ? "vs-dark" : "light"}
                  options={{
                    readOnly: true,
                    wordWrap: "on",
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    fontFamily: "var(--font-mono), 'Courier New', monospace",
                    fontSize: 14,
                    lineNumbers: "on",
                    automaticLayout: true,
                  }}
                />
              </div>
            </div>
          </div>
        );
      }

      return (
        <div className="p-4">
          <div className="text-xs text-gray-500 mb-2">
            {uiLanguage === "zh"
              ? "暂不支持当前格式的结构化预览，可直接下载查看。"
              : "Structured preview is not available for this file type yet. You can still download it."}
          </div>
          <div className="mt-3 text-xs text-gray-500">
            <a
              className="underline"
              href={previewDownloadUrl || previewContent}
              target="_blank"
              rel="noreferrer"
            >
              {uiLanguage === "zh" ? "点击下载/打开" : "Download / Open"}
            </a>
          </div>
        </div>
      );
    },
    [
      handlePreviewBackToTables,
      handlePreviewTableSelect,
      isDarkMode,
      previewContent,
      previewDownloadUrl,
      previewLoading,
      previewPayload,
      previewTitle,
      previewType,
      renderPreviewTable,
      uiLanguage,
    ]
  );

  const executeCode = async () => {
    setIsExecutingCode(true);
    try {
      const response = await fetch(API_URLS.EXECUTE_CODE, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          code: codeEditorContent,
          session_id: sessionId,
          instruction: appliedCodeEdit?.instruction || "",
          original_code: appliedCodeEdit?.originalCode || codeEditorOriginalCode,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setCodeExecutionResult(data.result);
        if (data.trace_content) {
          setMessages((current) => [
            ...current,
            {
              id: String(data.message_id || `manual-run-${Date.now()}`),
              sender: "ai",
              content: String(data.trace_content),
              timestamp: new Date(),
            },
          ]);
        }
        setCodeEditorOriginalCode(codeEditorContent);
        setAppliedCodeEdit(null);
        await loadWorkspaceFiles();
        await loadWorkspaceTree();
      } else {
        setCodeExecutionResult("Error: Failed to execute code");
      }
    } catch (error) {
      setCodeExecutionResult(`Error: ${error}`);
    } finally {
      setIsExecutingCode(false);
    }
  };

  const validateCodeEditRuntime = () => {
    const trimmedCustomModelName = customModelName.trim();
    if (llmProvider === "heywhale" && !heywhaleApiKey.trim()) {
      toastRef.current({
        description: textLabels.needHeywhaleKey,
        variant: "destructive",
      });
      return null;
    }
    if (llmProvider === "custom" && !trimmedCustomModelName) {
      toastRef.current({
        description: textLabels.needCustomModel,
        variant: "destructive",
      });
      return null;
    }
    if (llmProvider === "custom" && !customApiBase.trim()) {
      toastRef.current({
        description: textLabels.needCustomApiBase,
        variant: "destructive",
      });
      return null;
    }
    return trimmedCustomModelName;
  };

  const handleCodeEditorChange = (value?: string) => {
    setCodeEditorContent(value || "");
    setPendingCodeEdit(null);
  };

  const requestAiCodeEdit = async () => {
    const instruction = codeEditInstruction.trim();
    const trimmedCustomModelName = validateCodeEditRuntime();
    if (trimmedCustomModelName === null) return;
    if (!codeEditorContent.trim()) {
      toastRef.current({
        description:
          uiLanguage === "zh" ? "请先在编辑器中放入代码" : "Add code to the editor first.",
        variant: "destructive",
      });
      return;
    }
    if (!instruction) {
      toastRef.current({
        description:
          uiLanguage === "zh" ? "请输入自然语言修改指令" : "Enter an edit instruction first.",
        variant: "destructive",
      });
      return;
    }

    setIsEditingCodeWithAi(true);
    setPendingCodeEdit(null);
    try {
      const response = await fetch(API_URLS.EDIT_CODE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: codeEditorContent,
          instruction,
          model:
            llmProvider === "custom"
              ? trimmedCustomModelName || DEFAULT_MODEL_NAME
              : DEFAULT_MODEL_NAME,
          provider: llmProvider,
          api_key:
            llmProvider === "heywhale"
              ? heywhaleApiKey.trim()
              : llmProvider === "custom"
                ? customApiKey.trim()
                : "",
          api_base: llmProvider === "custom" ? customApiBase.trim() : "",
          temperature: normalizedTemperature,
          session_id: sessionId,
        }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || `HTTP ${response.status}`);
      }

      const modifiedCode = String(payload?.code || "");
      if (!modifiedCode.trim()) {
        throw new Error("LLM response did not contain modified code");
      }

      setPendingCodeEdit({
        originalCode: codeEditorContent,
        modifiedCode,
        instruction,
        diffRows: buildLineDiff(codeEditorContent, modifiedCode) as CodeDiffRow[],
      });
      toastRef.current({
        description:
          uiLanguage === "zh"
            ? "已生成修改预览，请确认或回滚"
            : "Generated a diff preview. Confirm or roll it back.",
      });
    } catch (error) {
      toastRef.current({
        description:
          uiLanguage === "zh"
            ? `自然语言修改失败：${error}`
            : `AI code edit failed: ${error}`,
        variant: "destructive",
      });
    } finally {
      setIsEditingCodeWithAi(false);
    }
  };

  const confirmAiCodeEdit = () => {
    if (!pendingCodeEdit) return;
    setCodeEditorContent(pendingCodeEdit.modifiedCode);
    setSelectedCodeSection(pendingCodeEdit.modifiedCode);
    setAppliedCodeEdit({
      originalCode: pendingCodeEdit.originalCode,
      instruction: pendingCodeEdit.instruction,
    });
    setPendingCodeEdit(null);
    toastRef.current({
      description: uiLanguage === "zh" ? "修改已应用到编辑器" : "Edit applied to the editor.",
    });
  };

  const rollbackAiCodeEdit = () => {
    setPendingCodeEdit(null);
    toastRef.current({
      description:
        uiLanguage === "zh"
          ? "已回滚 AI 修改预览，编辑器保持原代码"
          : "AI edit preview rolled back. The editor kept the original code.",
    });
  };

  /*
  const renderMarkdownContentLegacy = useCallback((
    content: string,
    options?: { withinSection?: boolean }
  ) => {
    const withinSection = options?.withinSection ?? false;
    // 先处理代码块，将其分离出来
    const parts = content.split(/(```[\w]*\n[\s\S]*?```)/g);

    return (
      <div className="prose prose-sm max-w-none dark:prose-invert break-words [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5">
        {parts.map((part, index) => {
          // 检查是否是代码块
          const codeBlockMatch = part.match(/```(\w+)?\n([\s\S]*?)```/);
          if (codeBlockMatch) {
            const [, language, code] = codeBlockMatch;
            return (
              <CodeBlockView
                key={index}
                language={language || "python"}
                code={code}
                showHeader={!withinSection}
                isDarkMode={isDarkMode}
                onEdit={(c) => {
                  setCodeEditorContent(c);
                  setCodeEditorOriginalCode(c);
                  setAppliedCodeEdit(null);
                  setSelectedCodeSection(c);
                  setShowCodeEditor(true);
                }}
              />
            );
          }

          // 处理普通 markdown 内容
          if (part.trim()) {
            return (
              <ReactMarkdown
                key={index}
                remarkPlugins={[remarkGfm]}
                components={{
                  code: ({ children, ...props }: any) => (
                    <code
                      className="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded text-sm font-mono"
                      {...props}
                    >
                      {children}
                    </code>
                  ),
                  h1: ({ children }) => (
                    <h1 className="text-2xl font-bold mt-4 mb-2">{children}</h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-xl font-semibold mt-4 mb-2">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-lg font-semibold mt-4 mb-2">
                      {children}
                    </h3>
                  ),
                  a: ({ href, children }) => {
                    const resolved = resolveWorkspaceFileUrl(String(href || ""), {
                      download: true,
                    });
                    return (
                      <a
                        href={resolved}
                        className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {children}
                      </a>
                    );
                  },
                  img: ({ src, alt }: any) => {
                    const resolvedSrc = resolveWorkspaceFileUrl(src || "", {
                      download: false,
                    });
                    return (
                      <img
                        src={resolvedSrc}
                        alt={alt || ""}
                        className="max-w-full h-auto rounded-lg my-2"
                      />
                    );
                  },
                  ol: ({ children }) => (
                    <ol className="list-decimal pl-5 space-y-1">{children}</ol>
                  ),
                  ul: ({ children }) => (
                    <ul className="list-disc pl-5 space-y-1">{children}</ul>
                  ),
                }}
              >
                {part}
              </ReactMarkdown>
            );
          }

          return null;
        })}
      </div>
    );
  }, [isDarkMode]);

  const renderSectionContentLegacy = useCallback(
    (content: string) => {
      return renderMarkdownContentLegacy(content, { withinSection: true });
    },
    [renderMarkdownContentLegacy]
  );
  */

  // 解析 Markdown 中的文件/图片链接，返回用于卡片渲染的数据
  const parseGeneratedFiles = (
    content: string
  ): Array<{ name: string; url: string; isImage: boolean }> => {
    const result: { name: string; url: string; isImage: boolean }[] = [];
    let m: RegExpExecArray | null;
    // 1) 列表形如: - [name](url)
    const linkRe = /\- \[(.*?)\]\((.*?)\)/g;
    while ((m = linkRe.exec(content)) !== null) {
      const name = m[1];
      const url = normalizeToLocalFileUrl(m[2], { download: false });
      const isImage = isImageAssetUrl(url, name);
      result.push({ name, url, isImage });
    }
    // 2) 图片 Markdown: ![name](url)
    const imgRe = /!\[(.*?)\]\((.*?)\)/g;
    while ((m = imgRe.exec(content)) !== null) {
      const name = m[1];
      const url = normalizeToLocalFileUrl(m[2], { download: false });
      result.push({ name, url, isImage: true });
    }
    // 3) 兜底：文中出现的裸链接
    const urlRe = /(https?:\/\/[^\s)]+)/g;
    while ((m = urlRe.exec(content)) !== null) {
      const url = normalizeToLocalFileUrl(m[1], { download: false });
      const isImage = isImageAssetUrl(url);
      if (isImage)
        result.push({ name: getUrlFileName(url) || "image", url, isImage });
    }
    // 去重同 url
    const seen = new Set<string>();
    return result.filter((f) =>
      seen.has(f.url) ? false : (seen.add(f.url), true)
    );
  };

  // 提取消息中的所有步骤
  const extractSections = (content: string, messageIndex?: number) => {
    const sectionConfigs = {
      Analyze: { icon: "🔍", color: "bg-blue-500" },
      Understand: { icon: "🧠", color: "bg-cyan-500" },
      Code: { icon: "💻", color: "bg-gray-500" },
      Execute: { icon: "⚡", color: "bg-orange-500" },
      Answer: { icon: "✅", color: "bg-green-500" },
      File: { icon: "📎", color: "bg-purple-500" }, // 添加 File 类型
    };

    const allMatches: Array<{
      type: keyof typeof sectionConfigs;
      position: number;
    }> = [];

    Object.keys(sectionConfigs).forEach((type) => {
      const regex = new RegExp(`<${type}>([\\s\\S]*?)</${type}>`, "g");
      let match;

      while ((match = regex.exec(content)) !== null) {
        allMatches.push({
          type: type as keyof typeof sectionConfigs,
          position: match.index,
        });
      }
    });

    // 按位置排序，然后生成 sectionKey（与 renderMessageWithSections 逻辑一致）
    allMatches.sort((a, b) => a.position - b.position);

    return allMatches.map((m) => ({
      type: m.type,
      sectionKey: buildSectionKey(
        m.type as StructuredSectionType,
        m.position,
        messageIndex
      ),
      config: sectionConfigs[m.type],
    }));
  };

  // 滚动到指定步骤
  const scrollToSection = useCallback((sectionKey: string) => {
    const container = messagesContainerRef.current;
    if (!container) {
      console.warn("Container not found");
      return;
    }

    // 展开目标块（如果它是折叠的）
    setCollapsedSections((prev) => {
      const next = { ...prev };
      // 仅处理当前 sectionKey

      // 如果该块是折叠的，则展开它

      if (prev[sectionKey]) {
        next[sectionKey] = false;
        return next;
      }
      return prev;
    });

    // 标记为手动操作，防止自动折叠覆盖
    setManualLocks((prev) => {
      return {
        ...prev,
        [sectionKey]: true,
      };
    });
    touchMessageAt(parseMessageIndexFromSectionKey(sectionKey));

    // 使用延迟确保 DOM 已更新和展开动画完成
    setTimeout(() => {
      const element = document.querySelector(
        `[data-section-key="${sectionKey}"]`
      );

      if (!element) {
        console.warn(`Element with key ${sectionKey} not found`);
        return;
      }

      const elementRect = element.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const scrollTop = container.scrollTop;

      // 计算目标滚动位置（居中显示）
      const targetScroll =
        scrollTop +
        elementRect.top -
        containerRect.top -
        containerRect.height / 2 +
        elementRect.height / 2;

      container.scrollTo({
        top: Math.max(0, targetScroll),
        behavior: "smooth",
      });

      setActiveSection(sectionKey);
    }, 150);
  }, [parseMessageIndexFromSectionKey, touchMessageAt]);

  const latestAssistantMeta = useMemo(() => {
    const assistantIndexes = getActiveAnalysisAssistantMessageIndexes(messages);
    if (assistantIndexes.length === 0) return null;
    const index = assistantIndexes[assistantIndexes.length - 1];
    return {
      message: messages[index],
      index,
      sections: assistantIndexes.flatMap((messageIndex) =>
        extractSections(messages[messageIndex].content, messageIndex)
      ),
    };
  }, [messages]);

  const navigatorActiveSectionKey = useMemo(() => {
    if (isTyping && latestAssistantMeta?.sections.length) {
      return latestAssistantMeta.sections[latestAssistantMeta.sections.length - 1]
        ?.sectionKey;
    }
    return activeSection;
  }, [activeSection, isTyping, latestAssistantMeta]);

  const renderedMessages = useMemo(
    () =>
      messages.map((message, msgIdx) => (
        <ChatMessageItem
          key={message.id}
          message={message}
          messageIndex={msgIdx}
          isStreaming={message.sender === "ai" && message.id === streamingMessageId}
          renderAssistant={renderMessageWithSections}
          renderAssistantStreaming={renderMessageWithSectionsStreaming}
        />
      )),
    [
      messages,
      renderMessageWithSections,
      renderMessageWithSectionsStreaming,
      streamingMessageId,
    ]
  );


  const renderedStepNavigator = useMemo(() => {
    if (!latestAssistantMeta || latestAssistantMeta.sections.length === 0) {
      return null;
    }

    const allSections = latestAssistantMeta.sections;
    const activeIdx = allSections.findIndex(
      (section) => section.sectionKey === navigatorActiveSectionKey
    );
    const enableNavigatorAnimations = allSections.length <= 16;

    return (
      <>
        {/* Step Navigator - Top Horizontal */}
        {latestAssistantMeta && latestAssistantMeta.sections.length > 0 && (() => {
          const allSections = latestAssistantMeta.sections;
          const activeIdx = allSections.findIndex(
            (section) => section.sectionKey === navigatorActiveSectionKey
          );

          return (
            <div className="relative border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-950 px-6 py-4 overflow-hidden">
              {/* 背景装饰 */}
              <div className="absolute inset-0 bg-gradient-to-r from-blue-50/50 via-purple-50/30 to-pink-50/50 dark:from-blue-950/20 dark:via-purple-950/10 dark:to-pink-950/20 pointer-events-none" />

              <div
                ref={stepNavigatorRef}
                className="relative flex items-center gap-1 overflow-x-auto pb-1 scrollbar-thin"
              >
                {allSections.map((section, idx) => {
                  const isActive = navigatorActiveSectionKey === section.sectionKey;
                  const isCompleted = activeIdx > idx;

                  // 颜色映射
                  const colorMap: Record<
                    string,
                    {
                bg: string;
                border: string;
                glow: string;
                text: string;
                    }
                  > = {
                    "bg-blue-500": {
                bg: "bg-blue-500",
                border: "border-blue-400",
                glow: "shadow-blue-500/50",
                text: "text-blue-600",
                    },
                    "bg-cyan-500": {
                bg: "bg-cyan-500",
                border: "border-cyan-400",
                glow: "shadow-cyan-500/50",
                text: "text-cyan-600",
                    },
                    "bg-gray-500": {
                bg: "bg-gray-500",
                border: "border-gray-400",
                glow: "shadow-gray-500/50",
                text: "text-gray-600",
                    },
                    "bg-orange-500": {
                bg: "bg-orange-500",
                border: "border-orange-400",
                glow: "shadow-orange-500/50",
                text: "text-orange-600",
                    },
                    "bg-green-500": {
                bg: "bg-green-500",
                border: "border-green-400",
                glow: "shadow-green-500/50",
                text: "text-green-600",
                    },
                    "bg-purple-500": {
                bg: "bg-purple-500",
                border: "border-purple-400",
                glow: "shadow-purple-500/50",
                text: "text-purple-600",
                    },
                  };
                  const colors =
                    colorMap[section.config.color] ||
                    colorMap["bg-gray-500"];

                  return (
                    <div
                key={section.sectionKey}
                className="flex items-center shrink-0"
                ref={(el) => {
                  if (el) {
                    activeStepRefs.current.set(
                      section.sectionKey,
                      el
                    );
                  }
                }}
                    >
                {/* 步骤节点 */}
                <button
                  onClick={() =>
                    scrollToSection(section.sectionKey)
                  }
                  className={`group relative flex flex-col items-center gap-1.5 px-2 py-1.5 rounded-lg transition-all duration-300 ${isActive
                    ? "scale-105"
                    : "hover:scale-102 hover:bg-gray-50 dark:hover:bg-gray-900/50"
                    }`}
                >
                  {/* 圆圈容器 */}
                  <div className="relative">
                    {/* 脉动动画背景 */}
                    {isActive && enableNavigatorAnimations && (
                      <div
                        className={`absolute inset-0 ${colors.bg} rounded-full animate-ping opacity-20`}
                      />
                    )}

                    {/* 主圆圈 */}
                    <div
                      className={`relative w-9 h-9 rounded-full flex items-center justify-center font-semibold text-base transition-all duration-500 ${isActive
                        ? `${colors.bg} text-white shadow-lg ${colors.glow
                        } ring-2 ring-offset-1 ${colors.border.replace(
                          "border-",
                          "ring-"
                        )} ring-opacity-30 dark:ring-offset-gray-950`
                        : isCompleted
                          ? "bg-gradient-to-br from-green-400 to-green-600 text-white shadow-md shadow-green-500/30"
                          : "bg-gradient-to-br from-gray-100 to-gray-200 dark:from-gray-800 dark:to-gray-700 border-2 border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500"
                        } ${!isActive &&
                        !isCompleted &&
                        "group-hover:border-gray-400 dark:group-hover:border-gray-500 group-hover:shadow-md"
                        }`}
                    >
                      {/* 内容 */}
                      {isCompleted ? (
                        <Check className="w-4 h-4" />
                      ) : (
                        <span
                          className={`text-base transition-transform duration-300 ${isActive
                            ? "scale-110"
                            : "group-hover:scale-105"
                            }`}
                        >
                          {section.config.icon}
                        </span>
                      )}

                      {/* 进度指示小点 */}
                      {isActive && (
                        <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-white dark:bg-gray-950 rounded-full flex items-center justify-center">
                          <div className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 标签 */}
                  <div
                    className={`text-[11px] font-semibold whitespace-nowrap transition-all duration-300 ${isActive
                      ? `${colors.text} dark:text-white scale-105`
                      : isCompleted
                        ? "text-green-600 dark:text-green-400"
                        : "text-gray-500 dark:text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-300"
                      }`}
                  >
                    {section.type}
                  </div>

                  {/* 序号 */}
                  <div
                    className={`absolute top-0 left-0 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold transition-all duration-300 ${isActive
                      ? `${colors.bg} text-white shadow-sm`
                      : isCompleted
                        ? "bg-green-500 text-white"
                        : "bg-gray-300 dark:bg-gray-600 text-gray-600 dark:text-gray-300"
                      }`}
                  >
                    {idx + 1}
                  </div>
                </button>

                {/* 连接线 */}
                {idx < allSections.length - 1 && (
                  <div className="relative w-16 h-1 mx-1">
                    {/* 背景轨道 */}
                    <div className="absolute inset-0 bg-gray-200 dark:bg-gray-700 rounded-full" />

                    {/* 进度条 */}
                    <div
                      className={`absolute inset-0 rounded-full transition-all duration-700 ${isCompleted || isActive
                        ? "bg-gradient-to-r from-green-400 to-green-500 shadow-sm shadow-green-500/30"
                        : "bg-transparent"
                        }`}
                      style={{
                        transform: isActive
                          ? "scaleX(0.5)"
                          : "scaleX(1)",
                        transformOrigin: "left",
                      }}
                    />

                    {/* 流动动画 */}
                    {isActive && enableNavigatorAnimations && (
                      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white to-transparent opacity-50 animate-shimmer" />
                    )}
                  </div>
                )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}

      </>
    );
  }, [latestAssistantMeta, navigatorActiveSectionKey, scrollToSection]);

  const handleStopMessage = useCallback(async () => {
    const controller = streamAbortControllerRef.current;
    if (!controller && !isTypingRef.current) return;
    setIsStopping(true);
    try {
      if (sessionId) {
        const response = await fetch(API_URLS.CHAT_STOP, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ session_id: sessionId }),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
      }
      controller?.abort();
      streamAbortControllerRef.current = null;
      updateTypingState(false);
      setStreamingMessageId(null);
    } catch (error) {
      console.warn("stop stream failed", error);
      toastRef.current({
        description:
          uiLanguage === "zh"
            ? "停止任务失败，请稍后重试"
            : "Failed to stop the task. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsStopping(false);
    }
  }, [sessionId, uiLanguage, updateTypingState]);

  const handleSendMessage = async () => {
    if (isTypingRef.current) {
      await handleStopMessage();
      return;
    }
    const resumePending = manualPaused;
    const trimmedCustomModelName = customModelName.trim();
    if (llmProvider === "heywhale" && !heywhaleApiKey.trim()) {
      toastRef.current({
        description: textLabels.needHeywhaleKey,
        variant: "destructive",
      });
      return;
    }
    if (llmProvider === "custom" && !trimmedCustomModelName) {
      toastRef.current({
        description: textLabels.needCustomModel,
        variant: "destructive",
      });
      return;
    }
    if (llmProvider === "custom" && !customApiBase.trim()) {
      toastRef.current({
        description: textLabels.needCustomApiBase,
        variant: "destructive",
      });
      return;
    }
    if (!resumePending && !inputValue.trim() && attachments.length === 0) return;
    if (resumePending) setManualPaused(false);
    const additionalInstruction = resumePending ? inputValue.trim() : "";
    const shouldAppendUserMessage = resumePending
      ? !!additionalInstruction
      : !!inputValue.trim() || attachments.length > 0;
    const baseMessageIndex = messages.length;
    const aiMessageIndex = baseMessageIndex + (shouldAppendUserMessage ? 1 : 0);

    const newMessage: Message | null = shouldAppendUserMessage
      ? {
          id: resumePending
            ? `manual-instruction-${Date.now()}`
            : Date.now().toString(),
          content: inputValue,
          sender: "user",
          timestamp: new Date(),
          attachments:
            !resumePending && attachments.length > 0
              ? [...attachments]
              : undefined,
        }
      : null;
    const sessionMessagesForRequest = newMessage
      ? [...messages, newMessage]
      : messages;

    if (newMessage) {
      setMessages((prev) => [...prev, newMessage]);
    }
    setInputValue("");
    setAttachments([]);
    updateTypingState(true);
    setIsStopping(false);
    const abortController = new AbortController();
    streamAbortControllerRef.current = abortController;
    const aiMsgId = `${Date.now()}-${Math.random()}`;

    try {
      const response = await fetch(API_URLS.CHAT_COMPLETIONS, {
        method: "POST",
        signal: abortController.signal,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model:
            llmProvider === "custom"
              ? trimmedCustomModelName || DEFAULT_MODEL_NAME
              : DEFAULT_MODEL_NAME,
          provider: llmProvider,
          api_key:
            llmProvider === "heywhale"
              ? heywhaleApiKey.trim()
              : llmProvider === "custom"
                ? customApiKey.trim()
                : "",
          api_base: llmProvider === "custom" ? customApiBase.trim() : "",
          temperature: normalizedTemperature,
          ui_language: uiLanguage,
          system_prompt: systemPrompt.trim(),
          workspace: Array.from(selectedAnalysisFiles),
          assistant_message_id: aiMsgId,
          interaction_mode: interactionMode,
          resume_pending: resumePending,
          additional_instruction: additionalInstruction,
          session_messages: sessionMessagesForRequest
            .filter((message) => !message.localOnly)
            .map((message) => ({
              id: message.id,
              role: message.sender === "user" ? "user" : "assistant",
              content: message.content,
              timestamp: message.timestamp,
              attachments: message.attachments || [],
            })),
          messages: resumePending
            ? []
            : [
                ...(effectiveSystemPrompt
                  ? [
                      {
                        role: "system",
                        content: effectiveSystemPrompt,
                      },
                    ]
                  : []),
                ...messages
                  .filter((m) => !m.localOnly)
                  .map((msg) => ({
                    role: msg.sender === "user" ? "user" : "assistant",
                    content: msg.content,
                  })),
                {
                  role: "user",
                  content: inputValue,
                },
              ],
          stream: true,
          session_id: sessionId,
        }),
      });

      const contentType = response.headers.get("content-type") || "";

      if (response.status === 401) {
        streamAbortControllerRef.current = null;
        setIsStopping(false);
        updateTypingState(false);
        window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        return;
      }

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // 情况1: 非流式 JSON (兜底)
      if (contentType.includes("application/json")) {
        const data = await response.json();
        const content = data?.choices?.[0]?.message?.content || "";
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            sender: "ai",
            content,
            timestamp: new Date(),
          },
        ]);
        autoCollapseForContent(content, aiMessageIndex);
        await Promise.all([loadWorkspaceTree(), loadWorkspaceFiles()]);
        streamAbortControllerRef.current = null;
        setIsStopping(false);
        updateTypingState(false);
        return;
      }

      // 情况2: 流式响应 (NDJSON / SSE)
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        updateTypingState(false);
        setStreamingMessageId(null);
        streamAbortControllerRef.current = null;
        setIsStopping(false);
        return;
      }

      // 预先插入 AI 消息占位
      setStreamingMessageId(aiMsgId);
      setMessages((prev) => [
        ...prev,
        {
          id: aiMsgId,
          sender: "ai",
          content: "",
          timestamp: new Date(),
        },
      ]);

      // [修改] 用于在本地累积完整的消息内容
      let accumulatedMessage = "";
      let refreshedExecutionCount = 0;

      // 更新 UI 的辅助函数
      const flushAiMessage = (visibleText: string) => {
        setMessages((prev) => {
          const next = [...prev];
          const idx = next.findIndex((m) => m.id === aiMsgId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], content: visibleText };
          }
          return next;
        });

        const executionCount = (visibleText.match(/<\/Execute>/g) || []).length;
        if (executionCount > refreshedExecutionCount) {
          refreshedExecutionCount = executionCount;
          void Promise.all([loadWorkspaceTree(), loadWorkspaceFiles()]);
        }
      };

      const yieldToNextPaint = () =>
        new Promise<void>((resolve) => {
          window.requestAnimationFrame(() => resolve());
        });

      let buffer = "";
      let nextInteractionStatus: "idle" | "awaiting_user" = "idle";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed === "data: [DONE]") continue;

          try {
            const json = JSON.parse(trimmed);
            const deltaContent = json.choices?.[0]?.delta?.content;
            const interactionStatus = json.deepanalyze?.interaction_status;
            if (
              interactionStatus === "idle" ||
              interactionStatus === "awaiting_user"
            ) {
              nextInteractionStatus = interactionStatus;
            }

            if (deltaContent) {
              accumulatedMessage += deltaContent;
              flushAiMessage(accumulatedMessage);
              await yieldToNextPaint();
            }
          } catch (e) {
            console.warn("JSON parse error for line:", trimmed, e);
          }
        }
      }

      if (buffer.trim()) {
        try {
          const json = JSON.parse(buffer.trim());
          const deltaContent = json.choices?.[0]?.delta?.content;
          const interactionStatus = json.deepanalyze?.interaction_status;
          if (
            interactionStatus === "idle" ||
            interactionStatus === "awaiting_user"
          ) {
            nextInteractionStatus = interactionStatus;
          }
          if (deltaContent) {
            accumulatedMessage += deltaContent;
            flushAiMessage(accumulatedMessage);
            await yieldToNextPaint();
          }
        } catch (e) { }
      }

      // 确保缓存中的最后一段内容也写入消息状态。
      flushAiMessage(accumulatedMessage);
      autoCollapseForContent(accumulatedMessage, aiMessageIndex);
      setManualPaused(nextInteractionStatus === "awaiting_user");

      // 结束后刷新一次文件列表确保无遗漏
      await loadWorkspaceFiles();
      await loadWorkspaceTree();
      updateTypingState(false); // 结束加载状态
      setStreamingMessageId(null);
      streamAbortControllerRef.current = null;
      setIsStopping(false);

    } catch (error) {
      if ((error as Error)?.name !== "AbortError") {
        console.error("Error sending message:", error);
        toast({
          description: textLabels.streamInterrupted,
          variant: "destructive",
        });
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === aiMsgId);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = {
              ...next[idx],
              content: `${next[idx].content}\n\n> ${textLabels.streamInterrupted}`,
            };
            return next;
          }
          return [
            ...prev,
            {
              id: aiMsgId,
              sender: "ai",
              content: `\n\n> ${textLabels.streamInterrupted}`,
              timestamp: new Date(),
            },
          ];
        });
        if (interactionMode === "manual" && sessionId) {
          void fetch(
            `${API_URLS.SESSION_STATE}?session_id=${encodeURIComponent(sessionId)}`
          )
            .then((response) => (response.ok ? response.json() : null))
            .then((state) => {
              if (state) {
                setManualPaused(
                  isAwaitingManualContinuation(state.interaction_state)
                );
              }
            })
            .catch(() => undefined);
        }
      }
      updateTypingState(false);
      setStreamingMessageId(null);
      streamAbortControllerRef.current = null;
      setIsStopping(false);
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const files = event.target.files;
    if (!files) return;
    await uploadToDir("", files);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((att) => att.id !== id));
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const composerPlaceholder = manualPaused
    ? uiLanguage === "zh"
      ? "可选：为下一轮分析追加指令"
      : "Optional: add instructions for the next analysis round"
    : uiLanguage === "zh"
      ? "输入分析问题，或从左侧加载示例..."
      : "Enter an analysis question, or load a sample from the left...";
  const compactComposerPlaceholder = manualPaused
    ? uiLanguage === "zh"
      ? "追加指令（可选）"
      : "Add instructions (optional)"
    : uiLanguage === "zh"
      ? "输入分析问题..."
      : "Enter a question...";

  const renderInteractionModeControl = () => (
    <div
      className="mb-2 flex min-w-0 flex-wrap items-center gap-2"
      data-testid="interaction-mode-control"
    >
      <Tabs
        value={interactionMode}
        onValueChange={(value) =>
          setInteractionMode(normalizeInteractionMode(value))
        }
        className="gap-0"
      >
        <TabsList className="h-8 rounded-md bg-gray-100 p-0.5 dark:bg-gray-900">
          <TabsTrigger
            value="auto"
            disabled={isTyping}
            className="h-7 rounded px-2 text-xs"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {uiLanguage === "zh" ? "自动" : "Auto"}
          </TabsTrigger>
          <TabsTrigger
            value="manual"
            disabled={isTyping}
            className="h-7 rounded px-2 text-xs"
          >
            <Hand className="h-3.5 w-3.5" />
            {uiLanguage === "zh" ? "手动" : "Manual"}
          </TabsTrigger>
        </TabsList>
      </Tabs>
      {manualPaused && (
        <Badge
          variant="outline"
          className="min-w-0 rounded-full border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
        >
          <CirclePause className="mr-1 h-3.5 w-3.5 shrink-0" />
          <span className="truncate">
            {uiLanguage === "zh" ? "等待继续" : "Waiting to continue"}
          </span>
        </Badge>
      )}
    </div>
  );

  const renderClearChatButton = (buttonClassName: string) => (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={buttonClassName}
          title={uiLanguage === "zh" ? "清空聊天" : "Clear Chat"}
          disabled={isTyping}
        >
          <Eraser className="h-3.5 w-3.5" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {uiLanguage === "zh" ? "清空聊天？" : "Clear chat?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {uiLanguage === "zh"
              ? "将删除当前会话内的所有消息，仅保留欢迎提示。"
              : "This removes all messages in the current session and keeps only the welcome message."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{uiLanguage === "zh" ? "取消" : "Cancel"}</AlertDialogCancel>
          <AlertDialogAction
            onClick={clearChat}
            className="bg-red-600 hover:bg-red-700"
          >
            {uiLanguage === "zh" ? "确认清空" : "Confirm"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  const renderComposerInput = (placeholder: string) => (
    <div
      className="flex min-w-0 flex-1 items-end overflow-hidden rounded-2xl border border-gray-200 bg-white transition-colors focus-within:border-gray-400 dark:border-gray-800 dark:bg-black dark:focus-within:border-gray-600"
      data-testid="chat-composer-input"
    >
      <Button
        variant="ghost"
        size="sm"
        onClick={() => fileInputRef.current?.click()}
        className="h-10 w-10 shrink-0 rounded-full p-0 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        title={uiLanguage === "zh" ? "上传文件" : "Upload Files"}
        aria-label={uiLanguage === "zh" ? "上传文件" : "Upload Files"}
        data-testid="chat-composer-upload"
      >
        <Plus className="h-4 w-4" />
      </Button>
      <AutoGrowingTextarea
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        placeholder={placeholder}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
          }
        }}
        className="max-h-40 min-h-10 flex-1 resize-none rounded-none border-0 bg-transparent px-0 py-2.5 pr-3 shadow-none [field-sizing:fixed] focus-visible:border-0 focus-visible:ring-0"
        data-testid="chat-composer-textarea"
      />
    </div>
  );

  const renderChatComposer = (
    wrapperClassName: string,
    options?: { stacked?: boolean }
  ) => {
    const stacked = !!options?.stacked;
    return (
      <div className={wrapperClassName}>
        {renderInteractionModeControl()}
        <div className={stacked ? "space-y-2" : "flex items-end gap-2"}>
          {renderComposerInput(
            stacked ? compactComposerPlaceholder : composerPlaceholder
          )}

          <div
            className={
              stacked
                ? "flex items-center justify-end gap-2"
                : "flex items-center gap-2"
            }
          >
            {isTyping ? (
              <Button
                onClick={handleStopMessage}
                size="sm"
                className="h-10 rounded-full px-4 bg-red-600 text-white hover:bg-red-700 dark:bg-red-600 dark:text-white dark:hover:bg-red-700"
                title={uiLanguage === "zh" ? "\u6b63\u5728\u751f\u6210" : "Generating"}
                disabled={isStopping}
              >
                {isStopping ? (
                  <RefreshCw className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <Square className="h-3.5 w-3.5 mr-1 fill-current" />
                )}
                {uiLanguage === "zh" ? "\u505c\u6b62" : "Stop"}
              </Button>
            ) : (
              <Button
                onClick={handleSendMessage}
                size="sm"
                disabled={
                  !manualPaused &&
                  !inputValue.trim() &&
                  attachments.length === 0
                }
                className="h-10 rounded-full bg-black px-4 text-white dark:bg-white dark:text-black hover:bg-gray-800 dark:hover:bg-gray-200"
              >
                {manualPaused ? (
                  <Play className="h-4 w-4 mr-1" />
                ) : (
                  <Send className="h-4 w-4 mr-1" />
                )}
                {manualPaused
                  ? uiLanguage === "zh"
                    ? "继续分析"
                    : "Continue"
                  : uiLanguage === "zh"
                    ? "发送"
                    : "Send"}
              </Button>
            )}
            {renderClearChatButton("h-10 rounded-full px-3")}
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      <div
        className="h-screen bg-white dark:bg-black text-black dark:text-white"
        suppressHydrationWarning
      >
        <ResizablePanelGroup direction="horizontal" className="h-full">
          {/* Left Panel - Workspace Tree */}
          <ResizablePanel defaultSize={25} minSize={20}>
            <div className="flex flex-col min-h-0 min-w-0 h-full bg-white/80 dark:bg-gray-950/80 border-r border-gray-200/70 dark:border-gray-800/70">
              <div className="flex items-start justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {textLabels.workspace}
                  </h2>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {textLabels.workspaceHint}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    onChange={handleFileUpload}
                    className="hidden"
                    accept={UPLOAD_ACCEPT_TYPES}
                  />
                  <DropdownMenu
                    open={sessionListOpen}
                    onOpenChange={(open) => {
                      setSessionListOpen(open);
                      if (open) void loadSessionList();
                    }}
                  >
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2 gap-1.5 text-xs text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
                        title={uiLanguage === "zh" ? "会话与账号" : "Sessions & account"}
                      >
                        <User className="h-3.5 w-3.5" />
                        <span className="max-w-[72px] truncate">
                          {currentUsername || "..."}
                        </span>
                        <ChevronDown className="h-3 w-3" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-72">
                      <DropdownMenuLabel>
                        {uiLanguage === "zh" ? "历史会话" : "Sessions"}
                      </DropdownMenuLabel>
                      <div className="max-h-72 overflow-y-auto">
                        {sessionList.length === 0 && (
                          <div className="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">
                            {uiLanguage === "zh" ? "暂无历史会话" : "No sessions yet"}
                          </div>
                        )}
                        {sessionList.map((item) => (
                          <DropdownMenuItem
                            key={item.session_id}
                            onClick={() => switchSession(item.session_id)}
                            className={
                              item.session_id === sessionId
                                ? "flex-col items-start gap-0.5 bg-accent"
                                : "flex-col items-start gap-0.5"
                            }
                          >
                            <span className="w-full truncate text-xs font-medium">
                              {item.instruction ||
                                (uiLanguage === "zh" ? "（未命名会话）" : "(untitled)")}
                            </span>
                            <span className="text-[11px] text-gray-500 dark:text-gray-400">
                              {formatSessionTime(item.updated_at)}
                              {item.message_count > 0
                                ? ` · ${item.message_count} ${uiLanguage === "zh" ? "条消息" : "msgs"}`
                                : ""}
                              {item.session_id === sessionId
                                ? uiLanguage === "zh" ? " · 当前" : " · current"
                                : ""}
                            </span>
                          </DropdownMenuItem>
                        ))}
                      </div>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={createNewSession}>
                        <Plus className="h-3.5 w-3.5 mr-2" />
                        {uiLanguage === "zh" ? "新建会话" : "New session"}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={handleLogout}>
                        <LogOut className="h-3.5 w-3.5 mr-2" />
                        {uiLanguage === "zh" ? "退出登录" : "Log out"}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>

              <div
                ref={treeContainerRef}
                className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-3 py-3 space-y-3"
              >
                <Collapsible className="border-b border-gray-200/80 pb-3 dark:border-gray-800/80">
                  <div className="flex items-end gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                          {textLabels.language}
                        </div>
                        <Select
                          value={uiLanguage}
                          onValueChange={(value) => setUiLanguage(value as UILanguage)}
                        >
                          <SelectTrigger className="h-9 w-full rounded-lg">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="en">English</SelectItem>
                            <SelectItem value="zh">中文</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <CollapsibleTrigger asChild>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 shrink-0 justify-between rounded-lg px-3 text-xs"
                          title={uiLanguage === "zh" ? "模型与提示词设置" : "Model & prompt settings"}
                        >
                          <span className="flex items-center gap-2">
                            <Settings2 className="h-3.5 w-3.5" />
                            {uiLanguage === "zh" ? "设置" : "Settings"}
                          </span>
                          <ChevronDown className="h-3.5 w-3.5" />
                        </Button>
                      </CollapsibleTrigger>
                  </div>
                      <CollapsibleContent className="mt-3 space-y-3 border-t border-gray-100 pt-3 dark:border-gray-800">
                    <div>
                      <div className="mb-1.5 flex items-center justify-between">
                        <div className="text-xs font-medium text-gray-700 dark:text-gray-300">
                          {textLabels.systemPrompt}
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-gray-500"
                          onClick={() => setSystemPrompt("")}
                        >
                          {textLabels.emptySystemPrompt}
                        </Button>
                      </div>
                      <Textarea
                        value={systemPrompt}
                        onChange={(e) => setSystemPrompt(e.target.value)}
                        className="min-h-20 rounded-2xl border-gray-200 dark:border-gray-800 bg-white dark:bg-black text-sm"
                        placeholder={textLabels.systemPromptPlaceholder}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                          {textLabels.modelProvider}
                        </div>
                        <Select
                          value={llmProvider}
                          onValueChange={(value) =>
                            setLlmProvider(value as LlmProvider)
                          }
                        >
                          <SelectTrigger className="w-full rounded-xl">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="local">{textLabels.providerLocal}</SelectItem>
                            <SelectItem value="heywhale">{textLabels.providerHeywhale}</SelectItem>
                            <SelectItem value="custom">{textLabels.providerCustom}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <div className="mb-1.5 flex items-center justify-between">
                          <div className="text-xs font-medium text-gray-700 dark:text-gray-300">
                            {textLabels.temperature}
                          </div>
                          <div className="text-[11px] text-gray-500 dark:text-gray-400">
                            {normalizedTemperature.toFixed(1)}
                          </div>
                        </div>
                        <Input
                          value={modelTemperature}
                          onChange={(e) => setModelTemperature(e.target.value)}
                          inputMode="decimal"
                          className="rounded-xl border-gray-200 dark:border-gray-800"
                          placeholder="0.4"
                        />
                        <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                          {textLabels.temperatureHint}
                        </div>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                        {textLabels.modelName}
                      </div>
                      <Input
                        value={
                          llmProvider === "custom"
                            ? customModelName
                            : DEFAULT_MODEL_NAME
                        }
                        onChange={(e) => {
                          if (llmProvider === "custom") {
                            setCustomModelName(e.target.value);
                          }
                        }}
                        className="rounded-xl border-gray-200 dark:border-gray-800"
                        placeholder={
                          llmProvider === "custom"
                            ? textLabels.modelNamePlaceholder
                            : DEFAULT_MODEL_NAME
                        }
                        readOnly={llmProvider !== "custom"}
                        disabled={llmProvider !== "custom"}
                      />
                    </div>
                    {llmProvider === "heywhale" && (
                      <div>
                        <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                          {textLabels.heywhaleApiKey}
                        </div>
                        <Input
                          type="password"
                          value={heywhaleApiKey}
                          onChange={(e) => setHeywhaleApiKey(e.target.value)}
                          className="rounded-xl border-gray-200 dark:border-gray-800"
                          placeholder={textLabels.heywhaleApiKeyPlaceholder}
                        />
                      </div>
                    )}
                    {llmProvider === "custom" && (
                      <div className="space-y-3">
                        <div>
                          <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                            {textLabels.customApiBase}
                          </div>
                          <Input
                            value={customApiBase}
                            onChange={(e) => setCustomApiBase(e.target.value)}
                            className="rounded-xl border-gray-200 dark:border-gray-800"
                            placeholder={textLabels.customApiBasePlaceholder}
                          />
                        </div>
                        <div>
                          <div className="mb-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                            {textLabels.customApiKey}
                          </div>
                          <Input
                            type="password"
                            value={customApiKey}
                            onChange={(e) => setCustomApiKey(e.target.value)}
                            className="rounded-xl border-gray-200 dark:border-gray-800"
                            placeholder={textLabels.customApiKeyPlaceholder}
                          />
                        </div>
                      </div>
                    )}
                    <div className="space-y-2 border-t border-gray-100 pt-3 dark:border-gray-800">
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          className="h-8 rounded-lg px-3 text-xs"
                          onClick={saveModelConfig}
                          disabled={modelConfigSaving || modelConfigTesting}
                        >
                          {modelConfigSaving
                            ? uiLanguage === "zh" ? "保存中..." : "Saving..."
                            : uiLanguage === "zh" ? "保存配置" : "Save config"}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 rounded-lg px-3 text-xs"
                          onClick={testModelConfig}
                          disabled={modelConfigSaving || modelConfigTesting}
                        >
                          {modelConfigTesting
                            ? uiLanguage === "zh" ? "检测中..." : "Testing..."
                            : uiLanguage === "zh" ? "检测连接" : "Test connection"}
                        </Button>
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-gray-400">
                        {uiLanguage === "zh"
                          ? "配置按用户保存在服务端，登录同一账号即可恢复"
                          : "Config is stored per user on the server"}
                      </p>
                      {modelTestResult && (
                        <div
                          className={`rounded-lg px-2.5 py-2 text-[11px] leading-relaxed break-all ${
                            modelTestResult.success
                              ? "bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-300"
                              : "bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300"
                          }`}
                        >
                          <span className="font-medium">
                            {modelTestResult.success
                              ? uiLanguage === "zh" ? "连接成功" : "Connected"
                              : uiLanguage === "zh" ? "连接失败" : "Failed"}
                          </span>
                          {modelTestResult.latency_ms !== undefined &&
                            modelTestResult.success &&
                            ` · ${modelTestResult.latency_ms}ms`}
                          {modelTestResult.detail ? ` · ${modelTestResult.detail}` : ""}
                        </div>
                      )}
                    </div>
                      </CollapsibleContent>
                </Collapsible>
                {moveDialogToLeftPanel &&
                  renderChatComposer(
                    "rounded-xl border border-gray-200/80 dark:border-gray-800/80 bg-gray-50/80 dark:bg-gray-900/40 p-3",
                    { stacked: true }
                  )}

                <div className="space-y-4">
                  <div
                    className={`rounded-xl border border-dashed px-4 py-3 text-sm select-none transition-all ${dropActive
                      ? "bg-blue-50 border-blue-300 text-blue-700 dark:bg-blue-950/30 dark:border-blue-800 dark:text-blue-300"
                      : "bg-gray-50 dark:bg-gray-900/40 border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300"
                      }`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDropActive(true);
                    }}
                    onDragLeave={() => setDropActive(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDropActive(false);
                      const files = e.dataTransfer.files;
                      if (files && files.length) uploadToDir("", files);
                    }}
                  >
                    <div className="flex min-h-[76px] flex-wrap items-center justify-between gap-3">
                      <div className="flex min-w-[150px] flex-1 items-center gap-3">
                        <div className="rounded-lg bg-white/90 p-2 shadow-sm dark:bg-gray-950/90">
                          <Upload className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-slate-900 dark:text-white">
                            {textLabels.uploadPanelTitle}
                          </div>
                          <div className="mt-1 text-xs leading-4 text-gray-500 dark:text-gray-400">
                            {textLabels.uploadPanelHint}
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-8 rounded-lg"
                          onClick={() => fileInputRef.current?.click()}
                        >
                          <Upload className="h-3.5 w-3.5" />
                          {uiLanguage === "zh" ? "上传" : "Upload"}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 rounded-lg"
                          disabled={isLoadingSample || isSampleCatalogLoading}
                          onClick={() => void openSampleDialog()}
                        >
                        {isLoadingSample ? (
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Database className="h-3.5 w-3.5" />
                        )}
                        {uiLanguage === "zh" ? "加载示例" : "Load sample"}
                        </Button>
                      </div>
                    </div>
                  </div>

                  <div className="border-y border-gray-200/80 py-3 dark:border-gray-800/80">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <div className="text-xs font-medium text-gray-700 dark:text-gray-300">
                        {uiLanguage === "zh" ? "分析文件" : "Analysis files"}
                        <span className="ml-2 text-gray-400">
                          {selectedAnalysisFiles.size}/{rightPanelSourceFiles.filter((file) => !isGeneratedWorkspaceFile(file)).length}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => {
                            setSelectedAnalysisFiles(
                              new Set(
                                rightPanelSourceFiles
                                  .filter((file) => !isGeneratedWorkspaceFile(file))
                                  .map((file) => file.path)
                              )
                            );
                            fileSelectionInitializedRef.current = true;
                          }}
                        >
                          {uiLanguage === "zh" ? "全选" : "All"}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => {
                            setSelectedAnalysisFiles(new Set());
                            fileSelectionInitializedRef.current = true;
                          }}
                        >
                          {uiLanguage === "zh" ? "清空" : "Clear"}
                        </Button>
                      </div>
                    </div>
                    <div className="max-h-32 space-y-1 overflow-y-auto">
                      {rightPanelSourceFiles
                        .filter((file) => !isGeneratedWorkspaceFile(file))
                        .map((file) => (
                          <div
                            key={file.path}
                            className="flex items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-900"
                          >
                            <Checkbox
                              checked={selectedAnalysisFiles.has(file.path)}
                              onCheckedChange={(checked) =>
                                toggleAnalysisFile(file.path, checked === true)
                              }
                            />
                            <span className="min-w-0 flex-1 truncate" title={file.path}>{file.name}</span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 shrink-0"
                              title={uiLanguage === "zh" ? "预览文件" : "Preview file"}
                              onClick={() => {
                                setSelectedWorkspacePath(file.path);
                                void openPreview(file);
                              }}
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        ))}
                    </div>
                  </div>

                <Card className="rounded-2xl border-gray-200/80 dark:border-gray-800/80 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {textLabels.exportCenter}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 rounded-xl px-3"
                        onClick={() => handleReportExport("md")}
                        type="button"
                        disabled={exportingFormat !== null}
                      >
                        {exportingFormat === "md" ? (
                          <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <FileText className="mr-2 h-4 w-4" />
                        )}
                        <span className="text-xs">
                          {exportingFormat === "md"
                            ? textLabels.exportMarkdownBusy
                            : textLabels.exportMarkdown}
                        </span>
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 rounded-xl px-3"
                        onClick={() => handleReportExport("pdf")}
                        type="button"
                        disabled={exportingFormat !== null}
                      >
                        {exportingFormat === "pdf" ? (
                          <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="mr-2 h-4 w-4" />
                        )}
                        <span className="text-xs">
                          {exportingFormat === "pdf"
                            ? textLabels.exportPdfBusy
                            : textLabels.exportPdf}
                        </span>
                      </Button>
                    </div>
                  </div>
                  {exportingFormat === "pdf" && (
                    <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                      {textLabels.exportPdfPendingHint}
                    </div>
                  )}
                </Card>

                {uploadMsg && (
                  <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50 px-3 py-2 text-[11px] text-gray-500 dark:text-gray-400">
                    {uploadMsg}
                  </div>
                )}

                <Card className="rounded-2xl border-gray-200/80 dark:border-gray-800/80 p-3 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {textLabels.bundleDownload}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        {uiLanguage === "zh"
                          ? "仅打包 generated 目录中的结果文件"
                          : "Bundles only include files inside the generated folder."}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-full"
                      disabled={!generatedBundleCounts.all}
                      onClick={() => downloadGeneratedBundle("all")}
                    >
                      <Archive className="h-3.5 w-3.5 mr-1" />
                      {textLabels.allBundle}
                    </Button>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { key: "table", label: textLabels.tableBundle, count: generatedBundleCounts.table },
                      { key: "image", label: textLabels.imageBundle, count: generatedBundleCounts.image },
                      { key: "other", label: textLabels.otherBundle, count: generatedBundleCounts.other },
                    ].map((item) => (
                      <Button
                        key={item.key}
                        variant="outline"
                        size="sm"
                        className="h-auto flex-col gap-1 rounded-2xl py-3"
                        disabled={!item.count}
                        onClick={() => downloadGeneratedBundle(item.key as "table" | "image" | "other")}
                      >
                        <Package className="h-4 w-4" />
                        <span className="text-xs">{item.label}</span>
                        <span className="text-[11px] text-gray-500">
                          {item.count} {textLabels.filesUnit}
                        </span>
                      </Button>
                    ))}
                  </div>
                </Card>

                <div className="hidden space-y-2">
                  <Input
                    value={workspaceSearch}
                    onChange={(e) => setWorkspaceSearch(e.target.value)}
                    placeholder={textLabels.search}
                    className="h-9 rounded-xl border-gray-200 dark:border-gray-800"
                  />
                  <Tabs
                    value={workspaceView}
                    onValueChange={(value) =>
                      setWorkspaceView(value as "all" | "uploaded" | "generated")
                    }
                    className="gap-0"
                  >
                    <TabsList className="grid w-full grid-cols-3 rounded-xl">
                      <TabsTrigger value="uploaded">{textLabels.uploaded}</TabsTrigger>
                      <TabsTrigger value="generated">{textLabels.generated}</TabsTrigger>
                      <TabsTrigger value="all">{textLabels.all}</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>

                <Card className="hidden rounded-2xl border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200/80 dark:border-gray-800/80 bg-gray-50/80 dark:bg-gray-900/60">
                    <Badge variant="secondary" className="rounded-full px-2.5">
                      {workspaceView === "generated"
                        ? textLabels.generated
                        : workspaceView === "uploaded"
                          ? textLabels.uploaded
                          : textLabels.all}
                    </Badge>
                    <span className="text-[11px] text-gray-400 dark:text-gray-500">
                      {textLabels.clickToPreview}
                    </span>
                  </div>
                  {filteredWorkspaceFiles.length ? (
                    <div className="grid grid-cols-2 gap-3 p-3 xl:grid-cols-3">
                      {filteredWorkspaceFiles.map((file, index) => {
                        const isImage = file.category === "image" && !!file.preview_url;
                        const imageUrl = resolveWorkspaceFileUrl(file.preview_url || file.download_url);
                        const ext = (file.extension || "").replace(/^\./, "").toUpperCase() || "FILE";
                        return (
                          <button
                            key={`${file.path || file.name}-${index}`}
                            className={`group text-left rounded-2xl border p-2 transition-all hover:-translate-y-0.5 hover:shadow-md ${getFileAccentClasses(file)} ${selectedWorkspacePath === file.path ? "ring-2 ring-blue-300 dark:ring-blue-800" : ""}`}
                            onClick={() => {
                              setSelectedWorkspacePath(file.path);
                              openPreview(file);
                            }}
                            onDoubleClick={() => {
                              setSelectedWorkspacePath(file.path);
                              openFullPreview(file);
                            }}
                            type="button"
                          >
                            <div className="aspect-square overflow-hidden rounded-xl bg-white/80 dark:bg-gray-950/70 border border-white/60 dark:border-gray-800 flex items-center justify-center">
                              {isImage ? (
                                <img
                                  src={imageUrl}
                                  alt={file.name}
                                  className="h-full w-full object-cover"
                                />
                              ) : file.category === "table" ? (
                                <div className="flex flex-col items-center justify-center text-emerald-700 dark:text-emerald-300">
                                  <FileSpreadsheet className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : ["json", "sqlite", "db"].includes((file.extension || "").replace(/^\./, "")) ? (
                                <div className="flex flex-col items-center justify-center text-amber-700 dark:text-amber-300">
                                  <FileJson className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : ["py", "sql", "js", "ts", "tsx", "jsx", "ipynb"].includes((file.extension || "").replace(/^\./, "")) ? (
                                <div className="flex flex-col items-center justify-center text-violet-700 dark:text-violet-300">
                                  <FileCode2 className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : file.category === "image" ? (
                                <div className="flex flex-col items-center justify-center text-blue-700 dark:text-blue-300">
                                  <FileImage className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : (
                                <div className="flex flex-col items-center justify-center text-gray-700 dark:text-gray-300">
                                  <FileText className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              )}
                            </div>
                            <div className="px-1 pt-2">
                              <div className="truncate text-xs font-medium text-gray-900 dark:text-gray-100" title={file.path}>
                                {file.name}
                              </div>
                              <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400">
                                <span className="truncate">{formatFileSize(file.size)}</span>
                                <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px]">
                                  {isGeneratedWorkspaceFile(file)
                                    ? textLabels.generated
                                    : textLabels.uploaded}
                                </Badge>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full px-4 py-10 text-sm text-gray-500 dark:text-gray-400">
                      {textLabels.noFiles}
                    </div>
                  )}
                </Card>
              </div>
            </div>
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Middle Panel - Chat & Analysis */}
          <ResizablePanel defaultSize={50} minSize={30}>
            <div className="flex flex-col min-h-0 min-w-0 h-full">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0 bg-white/80 dark:bg-gray-950/80">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {textLabels.appTitle}
                    </h1>
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {textLabels.appSubtitle}
                    </span>
                    {isTyping && (
                      <Badge variant="secondary" className="rounded-full px-2.5 py-0.5 text-xs">
                        <RefreshCw className="mr-1 h-3 w-3 animate-spin" />
                        {uiLanguage === "zh" ? "执行中" : "Running"}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate">
                    {textLabels.assistantHint}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-full"
                        title={uiLanguage === "zh" ? "视图设置" : "View settings"}
                      >
                        <Settings2 className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>
                        {uiLanguage === "zh" ? "视图设置" : "View settings"}
                      </DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuCheckboxItem
                        checked={autoCollapseEnabled}
                        onCheckedChange={(v: boolean) => {
                        setAutoCollapseEnabled(!!v);
                        if (typeof window !== "undefined") {
                          localStorage.setItem(
                            "autoCollapseEnabled",
                            (!!v).toString()
                          );
                        }
                        if (!v) {
                          setCollapsedSections({});
                          setManualLocks({});
                        }
                        }}
                      >
                        {uiLanguage === "zh" ? "自动折叠" : "Auto collapse"}
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuCheckboxItem
                        checked={fixedStreamingSectionHeightEnabled}
                        onCheckedChange={(v: boolean) => {
                        setFixedStreamingSectionHeightEnabled(!!v);
                        if (typeof window !== "undefined") {
                          localStorage.setItem(
                            "fixedStreamingSectionHeightEnabled",
                            (!!v).toString()
                          );
                        }
                        }}
                      >
                        {uiLanguage === "zh" ? "固定流式高度" : "Fixed stream height"}
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuCheckboxItem
                        checked={moveDialogToLeftPanel}
                        onCheckedChange={(v: boolean) => {
                        setMoveDialogToLeftPanel(!!v);
                        if (typeof window !== "undefined") {
                          localStorage.setItem(
                            "moveDialogToLeftPanel",
                            (!!v).toString()
                          );
                        }
                        }}
                      >
                        {textLabels.moveDialogToLeft}
                      </DropdownMenuCheckboxItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full"
                    onClick={() => setShowCodeEditor(true)}
                    disabled={!codeEditorContent.trim()}
                  >
                    <PanelRightOpen className="h-3.5 w-3.5 mr-1" />
                    {uiLanguage === "zh" ? "代码工作台" : "Code Lab"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={toggleTheme}
                    className="h-8 w-8 p-0 rounded-full"
                  >
                    {mounted ? (
                      isDarkMode ? (
                        <Sun className="h-4 w-4" />
                      ) : (
                        <Moon className="h-4 w-4" />
                      )
                    ) : (
                      <Moon className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>

              {renderedStepNavigator}

              {/* Chat Messages */}
              <div
                ref={messagesContainerRef}
                className="flex-1 min-h-0 min-w-0 overflow-y-scroll overflow-x-hidden px-4 py-4 pr-5 space-y-6 scrollbar-auto"
              >
                {renderedMessages}
                {/* 加载气泡已移除，改为仅按钮态提示 */}
                <div ref={messagesEndRef} />
              </div>

              {/* Input Area */}
              {!moveDialogToLeftPanel && (
                renderChatComposer(
                  "p-4 border-t border-gray-200 dark:border-gray-800 shrink-0 bg-white/80 dark:bg-gray-950/80"
                )
              )}

            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Right Panel - Inspector */}
          <ResizablePanel defaultSize={25} minSize={18}>
            <div className="flex h-full min-h-0 flex-col bg-white/80 dark:bg-gray-950/80 border-l border-gray-200/70 dark:border-gray-800/70">
              <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-800 px-4 py-2 shrink-0">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {uiLanguage === "zh" ? "检查栏" : "Inspector"}
                  </h2>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    {uiLanguage === "zh"
                      ? "预览当前文件、查看最近产物和快速进入代码工作台"
                      : "Preview the current file, inspect recent artifacts, and jump into the code lab."}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-full"
                  onClick={() => setShowCodeEditor(true)}
                  disabled={!codeEditorContent.trim()}
                >
                  <Code2 className="mr-1 h-3.5 w-3.5" />
                  {uiLanguage === "zh" ? "代码" : "Code"}
                </Button>
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
                <Card className="rounded-2xl border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                  <div className="border-b border-gray-200/80 dark:border-gray-800/80 px-4 py-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100 shrink-0">
                        {uiLanguage === "zh" ? "当前预览" : "Current Preview"}
                      </div>
                      {previewTitle && (
                        <>
                          <span className="text-xs text-gray-400 dark:text-gray-500">/</span>
                          <div className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                            {previewTitle}
                          </div>
                          <div className="shrink-0 text-xs text-gray-500 dark:text-gray-400">
                            {getLocalizedPreviewType(previewType)}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="p-4">
                    {previewTitle ? (
                      <div className="space-y-3">
                        <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/60">
                          {renderPreviewContent({ compact: true })}
                        </div>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="flex-1 rounded-full"
                            onClick={() => setIsPreviewOpen(true)}
                          >
                            <Eye className="mr-1 h-3.5 w-3.5" />
                            {uiLanguage === "zh" ? "完整预览" : "Open Preview"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={handleDownload}
                          >
                            <Download className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-gray-500 dark:text-gray-400">
                        {uiLanguage === "zh"
                          ? "从左侧文件卡片中选择一个文件开始预览。"
                          : "Select a file card on the left to preview it here."}
                      </div>
                    )}
                  </div>
                </Card>

                <Card className="rounded-2xl border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                  <div className="border-b border-gray-200/80 dark:border-gray-800/80 px-4 py-2">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                          {fileStatsTitle}
                        </div>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          {fileStatsHint}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            loadWorkspaceTree();
                            loadWorkspaceFiles();
                          }}
                          className="h-8 w-8 p-0"
                          title="refresh"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
                              title="clear workspace"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                {uiLanguage === "zh" ? "清空 workspace？" : "Clear workspace?"}
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                {uiLanguage === "zh"
                                  ? "将删除 workspace 根目录下的所有文件与文件夹，此操作不可撤销。"
                                  : "This deletes all files and folders under the workspace root. This action cannot be undone."}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>{uiLanguage === "zh" ? "取消" : "Cancel"}</AlertDialogCancel>
                              <AlertDialogAction
                                className="bg-red-600 hover:bg-red-700"
                                onClick={clearWorkspace}
                              >
                                {uiLanguage === "zh" ? "确认清空" : "Confirm"}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 p-3">
                    <button
                      type="button"
                      className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                        workspaceView === "uploaded"
                          ? "border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/20"
                          : "border-gray-200 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900/60"
                      }`}
                      onClick={() => setWorkspaceView("uploaded")}
                    >
                      <Upload className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                        {textLabels.uploaded}
                      </div>
                      <div className="mt-0.5 text-base font-semibold text-gray-900 dark:text-gray-100">
                        {workspaceFileCounts.uploaded}
                      </div>
                    </button>
                    <button
                      type="button"
                      className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                        workspaceView === "generated"
                          ? "border-purple-300 bg-purple-50 dark:border-purple-800 dark:bg-purple-950/20"
                          : "border-gray-200 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900/60"
                      }`}
                      onClick={() => setWorkspaceView("generated")}
                    >
                      <Sparkles className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                        {textLabels.generated}
                      </div>
                      <div className="mt-0.5 text-base font-semibold text-gray-900 dark:text-gray-100">
                        {workspaceFileCounts.generated}
                      </div>
                    </button>
                    <button
                      type="button"
                      className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                        workspaceView === "all"
                          ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/20"
                          : "border-gray-200 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900/60"
                      }`}
                      onClick={() => setWorkspaceView("all")}
                    >
                      <FolderOpen className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                        {textLabels.all}
                      </div>
                      <div className="mt-0.5 text-base font-semibold text-gray-900 dark:text-gray-100">
                        {workspaceFileCounts.all}
                      </div>
                    </button>
                  </div>

                  <div className="border-t border-gray-200/80 dark:border-gray-800/80 p-3 space-y-3">
                    <Input
                      value={workspaceSearch}
                      onChange={(e) => setWorkspaceSearch(e.target.value)}
                      placeholder={textLabels.search}
                      className="h-9 rounded-xl border-gray-200 dark:border-gray-800"
                    />

                    <div className="rounded-xl border border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200/80 dark:border-gray-800/80 bg-gray-50/80 dark:bg-gray-900/60">
                        <Badge variant="secondary" className="rounded-full px-2.5">
                          {workspaceView === "generated"
                            ? textLabels.generated
                            : workspaceView === "uploaded"
                              ? textLabels.uploaded
                              : textLabels.all}
                        </Badge>
                        <span className="text-[11px] text-gray-400 dark:text-gray-500">
                          {textLabels.clickToPreview}
                        </span>
                      </div>
                      {filteredWorkspaceFiles.length ? (
                        <div className="flex flex-wrap gap-2 p-2">
                          {filteredWorkspaceFiles.map((file, index) => {
                            const isImage = file.category === "image" && !!file.preview_url;
                            const imageUrl = resolveWorkspaceFileUrl(file.preview_url || file.download_url);
                            const ext = (file.extension || "").replace(/^\./, "").toUpperCase() || "FILE";
                            return (
                              <button
                                key={`${file.path || file.name}-${index}`}
                                className={`group w-[124px] shrink-0 rounded-lg border p-1.5 text-left transition-all hover:-translate-y-0.5 hover:shadow-md ${getFileAccentClasses(file)} ${selectedWorkspacePath === file.path ? "ring-2 ring-blue-300 dark:ring-blue-800" : ""}`}
                                onClick={() => {
                                  setSelectedWorkspacePath(file.path);
                                  openPreview(file);
                                }}
                                onDoubleClick={() => {
                                  setSelectedWorkspacePath(file.path);
                                  openFullPreview(file);
                                }}
                                type="button"
                              >
                                <div className="aspect-[4/3] overflow-hidden rounded-md border border-white/60 bg-white/80 dark:border-gray-800 dark:bg-gray-950/70 flex items-center justify-center">
                                  {isImage ? (
                                    <img
                                      src={imageUrl}
                                      alt={file.name}
                                      className="h-full w-full object-contain"
                                    />
                                  ) : file.category === "table" ? (
                                    <div className="flex flex-col items-center justify-center text-emerald-700 dark:text-emerald-300">
                                      <FileSpreadsheet className="h-9 w-9" />
                                      <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                    </div>
                                  ) : ["json", "sqlite", "db"].includes((file.extension || "").replace(/^\./, "")) ? (
                                    <div className="flex flex-col items-center justify-center text-amber-700 dark:text-amber-300">
                                      <FileJson className="h-9 w-9" />
                                      <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                    </div>
                                  ) : ["py", "sql", "js", "ts", "tsx", "jsx", "ipynb"].includes((file.extension || "").replace(/^\./, "")) ? (
                                    <div className="flex flex-col items-center justify-center text-violet-700 dark:text-violet-300">
                                      <FileCode2 className="h-9 w-9" />
                                      <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                    </div>
                                  ) : file.category === "image" ? (
                                    <div className="flex flex-col items-center justify-center text-blue-700 dark:text-blue-300">
                                      <FileImage className="h-9 w-9" />
                                      <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col items-center justify-center text-gray-700 dark:text-gray-300">
                                      <FileText className="h-9 w-9" />
                                      <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                    </div>
                                  )}
                                </div>
                                <div className="px-0.5 pt-1.5">
                                  <div className="truncate text-xs font-medium text-gray-900 dark:text-gray-100" title={file.path}>
                                    {file.name}
                                  </div>
                                  <div className="mt-0.5 flex items-center justify-between gap-1 text-[11px] text-gray-500 dark:text-gray-400">
                                    <span className="truncate">{formatFileSize(file.size)}</span>
                                    <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-xs">
                                      {isGeneratedWorkspaceFile(file)
                                        ? textLabels.generated
                                        : textLabels.uploaded}
                                    </Badge>
                                  </div>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="flex items-center justify-center h-full px-4 py-10 text-sm text-gray-500 dark:text-gray-400">
                          {textLabels.noFiles}
                        </div>
                      )}
                    </div>
                  </div>
                </Card>

                <div className="hidden space-y-2">
                  <Input
                    value={workspaceSearch}
                    onChange={(e) => setWorkspaceSearch(e.target.value)}
                    placeholder={textLabels.search}
                    className="h-9 rounded-xl border-gray-200 dark:border-gray-800"
                  />
                  <Tabs
                    value={workspaceView}
                    onValueChange={(value) =>
                      setWorkspaceView(value as "all" | "uploaded" | "generated")
                    }
                    className="gap-0"
                  >
                    <TabsList className="grid w-full grid-cols-3 rounded-xl">
                      <TabsTrigger value="uploaded">{textLabels.uploaded}</TabsTrigger>
                      <TabsTrigger value="generated">{textLabels.generated}</TabsTrigger>
                      <TabsTrigger value="all">{textLabels.all}</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>

                <Card className="hidden rounded-2xl border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200/80 dark:border-gray-800/80 bg-gray-50/80 dark:bg-gray-900/60">
                    <Badge variant="secondary" className="rounded-full px-2.5">
                      {workspaceView === "generated"
                        ? textLabels.generated
                        : workspaceView === "uploaded"
                          ? textLabels.uploaded
                          : textLabels.all}
                    </Badge>
                    <span className="text-[11px] text-gray-400 dark:text-gray-500">
                      {textLabels.clickToPreview}
                    </span>
                  </div>
                  {filteredWorkspaceFiles.length ? (
                    <div className="flex flex-wrap gap-3 p-3">
                      {filteredWorkspaceFiles.map((file, index) => {
                        const isImage = file.category === "image" && !!file.preview_url;
                        const imageUrl = resolveWorkspaceFileUrl(file.preview_url || file.download_url);
                        const ext = (file.extension || "").replace(/^\./, "").toUpperCase() || "FILE";
                        return (
                          <button
                            key={`${file.path || file.name}-${index}`}
                            className={`group w-[156px] shrink-0 text-left rounded-2xl border p-2 transition-all hover:-translate-y-0.5 hover:shadow-md ${getFileAccentClasses(file)} ${selectedWorkspacePath === file.path ? "ring-2 ring-blue-300 dark:ring-blue-800" : ""}`}
                            onClick={() => {
                              setSelectedWorkspacePath(file.path);
                              openPreview(file);
                            }}
                            onDoubleClick={() => {
                              setSelectedWorkspacePath(file.path);
                              openFullPreview(file);
                            }}
                            type="button"
                          >
                            <div className="aspect-square overflow-hidden rounded-xl bg-white/80 dark:bg-gray-950/70 border border-white/60 dark:border-gray-800 flex items-center justify-center">
                              {isImage ? (
                                <img
                                  src={imageUrl}
                                  alt={file.name}
                                  className="h-full w-full object-cover"
                                />
                              ) : file.category === "table" ? (
                                <div className="flex flex-col items-center justify-center text-emerald-700 dark:text-emerald-300">
                                  <FileSpreadsheet className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : ["json", "sqlite", "db"].includes((file.extension || "").replace(/^\./, "")) ? (
                                <div className="flex flex-col items-center justify-center text-amber-700 dark:text-amber-300">
                                  <FileJson className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : ["py", "sql", "js", "ts", "tsx", "jsx", "ipynb"].includes((file.extension || "").replace(/^\./, "")) ? (
                                <div className="flex flex-col items-center justify-center text-violet-700 dark:text-violet-300">
                                  <FileCode2 className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : file.category === "image" ? (
                                <div className="flex flex-col items-center justify-center text-blue-700 dark:text-blue-300">
                                  <FileImage className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              ) : (
                                <div className="flex flex-col items-center justify-center text-gray-700 dark:text-gray-300">
                                  <FileText className="h-9 w-9" />
                                  <span className="mt-2 text-[11px] font-medium">{ext}</span>
                                </div>
                              )}
                            </div>
                            <div className="px-1 pt-2">
                              <div className="truncate text-xs font-medium text-gray-900 dark:text-gray-100" title={file.path}>
                                {file.name}
                              </div>
                              <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400">
                                <span className="truncate">{formatFileSize(file.size)}</span>
                                <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px]">
                                  {isGeneratedWorkspaceFile(file)
                                    ? textLabels.generated
                                    : textLabels.uploaded}
                                </Badge>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full px-4 py-10 text-sm text-gray-500 dark:text-gray-400">
                      {textLabels.noFiles}
                    </div>
                  )}
                </Card>

                <Card className="hidden rounded-2xl border-gray-200/80 dark:border-gray-800/80 overflow-hidden">
                  <div className="border-b border-gray-200/80 dark:border-gray-800/80 px-4 py-3">
                    <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {uiLanguage === "zh" ? "最近生成文件" : "Generated Files"}
                    </div>
                  </div>
                  <div className="p-3 space-y-2">
                    {recentGeneratedFiles.length ? (
                      recentGeneratedFiles.map((file) => (
                        <button
                          key={`inspector-${file.path}`}
                          type="button"
                          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-900/60 ${
                            selectedWorkspacePath === file.path
                              ? "border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/20"
                              : "border-gray-200 dark:border-gray-800"
                          }`}
                          onClick={() => {
                            setSelectedWorkspacePath(file.path);
                            openPreview(file);
                          }}
                          onDoubleClick={() => {
                            setSelectedWorkspacePath(file.path);
                            openFullPreview(file);
                          }}
                        >
                          <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
                            {file.category === "image" && file.preview_url ? (
                              <img
                                src={resolveWorkspaceFileUrl(
                                  file.preview_url || file.download_url
                                )}
                                alt={file.name}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <FileText className="h-4 w-4 text-gray-500" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-xs font-medium text-gray-900 dark:text-gray-100">
                              {file.name}
                            </div>
                            <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                              {formatFileSize(file.size)}
                            </div>
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="px-1 py-2 text-sm text-gray-500 dark:text-gray-400">
                        {uiLanguage === "zh"
                          ? "还没有生成文件。"
                          : "No generated files yet."}
                      </div>
                    )}
                  </div>
                </Card>

              </div>
            </div>
          </ResizablePanel>

        </ResizablePanelGroup>
      </div>
        <Sheet open={showCodeEditor} onOpenChange={setShowCodeEditor}>
          <SheetContent side="right" className="w-[92vw] sm:max-w-3xl p-0 gap-0">
            <SheetHeader className="border-b border-gray-200 dark:border-gray-800 px-5 py-4">
              <div className="flex items-center justify-between gap-3 pr-8">
                <div>
                  <SheetTitle className="text-base">{uiLanguage === "zh" ? "代码工作台" : "Code Lab"}</SheetTitle>
                  <SheetDescription>
                    {uiLanguage === "zh"
                      ? "在这里修改生成代码、执行，并查看输出结果"
                      : "Edit generated code, run it, and inspect the output here."}
                  </SheetDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setCodeEditorContent("");
                      setCodeEditorOriginalCode("");
                      setSelectedCodeSection("");
                      setCodeExecutionResult("");
                      setCodeEditInstruction("");
                      setPendingCodeEdit(null);
                      setAppliedCodeEdit(null);
                      setShowCodeEditor(false);
                    }}
                  >
                    {uiLanguage === "zh" ? "关闭" : "Close"}
                  </Button>
                  <Button
                    size="sm"
                    onClick={executeCode}
                    disabled={!codeEditorContent || isExecutingCode || !!pendingCodeEdit}
                    className="bg-black text-white dark:bg-white dark:text-black"
                  >
                    {isExecutingCode
                      ? uiLanguage === "zh"
                        ? "运行中..."
                        : "Running..."
                      : uiLanguage === "zh"
                        ? "运行代码"
                        : "Run Code"}
                  </Button>
                </div>
              </div>
            </SheetHeader>

            <div className="flex-1 min-h-0 flex flex-col p-4 editor-container overflow-hidden bg-gray-50 dark:bg-gray-950">
              <div className="mb-3 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-3 dark:border-emerald-900/60 dark:bg-emerald-950/20">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-emerald-950 dark:text-emerald-100">
                      {uiLanguage === "zh" ? "自然语言修改代码" : "Natural-language code edit"}
                    </div>
                    <div className="text-xs text-emerald-700 dark:text-emerald-300">
                      {uiLanguage === "zh"
                        ? "输入修改意图，后端 LLM 会返回完整修改后的脚本。"
                        : "Describe the change; the backend LLM returns a complete revised script."}
                    </div>
                  </div>
                  {pendingCodeEdit && (
                    <div className="flex shrink-0 items-center gap-2">
                      <Button
                        size="sm"
                        onClick={confirmAiCodeEdit}
                        className="bg-emerald-700 text-white hover:bg-emerald-800"
                      >
                        {uiLanguage === "zh" ? "应用修改" : "Apply"}
                      </Button>
                      <Button size="sm" variant="outline" onClick={rollbackAiCodeEdit}>
                        {uiLanguage === "zh" ? "回滚预览" : "Rollback"}
                      </Button>
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Textarea
                    value={codeEditInstruction}
                    onChange={(event) => setCodeEditInstruction(event.target.value)}
                    placeholder={
                      uiLanguage === "zh"
                        ? "例如：把结果保存为 CSV，并为每个关键步骤补充中文注释"
                        : "Example: save the result as CSV and add comments for each key step"
                    }
                    rows={1}
                    className="h-12 min-h-12 min-w-0 resize-none bg-white/90 py-2 text-sm dark:bg-black/30 sm:flex-1"
                    disabled={isEditingCodeWithAi}
                  />
                  <Button
                    onClick={requestAiCodeEdit}
                    disabled={
                      isEditingCodeWithAi ||
                      !codeEditorContent.trim() ||
                      !codeEditInstruction.trim()
                    }
                    className="h-12 bg-emerald-700 text-white hover:bg-emerald-800 sm:w-28"
                  >
                    {isEditingCodeWithAi
                      ? uiLanguage === "zh"
                        ? "生成中..."
                        : "Editing..."
                      : uiLanguage === "zh"
                        ? "生成修改"
                        : "Generate"}
                  </Button>
                </div>
              </div>
              <div
                className="min-h-0 border border-gray-200 dark:border-gray-700 rounded-2xl overflow-hidden bg-white dark:bg-black flex flex-col"
                style={{ height: `${editorHeight}%` }}
              >
                <div className="bg-gray-50 dark:bg-gray-800 px-3 py-2 border-b border-gray-200 dark:border-gray-700 shrink-0 flex items-center justify-between">
                  <span className="text-xs text-gray-500 font-mono">python</span>
                  {selectedCodeSection && (
                    <span className="text-[11px] text-gray-400 truncate max-w-52">
                      {uiLanguage === "zh"
                        ? "来自最近选中的代码块"
                        : "From the latest selected code block"}
                    </span>
                  )}
                </div>
                <div className="flex-1 min-h-0 relative">
                  <Editor
                    height="100%"
                    defaultLanguage="python"
                    value={codeEditorContent}
                    onChange={handleCodeEditorChange}
                    theme={isDarkMode ? "vs-dark" : "light"}
                    options={{
                      fontSize: 14,
                      fontFamily:
                        "var(--font-mono), 'Courier New', monospace",
                      lineNumbers: "on",
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      automaticLayout: true,
                      tabSize: 4,
                      insertSpaces: true,
                      wordWrap: "on",
                      folding: true,
                      lineDecorationsWidth: 10,
                      lineNumbersMinChars: 3,
                      glyphMargin: false,
                      selectOnLineNumbers: true,
                      roundedSelection: false,
                      readOnly: false,
                      cursorStyle: "line",
                      smoothScrolling: true,
                      formatOnPaste: true,
                      formatOnType: true,
                      suggestOnTriggerCharacters: true,
                      acceptSuggestionOnEnter: "on",
                      tabCompletion: "on",
                      scrollbar: {
                        vertical: "visible",
                        verticalScrollbarSize: 10,
                      },
                    }}
                    loading={
                      <div className="flex items-center justify-center h-full">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                          <span className="text-sm">
                            {uiLanguage === "zh" ? "加载编辑器..." : "Loading editor..."}
                          </span>
                        </div>
                      </div>
                    }
                  />
                  {pendingCodeEdit && (
                    <div className="absolute inset-0 z-10 overflow-auto bg-white font-mono text-[13px] leading-5 dark:bg-black">
                      {pendingCodeEdit.diffRows.map((row) => (
                        <div
                          key={row.id}
                          className={
                            row.type === "added"
                              ? "flex min-w-max border-l-4 border-emerald-500 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/40 dark:text-emerald-100"
                              : row.type === "removed"
                                ? "flex min-w-max border-l-4 border-red-500 bg-red-50 text-red-950 dark:bg-red-950/40 dark:text-red-100"
                                : "flex min-w-max border-l-4 border-transparent text-gray-800 dark:text-gray-200"
                          }
                        >
                          <span className="w-12 shrink-0 select-none border-r border-gray-100 px-2 py-0.5 text-right text-gray-400 dark:border-gray-800">
                            {row.oldLineNumber ?? ""}
                          </span>
                          <span className="w-12 shrink-0 select-none border-r border-gray-100 px-2 py-0.5 text-right text-gray-400 dark:border-gray-800">
                            {row.newLineNumber ?? ""}
                          </span>
                          <span className="w-7 shrink-0 select-none px-2 py-0.5 text-center font-semibold">
                            {row.type === "added" ? "+" : row.type === "removed" ? "-" : " "}
                          </span>
                          <SyntaxHighlighter
                            language="python"
                            style={isDarkMode ? oneDark : oneLight}
                            PreTag="div"
                            CodeTag="span"
                            customStyle={{
                              margin: 0,
                              padding: "0.125rem 0.5rem",
                              flex: 1,
                              minWidth: 0,
                              overflow: "visible",
                              background: "transparent",
                              fontFamily: "inherit",
                              fontSize: "inherit",
                              lineHeight: "1.25rem",
                              whiteSpace: "pre",
                            }}
                            codeTagProps={{
                              style: {
                                display: "block",
                                fontFamily: "inherit",
                                whiteSpace: "pre",
                              },
                            }}
                          >
                            {row.content || " "}
                          </SyntaxHighlighter>
                        </div>
                      ))}
                      {pendingCodeEdit.diffRows.length === 0 && (
                        <div className="p-4 text-sm text-gray-500">
                          {uiLanguage === "zh" ? "没有代码差异" : "No code changes."}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div
                className="h-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 cursor-row-resize flex items-center justify-center group"
                onMouseDown={handleMouseDown}
              >
                <div className="w-8 h-1 bg-gray-300 dark:bg-gray-600 rounded group-hover:bg-gray-400 dark:group-hover:bg-gray-500"></div>
              </div>

              <div
                className="min-h-0 border border-gray-200 dark:border-gray-700 rounded-2xl overflow-hidden bg-white dark:bg-gray-900 flex flex-col"
                style={{ height: `${100 - editorHeight}%` }}
              >
                <div className="bg-gray-50 dark:bg-gray-800 px-3 py-2 border-b border-gray-200 dark:border-gray-700 shrink-0">
                  <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                    Output
                  </span>
                </div>
                <div className="flex-1 min-h-0 p-3 overflow-auto font-mono text-sm bg-white dark:bg-black text-gray-800 dark:text-gray-200">
                  {codeExecutionResult ? (
                    <div>
                      <div className="text-gray-500 dark:text-gray-400 mb-1">
                        $ python main.py
                      </div>
                      <pre className="whitespace-pre-wrap text-gray-800 dark:text-gray-200">
                        {codeExecutionResult}
                      </pre>
                      <div className="flex items-center mt-2">
                        <span className="text-gray-500 dark:text-gray-400">$</span>
                        <span className="w-2 h-4 bg-gray-400 dark:bg-gray-500 ml-1 animate-pulse"></span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-gray-400 dark:text-gray-500 italic">
                      {uiLanguage === "zh"
                        ? "运行代码后将在这里显示输出结果..."
                        : "Run the code to see the output here..."}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>

      {contextPos && contextTarget && (
        <div
          className="fixed z-50 bg-card border border-gray-200 dark:border-gray-700 rounded shadow-sm text-sm"
          style={{ left: contextPos.x, top: contextPos.y, minWidth: 180 }}
          onMouseLeave={closeContext}
        >
          {/* 生成文件专属：移动到普通文件区 */}
          {!contextTarget.is_dir &&
            contextTarget.path.startsWith("generated/") && (
              <button
                className="block w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={async () => {
                  await moveToDir(contextTarget.path, "");
                  closeContext();
                }}
              >
                移动到普通文件区
              </button>
            )}
          {!contextTarget.is_dir && (
            <button
              className="block w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
              onClick={() => {
                openNode(contextTarget);
                closeContext();
              }}
            >
              预览
            </button>
          )}
          {!contextTarget.is_dir && contextTarget.download_url && (
            <a
              className="block px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
              href={contextTarget.download_url}
              download={contextTarget.name}
              onClick={closeContext}
            >
              下载
            </a>
          )}
          <button
            className="block w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
            onClick={() => {
              copyToClipboard(contextTarget.path)
                .then((ok) =>
                  toast({
                    description: ok ? "已复制路径" : "复制失败",
                    variant: ok ? undefined : "destructive",
                  })
                )
                .catch(() =>
                  toast({ description: "复制失败", variant: "destructive" })
                );
              closeContext();
            }}
          >
            复制路径
          </button>
          {!contextTarget.is_dir && (
            <button
              className="block w-full text-left px-3 py-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
              onClick={() => {
                setDeleteConfirmPath(contextTarget.path);
                setDeleteIsDir(false);
              }}
            >
              删除文件
            </button>
          )}
          {contextTarget.is_dir && contextTarget.name === "generated" && (
            <button
              className="block w-full text-left px-3 py-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
              onClick={() => {
                setDeleteConfirmPath(contextTarget.path);
                setDeleteIsDir(true);
              }}
            >
              删除文件夹
            </button>
          )}
        </div>
      )}
      {/* 全局删除确认弹窗 */}
      {/* 右键移动操作已集成到主菜单顶部，移除单独浮层 */}

      {/* 全局删除确认弹窗 */}
      <AlertDialog
        open={!!deleteConfirmPath}
        onOpenChange={(o) => !o && setDeleteConfirmPath(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deleteIsDir ? "确认删除文件夹？" : "确认删除文件？"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deleteIsDir
                ? "此操作不可撤销，将删除该文件夹及其所有内容。"
                : "此操作不可撤销，将从 workspace 中移除此文件。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteConfirmPath(null)}>
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              onClick={async () => {
                if (deleteConfirmPath) {
                  if (deleteIsDir) {
                    await deleteDir(deleteConfirmPath);
                  } else {
                    await deleteFile(deleteConfirmPath);
                  }
                }
                setDeleteConfirmPath(null);
                closeContext();
              }}
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={isSampleDialogOpen} onOpenChange={setIsSampleDialogOpen}>
        <DialogContent className="flex max-h-[min(760px,calc(100vh-2rem))] flex-col overflow-hidden p-0 sm:max-w-3xl">
          <DialogHeader className="shrink-0 border-b border-gray-200 px-5 py-4 dark:border-gray-800">
            <DialogTitle>
              {uiLanguage === "zh" ? "加载示例数据" : "Load sample data"}
            </DialogTitle>
            <DialogDescription>
              {uiLanguage === "zh"
                ? "选择一个公开数据源和一个分析问题。"
                : "Choose a public dataset and an analysis question."}
            </DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {isSampleCatalogLoading ? (
              <div className="flex h-48 items-center justify-center text-sm text-gray-500">
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                {uiLanguage === "zh" ? "正在加载数据目录" : "Loading data catalog"}
              </div>
            ) : sampleCatalog.length ? (
              <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <section>
                  <h3 className="mb-2 text-xs font-semibold text-gray-600 dark:text-gray-300">
                    {uiLanguage === "zh" ? "数据源" : "Dataset"}
                  </h3>
                  <div className="space-y-2" role="radiogroup">
                    {sampleCatalog.map((dataset) => {
                      const active = dataset.id === selectedSampleId;
                      return (
                        <button
                          key={dataset.id}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          onClick={() => {
                            setSelectedSampleId(dataset.id);
                            setSelectedSampleQuestionId(dataset.questions[0].id);
                          }}
                          className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors ${
                            active
                              ? "border-blue-500 bg-blue-50 dark:border-blue-500 dark:bg-blue-950/30"
                              : "border-gray-200 hover:border-gray-300 hover:bg-gray-50 dark:border-gray-800 dark:hover:border-gray-700 dark:hover:bg-gray-900"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-semibold text-gray-900 dark:text-white">
                              {dataset.title[uiLanguage]}
                            </span>
                            <span className="shrink-0 text-[11px] text-gray-400">
                              {dataset.files.length} {uiLanguage === "zh" ? "个文件" : dataset.files.length === 1 ? "file" : "files"}
                            </span>
                          </div>
                          <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
                            {dataset.description[uiLanguage]}
                          </p>
                          <p className="mt-1 truncate text-[11px] text-gray-400" title={dataset.files.join(", ")}>
                            {dataset.files.join(", ")}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </section>

                <section>
                  <h3 className="mb-2 text-xs font-semibold text-gray-600 dark:text-gray-300">
                    {uiLanguage === "zh" ? "分析问题" : "Analysis question"}
                  </h3>
                  <div className="space-y-2" role="radiogroup">
                    {selectedSample?.questions.map((question) => {
                      const active = question.id === selectedSampleQuestionId;
                      return (
                        <button
                          key={question.id}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          onClick={() => setSelectedSampleQuestionId(question.id)}
                          className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors ${
                            active
                              ? "border-emerald-500 bg-emerald-50 dark:border-emerald-500 dark:bg-emerald-950/20"
                              : "border-gray-200 hover:border-gray-300 hover:bg-gray-50 dark:border-gray-800 dark:hover:border-gray-700 dark:hover:bg-gray-900"
                          }`}
                        >
                          <span className="text-sm font-semibold text-gray-900 dark:text-white">
                            {question.title[uiLanguage]}
                          </span>
                          <p className="mt-1 max-h-20 overflow-hidden whitespace-pre-line text-xs leading-5 text-gray-500 dark:text-gray-400">
                            {question.prompt[uiLanguage]}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                  {selectedSampleQuestion && (
                    <div className="mt-3 border-t border-gray-200 pt-3 dark:border-gray-800">
                      <div className="max-h-32 overflow-y-auto whitespace-pre-line text-xs leading-5 text-gray-600 dark:text-gray-300">
                        {selectedSampleQuestion.prompt[uiLanguage]}
                      </div>
                    </div>
                  )}
                </section>
              </div>
            ) : (
              <div className="flex h-48 items-center justify-center text-sm text-gray-500">
                {uiLanguage === "zh" ? "暂无可用示例数据" : "No sample datasets available"}
              </div>
            )}
          </div>

          <DialogFooter className="shrink-0 border-t border-gray-200 px-5 py-3 dark:border-gray-800">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsSampleDialogOpen(false)}
              disabled={isLoadingSample}
            >
              {uiLanguage === "zh" ? "取消" : "Cancel"}
            </Button>
            <Button
              type="button"
              onClick={() => void loadSampleData()}
              disabled={!selectedSampleQuestion || isLoadingSample}
            >
              {isLoadingSample ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Database className="h-4 w-4" />
              )}
              {uiLanguage === "zh" ? "加载并填入问题" : "Load and fill question"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>


      {/* 文件预览弹窗 */}
      <Dialog open={isPreviewOpen} onOpenChange={setIsPreviewOpen}>
        <DialogContent
          style={{
            width: "90vw",
            height: "90vh",
            maxWidth: "90vw",
            maxHeight: "90vh",
          }}
          className=" p-0 overflow-hidden flex flex-col"
        >
          <DialogHeader className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
            <DialogTitle className="text-sm font-medium truncate">
              {previewTitle}
            </DialogTitle>
          </DialogHeader>
          <div
            ref={previewScrollRef}
            className="w-full flex-1 min-h-0 overflow-auto"
          >
            {renderPreviewContent()}
          </div>
          <div className="absolute bottom-4 right-4">
            <Button onClick={handleDownload} size="sm" variant="outline">
              <Download className="h-4 w-4" />
              下载
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
