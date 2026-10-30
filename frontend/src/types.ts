export interface AuthState {
  initialized: boolean
  authenticated: boolean
  user: { id: number; username: string } | null
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
export interface Submission {
  id: string
  task_id: string
  version: number
  content: string
  evidence_notes: string
  created_at: string
  files: FileAttachment[]
  static_checks: StaticCheck[]
  latest_review: Review | null
  reviews?: Review[]
}
