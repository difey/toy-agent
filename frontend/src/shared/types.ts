export type Mode = 'plan' | 'build';

export interface SessionSummary {
  id: string;
  is_current: boolean;
  title: string;
  messages: number;
  path: string;
  name: string;
  preview: string;
  tokens: number;
  created_at: number;
  updated_at: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool' | 'system' | 'diff_summary';
  type: 'text' | 'tool_start' | 'tool_result' | 'system' | 'diff_summary';
  content: string;
  name?: string;
  title?: string;
  arguments?: Record<string, unknown>;
  flow_id?: string;
  timestamp?: number;
  // diff_summary specific fields
  checkpoint_filename?: string;
  summary?: {
    files_changed: number;
    files: FileChangeItem[];
  };
  // Local-only marker: this user message is a follow-up interjection
  // submitted while an AI response is running (not yet in the session).
  pending?: boolean;
}

export interface CurrentInfo {
  app: {
    cwd: string;
    mode: Mode;
    status: 'idle' | 'running' | 'awaiting_permission' | 'awaiting_question' | 'error';
    setup_needed: boolean;
    active_model?: string | null;
    active_provider?: string | null;
    last_error?: string | null;
  };
  session_meta: SessionSummary;
  session_catalog: {
    sessions: SessionSummary[];
  };
  conversation: {
    timeline: ChatMessage[];
  };
  interaction: {
    pending_permission: (PermissionRequest & { request_id: string }) | null;
    pending_question: (QuestionDialog & { request_id: string }) | null;
  };
  workspace: WorkspacePanelResponse & {
    diff_summaries: DiffSummary[];
    active_diff: string | null;
    active_diff_files: ModifiedFileItem[];
  };
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
  request_id?: string;
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
  diff_summaries?: DiffSummary[];
  active_diff?: string | null;
  active_diff_files?: ModifiedFileItem[];
}

export interface DiffSummary {
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

export interface ProviderInfo {
  name: string;
  type: string;
  label: string;
  base_url: string | null;
  has_api_key: boolean;
  models: string[];
}

export interface ModelItem {
  provider: string;
  provider_type: string;
  provider_label: string;
  model: string;
  litellm_model: string;
  display: string;
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
  files_list?: ModifiedFileItem[];
}
