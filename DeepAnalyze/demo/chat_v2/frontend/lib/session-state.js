function buildSessionStorageKey(sessionId) {
  return `chat_messages_v2:${String(sessionId || "default")}`;
}

function normalizeInteractionMode(value) {
  return value === "manual" ? "manual" : "auto";
}

function isAwaitingManualContinuation(interactionState) {
  return interactionState?.status === "awaiting_user";
}

function isManualInstructionMessage(message) {
  const sender = message?.sender || (message?.role === "user" ? "user" : "");
  return (
    sender === "user" &&
    String(message?.id || "").startsWith("manual-instruction-")
  );
}

function getActiveAnalysisAssistantMessageIndexes(messages) {
  if (!Array.isArray(messages)) return [];
  let analysisStartIndex = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const sender =
      message?.sender || (message?.role === "assistant" ? "ai" : message?.role);
    if (sender === "user" && !isManualInstructionMessage(message)) {
      analysisStartIndex = index + 1;
      break;
    }
  }

  const assistantIndexes = [];
  for (let index = analysisStartIndex; index < messages.length; index += 1) {
    const message = messages[index];
    const sender =
      message?.sender || (message?.role === "assistant" ? "ai" : message?.role);
    if (sender === "ai" && !message?.localOnly) assistantIndexes.push(index);
  }
  return assistantIndexes;
}

function normalizeSessionMessages(messages, now = () => new Date()) {
  if (!Array.isArray(messages)) return [];
  return messages
    .filter((message) => message && (message.role || message.sender))
    .map((message, index) => {
      const role = message.role || (message.sender === "user" ? "user" : "assistant");
      return {
        id: String(message.id || `restored-${index}`),
        content: String(message.content || ""),
        sender: role === "user" ? "user" : "ai",
        timestamp: message.timestamp ? new Date(message.timestamp) : now(),
        attachments: Array.isArray(message.attachments) ? message.attachments : undefined,
        ...(message.localOnly ? { localOnly: true } : {}),
      };
    });
}

function serializeSessionMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages.map((message) => ({
    ...message,
    timestamp:
      message.timestamp instanceof Date
        ? message.timestamp.toISOString()
        : new Date(message.timestamp).toISOString(),
  }));
}

function toServerMessages(messages) {
  return serializeSessionMessages(messages)
    .filter((message) => !message.localOnly)
    .map((message) => ({
      id: message.id,
      role: message.sender === "user" ? "user" : "assistant",
      content: message.content,
      timestamp: message.timestamp,
      attachments: message.attachments || [],
    }));
}

function toggleSelectedPath(currentPaths, path, selected) {
  const next = new Set(currentPaths || []);
  if (selected) next.add(path);
  else next.delete(path);
  return next;
}

module.exports = {
  buildSessionStorageKey,
  normalizeInteractionMode,
  isAwaitingManualContinuation,
  getActiveAnalysisAssistantMessageIndexes,
  normalizeSessionMessages,
  serializeSessionMessages,
  toServerMessages,
  toggleSelectedPath,
};
