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
  role: 'user' | 'assistant' | 'tool' | 'system';
  type: 'text' | 'tool_start' | 'tool_result' | 'system';
  content: string;
  name?: string;
  title?: string;
  arguments?: Record<string, unknown>;
  flow_id?: string;
  timestamp?: number;
}

export interface CurrentInfo {
  index: number;
  is_current: boolean;
  title: string;
  path: string;
  name: string;
  preview: string;
  tokens: number;
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
  checkpoint_filename: string;
  summary: {
    files_changed: number;
    files: FileChangeItem[];
  };
}

export interface FileChangeItem {
  path: string;
  status: 'modified' | 'added' | 'deleted' | 'binary';
}

export interface CheckpointData {
  version: number;
  timestamp: string;
  git_commit_hash: string;
  session_file: string;
  message_segment_key: string;
  summary: {
    files_changed: number;
  };
  files: {
    modified: Record<string, string>;
    deleted: Record<string, string>;
    added: string[];
    binary: string[];
  };
}
