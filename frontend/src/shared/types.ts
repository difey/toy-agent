export type Mode = 'plan' | 'build';

export interface SessionSummary {
  index: number;
  is_current: boolean;
  title: string;
  messages: number;
  path: string;
  name: string;
  preview: string;
  tokens: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool';
  type: 'text' | 'tool_start' | 'tool_result';
  content: string;
  name?: string;
  title?: string;
  arguments?: Record<string, unknown>;
  flow_id?: string;
}

export interface CurrentInfo extends SessionSummary {
  mode: Mode;
  setup_needed: boolean;
  messages: ChatMessage[];
  diff_summaries?: DiffSummary[];
}

export interface QuestionOption {
  label: string;
  description?: string;
}

export interface QuestionDialog {
  header: string;
  question: string;
  options: QuestionOption[];
  multiple: boolean;
}

export interface PermissionRequest {
  tool: string;
  target: string;
  resolved_path: string;
  cwd: string;
}

export interface SubAgentEvent {
  type: 'reasoning' | 'tool_start' | 'tool_result' | 'error';
  content?: string;
  name?: string;
  title?: string;
  arguments?: Record<string, unknown>;
}

export interface SubAgent {
  id: string;
  status: 'running' | 'done' | 'error';
  events: SubAgentEvent[];
}

export interface SubAgentFlow {
  agents: SubAgent[];
  visible: boolean;
  done: boolean;
}

export interface SetupStatus {
  configured: boolean;
  model?: string | null;
  has_env_vars?: boolean;
}

export interface PlanDocResponse {
  exists: boolean;
  filename: string | null;
  content: string | null;
  modified: number | null;
  size?: number | null;
}

export interface PlanDocListItem {
  filename: string;
  modified: number;
  size: number;
}

export interface ModifiedFileItem {
  path: string;
  status: string;
}

export interface WorkspacePanelResponse {
  plan_docs: PlanDocListItem[];
  modified_files: ModifiedFileItem[];
}

export interface DiffSummary {
  segment_key: string;
  diff_filename: string;
  summary: {
    files_changed: number;
    insertions: number;
    deletions: number;
  };
}

export interface DiffFileEntry {
  path: string;
  status: 'modified' | 'added' | 'deleted';
  insertions: number;
  deletions: number;
  diff: string;
  binary?: boolean;
}

export interface DiffDetail {
  version: number;
  timestamp: string;
  session_file: string;
  message_segment_key: string;
  summary: {
    files_changed: number;
    insertions: number;
    deletions: number;
  };
  files: DiffFileEntry[];
}
