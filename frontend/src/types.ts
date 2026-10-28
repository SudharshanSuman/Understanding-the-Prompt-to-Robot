// Shapes returned by the backend (backend/app, INTERFACE_CONTRACTS s3, s4, s7).

export type StageState =
  | "waiting"
  | "running"
  | "success"
  | "warning"
  | "failed"
  | "cancelled"
  | "needs_clarification";

export const STAGE_STATES: StageState[] = [
  "waiting", "running", "success", "warning", "failed", "cancelled", "needs_clarification",
];

export interface StageDef {
  id: string;
  label: string;
  group: string;
  ros: boolean; // needs ROS 2 (runs only when an executor is connected)
}

// Canonical 14 stages (ADR-009) and the 5 UI groups (INTERFACE_CONTRACTS s3.2).
export const STAGES: StageDef[] = [
  { id: "instruction", label: "Instruction", group: "NL Processing", ros: false },
  { id: "tokenization", label: "Tokenization", group: "NL Processing", ros: false },
  { id: "interpretation", label: "Interpretation", group: "NL Processing", ros: false },
  { id: "structured_task", label: "Structured task", group: "NL Processing", ros: false },
  { id: "schema_validation", label: "Schema validation", group: "Safety Interlock", ros: false },
  { id: "feasibility", label: "Feasibility", group: "Safety Interlock", ros: false },
  { id: "grounding", label: "Object / destination grounding", group: "Spatial & Kinematics", ros: true },
  { id: "planning_scene", label: "Planning scene", group: "Spatial & Kinematics", ros: true },
  { id: "ik", label: "Inverse kinematics", group: "Spatial & Kinematics", ros: true },
  { id: "planning", label: "Collision-aware planning", group: "Motion Planning", ros: true },
  { id: "trajectory_validation", label: "Trajectory validation", group: "Motion Planning", ros: true },
  { id: "execution", label: "ROS 2 execution", group: "Simulation & Verification", ros: true },
  { id: "simulation", label: "Gazebo simulation", group: "Simulation & Verification", ros: true },
  { id: "verification", label: "Verification", group: "Simulation & Verification", ros: true },
];

export interface PipelineEvent {
  event_id: string;
  stage: string;
  state: StageState;
  timestamp: string;
  message: string;
  data: Record<string, unknown>;
}

export interface TokenUnit {
  index: number;
  text: string;
  start: number;
  end: number;
  token_id: number | null;
  is_approximate: boolean;
  role: string | null;
}

export interface TokenizationResult {
  raw_text: string;
  tokens: TokenUnit[];
  tokenizer_name: string;
  is_live_model_tokenization: boolean;
  note?: string;
}

export interface ValidationIssue {
  code: string;
  field: string | null;
  message: string;
}

export interface Clarification {
  question: string;
  reason?: string;
  options: string[];
}

export interface TaskSummary {
  task_id: string;
  status: string;
  instruction: string;
  created_at: string;
  updated_at: string;
  provider: string | null;
}

export interface TaskDetail extends TaskSummary {
  task: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
  clarification: Clarification | null;
  report: { ok: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] } | null;
  stages: Record<string, StageState>;
  events: PipelineEvent[];
  error?: string;
}

export interface Health {
  status: string;
  ros2: string;
  gazebo: string;
  moveit: string;
  executor_connected: boolean;
}

export interface ProviderStatus {
  provider_id: string;
  name: string;
  kind: string;
  configured: boolean;
  available: boolean;
  model_name: string | null;
  detail: string;
  error_message: string | null;
}

export interface ExecutorStatus {
  name: string;
  connected: boolean;
  can_execute: boolean;
  e_stop_latched: boolean;
  controller_state: string;
  detail: string;
}

export interface StopReport {
  status: "e_stop_confirmed" | "e_stop_unverified";
  controller_state: string;
  max_joint_velocity: number | null;
  tolerance: number;
  source: string;
  requires_reset: boolean;
  detail: string;
}

// ROS-backed endpoints answer with this until the ROS 2 side is connected.
export interface RosStub {
  available: boolean;
  reason?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface Environment extends RosStub {
  perception_mode: string;
  objects: unknown[];
  scene_config: { objects: string[]; destinations: string[] };
}

export const FINAL_STATUSES = new Set([
  "needs_clarification", "failed", "cancelled", "validated_no_executor", "completed",
]);
