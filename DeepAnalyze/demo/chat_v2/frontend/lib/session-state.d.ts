export function buildSessionStorageKey(sessionId: string): string;
export function normalizeInteractionMode(value: unknown): "auto" | "manual";
export function isAwaitingManualContinuation(interactionState: unknown): boolean;
export function getActiveAnalysisAssistantMessageIndexes(
  messages: any[]
): number[];
export function normalizeSessionMessages(
  messages: unknown[],
  now?: () => Date
): any[];
export function serializeSessionMessages(
  messages: any[]
): any[];
export function toServerMessages(
  messages: any[]
): any[];
export function toggleSelectedPath(
  currentPaths: Iterable<string>,
  path: string,
  selected: boolean
): Set<string>;
