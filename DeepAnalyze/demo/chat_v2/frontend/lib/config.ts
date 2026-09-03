export const API_CONFIG = {
  // 走 Next.js /api 代理，同源请求自动携带认证 Cookie
  BACKEND_BASE_URL:
    process.env.NEXT_PUBLIC_BACKEND_URL || "/api",
  AI_API_BASE_URL:
    process.env.NEXT_PUBLIC_AI_API_URL || "http://localhost:8000",
  WEBSOCKET_URL: process.env.NEXT_PUBLIC_WEBSOCKET_URL || "ws://localhost:8001",
  ENDPOINTS: {
    CHAT_COMPLETIONS: "/chat/completions",
    CHAT_STOP: "/chat/stop",
    WORKSPACE_FILES: "/workspace/files",
    WORKSPACE_TREE: "/workspace/tree",
    WORKSPACE_PREVIEW: "/workspace/preview",
    WORKSPACE_DOWNLOAD_BUNDLE: "/workspace/download-bundle",
    WORKSPACE_UPLOAD: "/workspace/upload",
    WORKSPACE_SAMPLES: "/workspace/samples",
    WORKSPACE_SAMPLE: "/workspace/sample",
    WORKSPACE_CLEAR: "/workspace/clear",
    WORKSPACE_DELETE_FILE: "/workspace/file",
    WORKSPACE_UPLOAD_TO: "/workspace/upload-to",
    WORKSPACE_MOVE: "/workspace/move",
    WORKSPACE_DELETE_DIR: "/workspace/dir",
    EXECUTE_CODE: "/execute",
    EDIT_CODE: "/code/edit",
    EXPORT_REPORT: "/export/report",
    SESSION_STATE: "/session/state",
    SESSION_PENDING: "/session/pending",
    SESSION_MESSAGES: "/session/messages",
    SESSION_TASK: "/session/task",
    SESSIONS_LIST: "/sessions/list",
    SESSIONS_DELETE: "/sessions/delete",
    SESSIONS_RENAME: "/sessions/rename",
    AUTH_LOGIN: "/auth/login",
    AUTH_REGISTER: "/auth/register",
    AUTH_LOGOUT: "/auth/logout",
    AUTH_ME: "/auth/me",
    USER_MODEL_CONFIG: "/user/model-config",
    USER_MODEL_CONFIG_TEST: "/user/model-config/test",
  },
};

const normalizeBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, "");

const normalizeEndpoint = (endpoint: string) =>
  endpoint.startsWith("/") ? endpoint : `/${endpoint}`;

export const buildApiUrl = (
  endpoint: string,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  return `${normalizeBaseUrl(baseUrl)}${normalizeEndpoint(endpoint)}`;
};

export const buildApiUrlWithParams = (
  endpoint: string,
  params: Record<string, string | number | boolean | null | undefined>,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  const url = new URL(buildApiUrl(endpoint, baseUrl));
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return url.toString();
};

export const API_URLS = {
  WORKSPACE_FILES: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_FILES),
  WORKSPACE_TREE: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_TREE),
  WORKSPACE_PREVIEW: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_PREVIEW),
  WORKSPACE_DOWNLOAD_BUNDLE: buildApiUrl(
    API_CONFIG.ENDPOINTS.WORKSPACE_DOWNLOAD_BUNDLE
  ),
  WORKSPACE_UPLOAD: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_UPLOAD),
  WORKSPACE_SAMPLES: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_SAMPLES),
  WORKSPACE_SAMPLE: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_SAMPLE),
  WORKSPACE_CLEAR: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_CLEAR),
  WORKSPACE_DELETE_FILE: buildApiUrl(
    API_CONFIG.ENDPOINTS.WORKSPACE_DELETE_FILE
  ),
  WORKSPACE_UPLOAD_TO: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_UPLOAD_TO),
  WORKSPACE_MOVE: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_MOVE),
  WORKSPACE_DELETE_DIR: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_DELETE_DIR),
  EXECUTE_CODE: buildApiUrl(API_CONFIG.ENDPOINTS.EXECUTE_CODE),
  EDIT_CODE: buildApiUrl(API_CONFIG.ENDPOINTS.EDIT_CODE),
  EXPORT_REPORT: buildApiUrl(API_CONFIG.ENDPOINTS.EXPORT_REPORT),
  CHAT_COMPLETIONS: buildApiUrl(API_CONFIG.ENDPOINTS.CHAT_COMPLETIONS),
  CHAT_STOP: buildApiUrl(API_CONFIG.ENDPOINTS.CHAT_STOP),
  SESSION_STATE: buildApiUrl(API_CONFIG.ENDPOINTS.SESSION_STATE),
  SESSION_PENDING: buildApiUrl(API_CONFIG.ENDPOINTS.SESSION_PENDING),
  SESSION_MESSAGES: buildApiUrl(API_CONFIG.ENDPOINTS.SESSION_MESSAGES),
  SESSION_TASK: buildApiUrl(API_CONFIG.ENDPOINTS.SESSION_TASK),
  SESSIONS_LIST: buildApiUrl(API_CONFIG.ENDPOINTS.SESSIONS_LIST),
  SESSIONS_DELETE: buildApiUrl(API_CONFIG.ENDPOINTS.SESSIONS_DELETE),
  SESSIONS_RENAME: buildApiUrl(API_CONFIG.ENDPOINTS.SESSIONS_RENAME),
  AUTH_LOGIN: buildApiUrl(API_CONFIG.ENDPOINTS.AUTH_LOGIN),
  AUTH_REGISTER: buildApiUrl(API_CONFIG.ENDPOINTS.AUTH_REGISTER),
  AUTH_LOGOUT: buildApiUrl(API_CONFIG.ENDPOINTS.AUTH_LOGOUT),
  AUTH_ME: buildApiUrl(API_CONFIG.ENDPOINTS.AUTH_ME),
  USER_MODEL_CONFIG: buildApiUrl(API_CONFIG.ENDPOINTS.USER_MODEL_CONFIG),
  USER_MODEL_CONFIG_TEST: buildApiUrl(
    API_CONFIG.ENDPOINTS.USER_MODEL_CONFIG_TEST
  ),
};
