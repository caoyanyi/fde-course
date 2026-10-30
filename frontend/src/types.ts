export interface User {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'learner'
  is_active: boolean
  must_change_password: boolean
  review_daily_limit: number
  material_daily_limit: number
  created_at?: string
  submission_count?: number
  completed_count?: number
}
export interface UsageLimit { used: number; limit: number; global_remaining: number }
export interface Usage { reviews: UsageLimit; materials: UsageLimit }
export interface AuthState {
  initialized: boolean
  authenticated: boolean
  user: User | null
  csrf_token: string | null
  setup_token_configured: boolean
}
export interface Resource { title: string; url: string }
export interface Rubric { id: string; title: string; weight: number; description: string }
export interface Task {
  id: string
  title: string
  hours: number
  summary: string
  objectives: string[]
  tutorial: { title: string; body: string }[]
  steps: { title: string; description: string }[]
  deliverables: string[]
  acceptanceCriteria: string[]
  rubric: Rubric[]
  resources: Resource[]
  prerequisites: string[]
  submissionPrompt: string
}
export interface Week {
  id: string
  number: number
  title: string
  summary: string
  goal: string
  hours: number
  tasks: Task[]
}
export interface Course {
  version: string
  title: string
  description: string
  audience: string
  totalWeeks: number
  totalHours: number
  weeks: Week[]
}
export interface Progress {
  status: 'not_started' | 'in_progress' | 'completed'
  actual_hours: number | null
  notes: string
  updated_at: string
}
export interface CourseState { course: Course; progress: Record<string, Progress> }
export interface AiSettings {
  base_url: string
  model: string
  api_key_set: boolean
  max_tokens: number
  material_max_tokens: number
  can_manage: boolean
  timeout_seconds: number
  temperature: number
  provider_label: string
}
export interface FileAttachment {
  id: string
  filename: string
  size: number
  extracted_chars: number
  truncated: boolean
  extraction_note: string
  download_url: string
}
export interface StaticCheck { name: string; status: 'passed' | 'warning' | 'failed'; message: string }
export interface ReviewReport {
  mode: 'ai_review'
  runtime_verified: boolean
  total_score: number
  max_score: number
  rubric: { id: string; title: string; weight: number; score: number; feedback: string; evidence: string[] }[]
  summary: string
  strengths: string[]
  improvements: string[]
  missing_evidence: string[]
  next_steps: string[]
  confidence: 'low' | 'medium' | 'high'
  verification_note: string
  evidence_truncated?: boolean
}
export interface Review {
  id: string
  submission_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  created_at: string
  completed_at: string | null
  error: string | null
  model: string
  report: ReviewReport | null
  usage: { input_tokens: number | null; output_tokens: number | null } | null
}
export type MaterialKind = 'scenario' | 'sample_data' | 'knowledge_docs' | 'test_cases' | 'starter_template'
export interface MaterialFile {
  id: string
  filename: string
  kind: MaterialKind
  description: string
  size: number
  sha256: string
  chars: number
  download_url: string
  content?: string
}
export interface MaterialPack {
  id: string
  task_id: string
  version: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  title: string
  summary: string
  how_to_use: string[]
  params: { scenario: string; difficulty: string; tech_stack: string; material_types: MaterialKind[]; requirements: string }
  created_at: string
  completed_at: string | null
  error: string | null
  model: string
  provider_label: string
  course_version: string
  synthetic: boolean
  runtime_verified: boolean
  verification_note: string
  prompt_version: string
  data_consent_at: string
  usage: { input_tokens?: number; output_tokens?: number } | null
  files: MaterialFile[]
  download_url: string | null
}
export interface MaterialPage { items: MaterialPack[]; total: number; limit: number; offset: number }
export interface Submission {
  id: string
  task_id: string
  version: number
  content: string
  evidence_notes: string
  material_pack_id: string | null
  created_at: string
  files: FileAttachment[]
  static_checks: StaticCheck[]
  latest_review: Review | null
  reviews?: Review[]
}
