import type {
  ChatMessage,
  ModifiedFileItem,
  SessionSummary,
  SubAgentFlow,
} from '../../../shared/types';

const SEVEN_DAYS_SEC = 7 * 24 * 60 * 60;
const TIMESTAMP_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const MSG_TIMESTAMP_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

export interface FileTreeNode {
  name: string;
  path: string;
  type: 'folder' | 'file';
  status?: string;
  children?: FileTreeNode[];
}

export interface MessageSegment {
  key: string;
  userMessage: { message: ChatMessage; index: number } | null;
  foldingMessages: { message: ChatMessage; index: number }[];
  diffSummaryMessages: { message: ChatMessage; index: number }[];
  lastMessage: { message: ChatMessage; index: number } | null;
}

export function formatMsgTimestamp(ts: number | undefined | null): string {
  if (!ts || ts === 0) return '';
  return MSG_TIMESTAMP_FORMATTER.format(new Date(ts * 1000));
}

export function formatModifiedTimestamp(value: number | null | undefined): string {
  if (!value) {
    return '';
  }
  return TIMESTAMP_FORMATTER.format(new Date(value * 1000));
}

export function truncate(text: string, max: number): string {
  if (text.length > max) {
    return `${text.slice(0, max)}\n... (truncated)`;
  }
  return text;
}

export function cloneFlow(flow: SubAgentFlow): SubAgentFlow {
  return {
    ...flow,
    agents: flow.agents.map((agent) => ({ ...agent, events: [...agent.events] })),
  };
}

export function groupSessions(sessions: SessionSummary[]): { recent: SessionSummary[]; older: SessionSummary[] } {
  const now = Date.now() / 1000;
  const threshold = now - SEVEN_DAYS_SEC;

  const recent: SessionSummary[] = [];
  const older: SessionSummary[] = [];

  for (const s of sessions) {
    const ts = s.updated_at || s.created_at || 0;
    if (ts >= threshold) {
      recent.push(s);
    } else {
      older.push(s);
    }
  }

  return { recent, older };
}

export function buildModifiedFileTree(files: ModifiedFileItem[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];

  for (const file of files) {
    const segments = file.path.split('/').filter(Boolean);
    if (segments.length === 0) {
      continue;
    }

    let currentLevel = root;
    let currentPath = '';
    segments.forEach((segment, index) => {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      const isFile = index === segments.length - 1;
      let existing = currentLevel.find((node) => node.name === segment && node.type === (isFile ? 'file' : 'folder'));

      if (existing) {
        if (!isFile && existing.children) {
          currentLevel = existing.children;
        }
        return;
      }

      existing = isFile
        ? { name: segment, path: currentPath, type: 'file', status: file.status }
        : { name: segment, path: currentPath, type: 'folder', children: [] };
      currentLevel.push(existing);
      if (!isFile) {
        currentLevel = existing.children ?? [];
      }
    });
  }

  const normalize = (nodes: FileTreeNode[]): FileTreeNode[] =>
    nodes
      .map((node) => (
        node.type === 'folder'
          ? { ...node, children: normalize(node.children ?? []) }
          : node
      ))
      .sort((left, right) => {
        if (left.type !== right.type) {
          return left.type === 'folder' ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });

  return normalize(root);
}

export function collectFolderPaths(nodes: FileTreeNode[]): string[] {
  return nodes.flatMap((node) => (
    node.type === 'folder'
      ? [node.path, ...collectFolderPaths(node.children ?? [])]
      : []
  ));
}

export function buildMessageSegments(messages: ChatMessage[]): MessageSegment[] {
  if (messages.length === 0) return [];

  const segments: MessageSegment[] = [];
  const finalize = (key: string, userMsg: ChatMessage | null, msgs: ChatMessage[], startIdx: number) => {
    const mapped = msgs.map((m, i) => ({ message: m, index: startIdx + i }));
    const diffSummaryMessages = mapped.filter((m) => m.message.type === 'diff_summary');
    const nonDiffMessages = mapped.filter((m) => m.message.type !== 'diff_summary');

    if (nonDiffMessages.length === 0) {
      segments.push({
        key,
        userMessage: userMsg ? { message: userMsg, index: startIdx - 1 } : null,
        foldingMessages: [],
        diffSummaryMessages: mapped,
        lastMessage: null,
      });
    } else if (nonDiffMessages.length === 1) {
      segments.push({
        key,
        userMessage: userMsg ? { message: userMsg, index: startIdx - 1 } : null,
        foldingMessages: [],
        diffSummaryMessages,
        lastMessage: nonDiffMessages[0],
      });
    } else {
      segments.push({
        key,
        userMessage: userMsg ? { message: userMsg, index: startIdx - 1 } : null,
        foldingMessages: nonDiffMessages.slice(0, -1),
        diffSummaryMessages,
        lastMessage: nonDiffMessages[nonDiffMessages.length - 1],
      });
    }
  };

  let segUser: ChatMessage | null = null;
  let segMsgs: ChatMessage[] = [];
  let segStartIdx = 0;
  let segCount = 0;

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'system' && msg.type === 'system') {
      if (segUser !== null || segMsgs.length > 0) {
        finalize(`seg-${segCount++}`, segUser, segMsgs, segStartIdx);
      }
      segments.push({
        key: `seg-${segCount++}`,
        userMessage: null,
        foldingMessages: [],
        diffSummaryMessages: [],
        lastMessage: { message: msg, index: i },
      });
      segUser = null;
      segMsgs = [];
      segStartIdx = i + 1;
    } else if (msg.role === 'user' && msg.type === 'text') {
      if (segUser !== null || segMsgs.length > 0) {
        finalize(`seg-${segCount++}`, segUser, segMsgs, segStartIdx);
      }
      segUser = msg;
      segMsgs = [];
      segStartIdx = i + 1;
    } else {
      segMsgs.push(msg);
    }
  }
  if (segUser !== null || segMsgs.length > 0) {
    finalize(`seg-${segCount}`, segUser, segMsgs, segStartIdx);
  }

  return segments;
}
