<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api, json, setCsrfToken, errorMessage, currentSessionEpoch } from './api'
import type { AiSettings, AuthState, CourseState, MaterialPack, MaterialPage, Progress, Review, Submission, Usage, Week } from './types'
import Icon from './components/Icon.vue'
import MarkdownBlock from './components/MarkdownBlock.vue'
import ReviewCard from './components/ReviewCard.vue'
import PasswordForm from './components/PasswordForm.vue'
import UserManagement from './components/UserManagement.vue'
import MaterialsWorkspace from './components/MaterialsWorkspace.vue'

const auth = ref<AuthState | null>(null)
const booting = ref(true)
const bootError = ref('')
const workspaceLoading = ref(false)
const workspaceError = ref('')
const courseState = ref<CourseState | null>(null)
const aiSettings = ref<AiSettings | null>(null)
const submissions = ref<Submission[]>([])
const usage = ref<Usage | null>(null)
const submissionMaterials = ref<MaterialPack[]>([])
const materialListError = ref('')
const isAdmin = computed(() => auth.value?.user?.role === 'admin')
const sessionKey = computed(() => `${auth.value?.user?.id || 0}:${auth.value?.csrf_token || ''}`)
const hash = ref(window.location.hash || '#/dashboard')
const mobileNavOpen = ref(false)
const route = computed(() => hash.value.replace(/^#\/?/, '').split('/'))
const view = computed(() => ['dashboard', 'course', 'learn', 'submissions', 'materials', 'settings', 'account', 'users'].includes(route.value[0]) ? route.value[0] : 'dashboard')
const course = computed(() => courseState.value?.course)
const allTasks = computed(() => course.value?.weeks.flatMap(week => week.tasks.map(task => ({ task, week }))) || [])
const currentItem = computed(() => allTasks.value.find(item => item.task.id === (route.value[1] || '')))
const currentTask = computed(() => currentItem.value?.task)
const completedCount = computed(() => allTasks.value.filter(({ task }) => progressOf(task.id).status === 'completed').length)
const progressPercent = computed(() => allTasks.value.length ? Math.round(completedCount.value / allTasks.value.length * 100) : 0)
const nextItem = computed(() => allTasks.value.find(({ task }) => progressOf(task.id).status !== 'completed' && task.prerequisites.every(id => progressOf(id).status === 'completed')) || allTasks.value.find(({ task }) => progressOf(task.id).status !== 'completed'))
const recordedHours = computed(() => {
  const values = Object.values(courseState.value?.progress || {}).map(p => p.actual_hours).filter((v): v is number => typeof v === 'number')
  return values.length ? Number(values.reduce((a, b) => a + b, 0).toFixed(1)) : null
})
const reviewedCount = computed(() => submissions.value.filter(s => s.latest_review?.status === 'completed').length)
const expandedWeek = ref('')
const navigation = computed(() => [
  { id: 'dashboard', label: '学习概览', icon: 'dashboard' },
  { id: 'course', label: '课程路线', icon: 'book' },
  { id: 'submissions', label: '作业记录', icon: 'clipboard' },
  { id: 'materials', label: '我的素材库', icon: 'folder' },
  { id: 'settings', label: isAdmin.value ? '模型设置' : '模型服务', icon: 'settings' },
  { id: 'account', label: '我的账号', icon: 'user' },
  ...(isAdmin.value ? [{ id: 'users', label: '用户管理', icon: 'users' }] : []),
])
const pageLabel = computed(() => view.value === 'learn' ? '课程学习' : navigation.value.find(n => n.id === view.value)?.label || '学习概览')
const toast = ref<{ text: string; error: boolean } | null>(null)
let toastTimer: number | undefined
function notify(text: string, error = false) { if (!text) return; toast.value = { text, error }; window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => toast.value = null, 5500) }
function navigate(path: string) { window.location.hash = `#/${path}`; hash.value = `#/${path}`; mobileNavOpen.value = false; window.scrollTo({ top: 0, behavior: 'smooth' }) }
function onHashChange() { hash.value = window.location.hash || '#/dashboard'; mobileNavOpen.value = false }
function progressOf(id: string): Progress { return courseState.value?.progress[id] || { status: 'not_started', actual_hours: null, notes: '', updated_at: '' } }
const statusLabels = { not_started: '未开始', in_progress: '进行中', completed: '已完成' }
const reviewLabels = { queued: '排队中', running: '评审中', completed: '评审完成', failed: '评审失败' }
function taskTitle(id: string) { return allTasks.value.find(t => t.task.id === id)?.task.title || id }
function weekCompleted(week: Week) { return week.tasks.filter(t => progressOf(t.id).status === 'completed').length }
function dateText(value: string | null | undefined) { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function fileSize(n: number) { return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB` }
function safeLink(url: string) { try { const u = new URL(url); return ['https:', 'http:'].includes(u.protocol) ? u.href : '#' } catch { return '#' } }
function safeDownload(url: string) { return url.startsWith('/api/') ? url : '#' }

const authForm = reactive({ username: '', password: '', setup_token: '' })
const authBusy = ref(false)
const authError = ref('')
const revealPassword = ref(false)
async function bootstrap() {
  booting.value = true; bootError.value = ''
  try {
    auth.value = await api<AuthState>('/auth/status'); setCsrfToken(auth.value.csrf_token)
    if (auth.value.authenticated && !auth.value.user?.must_change_password) await loadWorkspace()
  } catch (e) { bootError.value = errorMessage(e) } finally { booting.value = false }
}
async function authenticate() {
  authBusy.value = true; authError.value = ''
  try {
    const setup = !auth.value?.initialized
    auth.value = await api<AuthState>(`/auth/${setup ? 'setup' : 'login'}`, { method: 'POST', body: json(setup ? authForm : { username: authForm.username, password: authForm.password }) })
    setCsrfToken(auth.value.csrf_token); authForm.password = ''; authForm.setup_token = ''
    if (!auth.value.user?.must_change_password) await loadWorkspace()
  } catch (e) { authError.value = errorMessage(e) } finally { authBusy.value = false }
}
function clearPrivateState() {
  courseState.value = null; aiSettings.value = null; submissions.value = []; usage.value = null
  submissionMaterials.value = []; selectedSubmission.value = null; activeReviewId.value = null; openingSubmissionId.value = null
  for (const key of Object.keys(drafts)) delete drafts[key]
  Object.assign(settingsForm, { provider_label: '', base_url: '', model: '', api_key: '', max_tokens: 3000, material_max_tokens: 6000, timeout_seconds: 90, temperature: 0.2, clear_api_key: false })
  Object.assign(progressDraft, { status: 'not_started', actual_hours: '', notes: '' })
  authForm.password = ''; authForm.setup_token = ''; authForm.username = ''; revealPassword.value = false
  aiConsent.value = false; testResult.value = null; expandedWeek.value = ''; historyFilter.value = 'all'
  submissionError.value = ''; settingsError.value = ''; reviewSyncError.value = ''; workspaceError.value = ''; materialListError.value = ''
  workspaceLoading.value = false; submissionBusy.value = false; reviewBusy.value = false; progressBusy.value = false; settingsBusy.value = false; testing.value = false
  toast.value = null; window.clearTimeout(toastTimer)
}
async function logout() {
  try { await api('/auth/logout', { method: 'POST' }); setCsrfToken(null); clearPrivateState(); await bootstrap() }
  catch (e) { notify(errorMessage(e), true) }
}
function onAuthExpired() {
  if (auth.value) auth.value = { ...auth.value, authenticated: false, user: null, csrf_token: null }
  setCsrfToken(null); clearPrivateState(); authError.value = '登录已失效，请重新登录。账号停用或密码重置也会使旧会话失效。'
}
async function passwordChanged(state: AuthState) {
  setCsrfToken(state.csrf_token); clearPrivateState(); auth.value = state
  navigate('dashboard'); await loadWorkspace(); notify('密码已更新，欢迎进入学习空间。')
}
async function loadUsage() {
  const epoch = currentSessionEpoch()
  try { const result = await api<Usage>('/usage'); if (epoch === currentSessionEpoch()) usage.value = result } catch (e) { if (epoch === currentSessionEpoch()) notify(errorMessage(e), true) }
}
async function loadTaskMaterials() {
  const id = currentTask.value?.id; const epoch = currentSessionEpoch()
  if (!id || !auth.value?.authenticated || auth.value.user?.must_change_password) { submissionMaterials.value = []; return }
  materialListError.value = ''
  try {
    const result = await api<MaterialPage>(`/materials?task_id=${encodeURIComponent(id)}&limit=200&offset=0`)
    if (id === currentTask.value?.id && epoch === currentSessionEpoch()) submissionMaterials.value = result.items.filter(p => p.status === 'completed')
  } catch (e) { if (id === currentTask.value?.id && epoch === currentSessionEpoch()) materialListError.value = errorMessage(e) }
}
async function materialsChanged() { await Promise.all([loadUsage(), loadTaskMaterials()]) }
async function useMaterial(pack: MaterialPack) {
  const epoch = currentSessionEpoch()
  if (pack.status !== 'completed') return
  if (currentTask.value?.id !== pack.task_id) { navigate(`learn/${pack.task_id}`); await nextTick() }
  if (epoch !== currentSessionEpoch()) return
  taskDraft(pack.task_id).material_pack_id = pack.id
  if (!submissionMaterials.value.some(p => p.id === pack.id)) submissionMaterials.value.unshift(pack)
  selectedSubmission.value = null; activeReviewId.value = null; lessonTab.value = 'submission'
  notify(`已关联素材 V${pack.version}。请完成实践后提交自己的成果。`)
}
async function loadWorkspace() {
  const epoch = currentSessionEpoch()
  if (!auth.value?.authenticated || auth.value.user?.must_change_password) return
  workspaceLoading.value = true; workspaceError.value = ''
  const results = await Promise.allSettled([api<CourseState>('/course'), fetchAllSubmissions(), api<AiSettings>('/settings/ai'), api<Usage>('/usage')])
  if (epoch !== currentSessionEpoch()) return
  if (results[0].status === 'fulfilled') { courseState.value = results[0].value; expandedWeek.value ||= nextItem.value?.week.id || course.value?.weeks[0]?.id || ''; syncProgressDraft() }
  else workspaceError.value = errorMessage(results[0].reason)
  if (results[1].status === 'fulfilled') submissions.value = results[1].value
  else workspaceError.value ||= errorMessage(results[1].reason)
  if (results[2].status === 'fulfilled') { aiSettings.value = results[2].value; syncSettings() }
  else workspaceError.value ||= errorMessage(results[2].reason)
  if (results[3].status === 'fulfilled') usage.value = results[3].value
  else workspaceError.value ||= errorMessage(results[3].reason)
  workspaceLoading.value = false
  void loadTaskMaterials()
}

const lessonTab = ref<'lesson' | 'materials' | 'submission' | 'history'>('lesson')
function onLessonTabKey(event: KeyboardEvent) {
  const tabs = ['lesson', 'materials', 'submission', 'history'] as const
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const index = tabs.indexOf(lessonTab.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length
  lessonTab.value = tabs[next]
  document.getElementById('tab-' + tabs[next])?.focus()
}
function onGlobalKey(event: KeyboardEvent) { if (event.key === 'Escape' && mobileNavOpen.value) { mobileNavOpen.value = false; (document.querySelector('.mobile-menu') as HTMLButtonElement | null)?.focus() } }
const progressDraft = reactive<{ status: Progress['status']; actual_hours: number | ''; notes: string }>({ status: 'not_started', actual_hours: '', notes: '' })
const progressBusy = ref(false)
function syncProgressDraft() { if (!currentTask.value) return; const p = progressOf(currentTask.value.id); progressDraft.status = p.status; progressDraft.actual_hours = p.actual_hours ?? ''; progressDraft.notes = p.notes || '' }
async function saveProgress(status?: Progress['status']) {
  const epoch = currentSessionEpoch()
  if (!currentTask.value || !courseState.value) return
  const taskId = currentTask.value.id
  progressBusy.value = true
  try {
    const payload = { status: status || progressDraft.status, actual_hours: progressDraft.actual_hours === '' ? null : Number(progressDraft.actual_hours), notes: progressDraft.notes }
    const result = await api<Progress>(`/tasks/${taskId}/progress`, { method: 'PATCH', body: json(payload) })
    if (epoch !== currentSessionEpoch()) return
    if (courseState.value) courseState.value.progress[taskId] = result
    if (currentTask.value?.id === taskId) syncProgressDraft()
    notify('学习记录已保存')
  } catch (e) { if (epoch === currentSessionEpoch()) notify(errorMessage(e), true) } finally { if (epoch === currentSessionEpoch()) progressBusy.value = false }
}

interface Draft { content: string; evidence_notes: string; files: File[]; material_pack_id: string }
const drafts = reactive<Record<string, Draft>>({})
function taskDraft(id: string) { return drafts[id] ||= { content: '', evidence_notes: '', files: [], material_pack_id: '' } }
const draft = computed(() => taskDraft(currentTask.value?.id || '__empty'))
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const submissionBusy = ref(false)
const submissionError = ref('')
const selectedSubmission = ref<Submission | null>(null)
const openingSubmissionId = ref<string | null>(null)
const activeReviewId = ref<string | null>(null)
const activeReview = computed<Review | null>(() => selectedSubmission.value?.reviews?.find(r => r.id === activeReviewId.value) || selectedSubmission.value?.latest_review || null)
const taskSubmissions = computed(() => submissions.value.filter(s => s.task_id === currentTask.value?.id))
const reviewBusy = ref(false)
const aiConsent = ref(false)
const historyFilter = ref('all')
const filteredSubmissions = computed(() => historyFilter.value === 'all' ? submissions.value : submissions.value.filter(s => s.task_id === historyFilter.value))
const allowedExtensions = new Set(['txt','md','py','php','js','ts','tsx','jsx','vue','json','csv','yaml','yml','sql','sh','html','css','log','pdf','docx'])
const acceptedFiles = [...allowedExtensions].map(e => `.${e}`).join(',')
function addFiles(list: FileList | File[] | null) {
  if (!list) return
  submissionError.value = ''
  const incoming = [...list]
  const combined = [...draft.value.files, ...incoming]
  if (combined.length > 5) { submissionError.value = '每次作业最多上传 5 个文件。'; return }
  for (const f of incoming) {
    if (!allowedExtensions.has(f.name.split('.').pop()?.toLowerCase() || '')) { submissionError.value = `暂不支持 ${f.name} 的文件格式，请上传文本、代码、PDF 或 DOCX。`; return }
    if (f.size > 2 * 1024 * 1024) { submissionError.value = `${f.name} 超过单文件 2 MB 限制。`; return }
  }
  if (combined.reduce((a, f) => a + f.size, 0) > 8 * 1024 * 1024) { submissionError.value = '本次附件总大小不能超过 8 MB。'; return }
  draft.value.files = combined
  if (fileInput.value) fileInput.value.value = ''
}
function onDrop(e: DragEvent) { dragOver.value = false; addFiles(e.dataTransfer?.files || null) }
async function submitAssignment() {
  const epoch = currentSessionEpoch()
  if (!currentTask.value) return
  if (!draft.value.content.trim() && !draft.value.files.length) { submissionError.value = '请填写作业内容或上传至少一个文件。'; return }
  const taskId = currentTask.value.id
  const submittedDraft = draft.value
  submissionBusy.value = true; submissionError.value = ''
  try {
    const data = new FormData(); data.append('content', submittedDraft.content); data.append('evidence_notes', submittedDraft.evidence_notes); if (submittedDraft.material_pack_id) data.append('material_pack_id', submittedDraft.material_pack_id); submittedDraft.files.forEach(f => data.append('files', f))
    const result = await api<Submission>(`/tasks/${taskId}/submissions`, { method: 'POST', body: data })
    if (epoch !== currentSessionEpoch()) return
    submissions.value = [result, ...submissions.value.filter(s => s.id !== result.id)]
    submittedDraft.content = ''; submittedDraft.evidence_notes = ''; submittedDraft.files = []; submittedDraft.material_pack_id = ''; if (fileInput.value) fileInput.value.value = ''
    if (currentTask.value?.id !== taskId) { navigate(`learn/${taskId}`); await nextTick() }
    if (epoch !== currentSessionEpoch()) return
    selectedSubmission.value = result; activeReviewId.value = null; aiConsent.value = false; lessonTab.value = 'submission'
    notify('作业已保存。现在可以申请 AI 评审。')
  } catch (e) { if (epoch === currentSessionEpoch()) submissionError.value = errorMessage(e) } finally { if (epoch === currentSessionEpoch()) submissionBusy.value = false }
}
async function fetchAllSubmissions() {
  const epoch = currentSessionEpoch()
  const first = await api<{ items: Submission[]; total: number }>('/submissions?limit=200&offset=0')
  const items = [...first.items]
  for (let offset = 200; offset < first.total; offset += 200) {
    if (epoch !== currentSessionEpoch()) return []
    const page = await api<{ items: Submission[] }>('/submissions?limit=200&offset=' + offset)
    items.push(...page.items)
  }
  return items
}
async function loadSubmissions() { const epoch = currentSessionEpoch(); const result = await fetchAllSubmissions(); if (epoch === currentSessionEpoch()) submissions.value = result }
async function openSubmission(id: string, jump = false) {
  const epoch = currentSessionEpoch()
  openingSubmissionId.value = id
  try {
    const result = await api<Submission>(`/submissions/${id}`)
    if (epoch !== currentSessionEpoch() || openingSubmissionId.value !== id) return
    if (jump) { navigate(`learn/${result.task_id}`); await nextTick() }
    if (epoch !== currentSessionEpoch() || openingSubmissionId.value !== id) return
    selectedSubmission.value = result; activeReviewId.value = result.latest_review?.id || null; aiConsent.value = false; lessonTab.value = 'submission'
  } catch (e) { if (epoch === currentSessionEpoch()) notify(errorMessage(e), true) } finally { if (epoch === currentSessionEpoch() && openingSubmissionId.value === id) openingSubmissionId.value = null }
}
function reviseSubmission() {
  if (!selectedSubmission.value || !currentTask.value) return
  draft.value.content = selectedSubmission.value.content; draft.value.evidence_notes = selectedSubmission.value.evidence_notes; draft.value.material_pack_id = selectedSubmission.value.material_pack_id || ''; selectedSubmission.value = null; activeReviewId.value = null; aiConsent.value = false
  notify('文字已带入新版本。需要保留的附件请重新上传。')
}
async function requestReview() {
  const epoch = currentSessionEpoch()
  if (!selectedSubmission.value || !aiConsent.value) return
  const submissionId = selectedSubmission.value.id
  reviewBusy.value = true
  try {
    const result = await api<{ review_id: string; status: string }>(`/submissions/${submissionId}/reviews`, { method: 'POST', body: json({ consent: true }) })
    if (epoch !== currentSessionEpoch()) return
    aiConsent.value = false
    void loadUsage()
    notify('评审已创建，结果会自动更新')
    try {
      await loadSubmissions()
      if (epoch !== currentSessionEpoch()) return
      if (selectedSubmission.value?.id === submissionId) {
        const detail = await api<Submission>(`/submissions/${submissionId}`)
        if (epoch === currentSessionEpoch() && selectedSubmission.value?.id === submissionId) { selectedSubmission.value = detail; activeReviewId.value = result.review_id }
      }
      reviewSyncError.value = ''
    } catch (e) { if (epoch === currentSessionEpoch()) reviewSyncError.value = errorMessage(e) }
  } catch (e) { if (epoch === currentSessionEpoch()) notify(errorMessage(e), true) } finally { if (epoch === currentSessionEpoch()) reviewBusy.value = false }
}
let polling = false
const reviewSyncError = ref('')
async function pollReviews() {
  const epoch = currentSessionEpoch()
  if (!auth.value?.authenticated || auth.value.user?.must_change_password || polling || document.hidden) return
  const pending = submissions.value.some(s => ['queued','running'].includes(s.latest_review?.status || '')) || ['queued','running'].includes(selectedSubmission.value?.latest_review?.status || '')
  if (!pending && !reviewSyncError.value) return
  polling = true
  try {
    await loadSubmissions()
    if (epoch !== currentSessionEpoch()) return
    reviewSyncError.value = ''
    if (selectedSubmission.value) {
      const id = selectedSubmission.value.id; const detail = await api<Submission>(`/submissions/${id}`)
      if (epoch === currentSessionEpoch() && selectedSubmission.value?.id === id) selectedSubmission.value = detail
    }
  } catch (e) { if (epoch === currentSessionEpoch()) reviewSyncError.value = errorMessage(e) } finally { polling = false }
}

const settingsForm = reactive({ provider_label: '', base_url: '', model: '', api_key: '', max_tokens: 3000, material_max_tokens: 6000, timeout_seconds: 90, temperature: 0.2, clear_api_key: false })
const settingsBusy = ref(false)
const testing = ref(false)
const settingsError = ref('')
const testResult = ref<{ ok: boolean; message: string; model: string; latency_ms: number } | null>(null)
function syncSettings() {
  if (!aiSettings.value) return
  const { provider_label, base_url, model, max_tokens, material_max_tokens, timeout_seconds, temperature } = aiSettings.value
  Object.assign(settingsForm, { provider_label, base_url, model, max_tokens, material_max_tokens, timeout_seconds, temperature, api_key: '', clear_api_key: false })
}
async function persistSettings(showToast = true) {
  const epoch = currentSessionEpoch()
  if (!isAdmin.value) return false
  settingsBusy.value = true; settingsError.value = ''; testResult.value = null
  try {
    const result = await api<AiSettings>('/settings/ai', { method: 'PUT', body: json(settingsForm) }); if (epoch !== currentSessionEpoch()) return false; aiSettings.value = result; syncSettings()
    if (showToast) notify('模型配置已保存')
    return true
  } catch (e) { if (epoch === currentSessionEpoch()) settingsError.value = errorMessage(e); return false } finally { if (epoch === currentSessionEpoch()) settingsBusy.value = false }
}
async function testConnection() {
  const epoch = currentSessionEpoch()
  if (!isAdmin.value) return
  testing.value = true; settingsError.value = ''; testResult.value = null
  try {
    if (!await persistSettings(false) || epoch !== currentSessionEpoch()) return
    const result = await api<{ ok: boolean; message: string; model: string; latency_ms: number }>('/settings/ai/test', { method: 'POST' })
    if (epoch !== currentSessionEpoch()) return
    testResult.value = result
    notify('模型服务连接成功')
  } catch (e) { if (epoch === currentSessionEpoch()) settingsError.value = errorMessage(e) } finally { if (epoch === currentSessionEpoch()) testing.value = false }
}
function beforeUnload(event: BeforeUnloadEvent) { if (Object.values(drafts).some(d => d.content.trim() || d.evidence_notes.trim() || d.files.length || d.material_pack_id)) event.preventDefault() }
watch(() => currentTask.value?.id, () => { lessonTab.value = 'lesson'; selectedSubmission.value = null; activeReviewId.value = null; submissionError.value = ''; aiConsent.value = false; submissionMaterials.value = []; syncProgressDraft(); void loadTaskMaterials() })
watch(lessonTab, tab => { if (tab === 'submission') void loadTaskMaterials() })
watch(view, name => { if (['account', 'materials', 'settings'].includes(name) && auth.value?.authenticated && !auth.value.user?.must_change_password) void loadUsage() })
let pollTimer: number | undefined
onMounted(() => { window.addEventListener('hashchange', onHashChange); window.addEventListener('fde:auth-expired', onAuthExpired); window.addEventListener('beforeunload', beforeUnload); window.addEventListener('keydown', onGlobalKey); void bootstrap(); pollTimer = window.setInterval(pollReviews, 3000) })
onUnmounted(() => { window.removeEventListener('hashchange', onHashChange); window.removeEventListener('fde:auth-expired', onAuthExpired); window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('keydown', onGlobalKey); window.clearInterval(pollTimer); window.clearTimeout(toastTimer) })
</script>

<template>
  <div v-if="booting" class="boot-screen"><div class="brand-mark">F</div><span class="spinner"></span><p>正在打开你的学习工作台…</p></div>
  <div v-else-if="bootError" class="boot-screen"><Icon name="alert" :size="32" /><h1>暂时无法连接学习服务</h1><p>{{ bootError }}</p><button class="button primary" @click="bootstrap">重新连接</button></div>
  <main v-else-if="!auth?.authenticated" class="auth-layout">
    <section class="auth-story"><div class="brand auth-brand"><span class="brand-mark">F</span><div><strong>FIELDWORK</strong><span>FDE 学习工作台</span></div></div><div class="auth-story-content"><span class="eyebrow">从一次练习，到独立交付</span><h1>带着问题学习，<br />带着作品前进。</h1><p>10 周实践路线。教程、作业与反馈，<br />在一个属于你的工作台中连续积累。</p><div class="auth-path"><span><i>01</i>学习与实践</span><span><i>02</i>提交与评审</span><span><i>03</i>改进与交付</span></div></div><div class="auth-footer">你的课程、作业与进度保存在这台服务器。</div></section>
    <section class="auth-form-side"><div class="auth-card"><span class="small-tag">{{ auth?.initialized ? '继续你的学习' : '首次使用' }}</span><h2>{{ auth?.initialized ? '欢迎回来' : '创建你的学习账号' }}</h2><p class="muted">{{ auth?.initialized ? '登录后继续课程、查看作业与评审结果。' : '首次创建的账号拥有管理权限，可在登录后为其他学习者开通账号。' }}</p><form @submit.prevent="authenticate"><label for="username">用户名</label><input id="username" v-model="authForm.username" name="username" autocomplete="username" placeholder="例如 ethan" required minlength="3" maxlength="40" pattern="[A-Za-z0-9_-]+" /><small v-if="!auth?.initialized" class="field-help">3–40 位英文字母、数字、下划线或短横线。</small><label for="password">密码</label><div class="password-field"><input id="password" v-model="authForm.password" :type="revealPassword ? 'text' : 'password'" :autocomplete="auth?.initialized ? 'current-password' : 'new-password'" placeholder="至少 12 个字符" required minlength="12" maxlength="128" /><button type="button" class="password-toggle" @click="revealPassword = !revealPassword">{{ revealPassword ? '隐藏' : '显示' }}</button></div><template v-if="!auth?.initialized"><label for="setupToken">部署初始化口令</label><input id="setupToken" v-model="authForm.setup_token" type="password" autocomplete="off" placeholder="服务器 APP_SETUP_TOKEN" :required="auth?.setup_token_configured" /><small class="field-help">由部署者在服务器配置中设置，只用于首次创建账号。</small><div v-if="!auth?.setup_token_configured" class="inline-note"><Icon name="info" :size="16" /><span>服务器尚未配置初始化口令，请先完成部署配置。</span></div></template><p v-if="authError" class="form-error" role="alert">{{ authError }}</p><button class="button primary full" :disabled="authBusy || (!auth?.initialized && !auth?.setup_token_configured)"><span v-if="authBusy" class="spinner small"></span>{{ authBusy ? '正在处理…' : auth?.initialized ? '登录工作台' : '创建账号并开始' }}<Icon v-if="!authBusy" name="arrow" :size="18" /></button></form><p class="auth-note"><Icon name="lock" :size="14" />账号由管理员创建，模型服务由管理员统一配置。</p></div></section>
  </main>
  <main v-else-if="auth.user?.must_change_password" class="password-gate"><a href="#/dashboard" class="brand"><span class="brand-mark">F</span><div><strong>FIELDWORK</strong><span>FDE 学习工作台</span></div></a><PasswordForm :key="sessionKey" required-change @changed="passwordChanged" /><button class="text-link" @click="logout"><Icon name="logout" :size="16" />退出当前账号</button></main>
  <div v-else class="app-shell" :key="sessionKey">
    <div v-if="mobileNavOpen" class="nav-scrim" @click="mobileNavOpen = false"></div>
    <aside class="sidebar" :class="{ open: mobileNavOpen }"><a href="#/dashboard" class="brand"><span class="brand-mark">F</span><div><strong>FIELDWORK</strong><span>FDE 学习工作台</span></div></a><span class="nav-heading">我的工作台</span><nav aria-label="主导航"><a v-for="item in navigation" :key="item.id" :href="`#/${item.id}`" :class="{ active: view === item.id || (view === 'learn' && item.id === 'course') }" :aria-current="view === item.id || (view === 'learn' && item.id === 'course') ? 'page' : undefined"><Icon :name="item.icon" /><span>{{ item.label }}</span><span v-if="item.id === 'submissions' && submissions.length" class="nav-count">{{ submissions.length }}</span></a></nav><div class="sidebar-course"><div class="sidebar-course-top"><Icon name="target" :size="18" /><span>独立交付训练</span></div><p>{{ completedCount }} / {{ allTasks.length }} 项实践已完成</p><div class="progress-track"><i :style="{ width: `${progressPercent}%` }"></i></div><small>{{ course?.totalWeeks || 10 }} 周课程 · {{ course?.totalHours || 200 }} 小时核心计划</small></div><div class="sidebar-bottom"><div class="profile"><span class="avatar">{{ auth.user?.username?.slice(0,1).toUpperCase() || 'F' }}</span><div><strong>{{ auth.user?.display_name || auth.user?.username }}</strong><span>{{ isAdmin ? '管理员 · 独立学习空间' : '学习者 · 独立学习空间' }}</span></div><button class="icon-button" aria-label="退出登录" title="退出登录" @click="logout"><Icon name="logout" :size="18" /></button></div></div></aside>
    <div class="workspace"><header class="topbar"><div class="topbar-left"><button class="icon-button mobile-menu" aria-label="打开导航" :aria-expanded="mobileNavOpen" @click="mobileNavOpen = !mobileNavOpen"><Icon name="menu" /></button><span>我的学习空间</span><Icon name="chevron" :size="14" /><strong>{{ pageLabel }}</strong></div><button class="model-indicator" :class="{ connected: aiSettings?.api_key_set }" @click="navigate('settings')"><i></i>{{ aiSettings?.api_key_set ? '模型已配置' : isAdmin ? '配置 AI 服务' : '模型未配置' }}<Icon name="chevron" :size="14" /></button></header>
      <main id="main-content" class="main-content"><div v-if="openingSubmissionId" class="loading-notice" role="status"><span class="spinner small"></span>正在读取作业记录…</div><div v-if="reviewSyncError" class="inline-note poll-notice" role="status"><Icon name="info" :size="17" /><span>评审状态暂未同步：{{ reviewSyncError }} 页面将自动重试。</span><button class="text-link" @click="pollReviews">立即重试</button></div>
        <div v-if="workspaceError" class="error-box workspace-alert" role="alert"><Icon name="alert" /><div><strong>部分内容未能加载</strong><p>{{ workspaceError }}</p></div><button class="button subtle" @click="loadWorkspace">重试</button></div>
        <div v-if="workspaceLoading && !course" class="content-loading"><span class="spinner"></span><p>正在读取课程与学习记录…</p></div>

        <template v-else-if="view === 'dashboard' && course">
          <header class="page-heading"><div><span class="eyebrow">把学习落实到每一次实践</span><h1>你的下一步</h1><p>循着一条清晰的路线，积累能演示、能验证、能交付的作品。</p></div><a href="#/course" class="button secondary">查看完整课程<Icon name="arrow" :size="17" /></a></header>
          <section class="dashboard-hero"><div class="next-task-card"><div class="hero-meta"><span class="pill dark">{{ nextItem ? `第 ${String(nextItem.week.number).padStart(2,'0')} 周` : '全部课程已完成' }}</span><span>{{ nextItem?.week.title || '继续完善你的交付案例' }}</span></div><h2>{{ nextItem?.task.title || '把这份成果，带到真实项目中' }}</h2><p>{{ nextItem?.task.summary || '全部实践任务已经标记完成。你可以继续查看评审、迭代作品，并补充实际交付证据。' }}</p><div class="hero-bottom"><a :href="nextItem ? `#/learn/${nextItem.task.id}` : '#/submissions'" class="button primary">{{ nextItem ? '进入本次实践' : '查看我的作品' }}<Icon name="arrow" :size="18" /></a><span v-if="nextItem" class="duration"><Icon name="clock" :size="16" />建议投入 {{ nextItem.task.hours }} 小时</span></div><div class="hero-decoration" aria-hidden="true"><span class="deco-code">&lt;/&gt;</span><div class="deco-line"></div><span class="deco-small">LEARN<br />BY DOING</span></div></div><div class="delivery-card"><span class="eyebrow">这段旅程的目的地</span><Icon name="folder" :size="31" /><h3>一份完整的<br />AI 项目交付案例</h3><p>从需求说明到上线验收，把工程能力变成可展示的服务。</p><div><span>需求</span><span>开发</span><span>验证</span><span>交付</span></div></div></section>
          <section class="stats-grid" aria-label="学习统计"><article class="stat-card"><div class="stat-icon"><Icon name="checkcircle" /></div><div><span>实践完成</span><strong>{{ completedCount }}<small> / {{ allTasks.length }}</small></strong></div><span class="stat-detail">{{ progressPercent }}%</span></article><article class="stat-card"><div class="stat-icon"><Icon name="clock" /></div><div><span>实际投入</span><strong>{{ recordedHours ?? '—' }}<small v-if="recordedHours !== null"> 小时</small></strong></div><span class="stat-detail">{{ recordedHours === null ? '等待你的记录' : '来自课时记录' }}</span></article><article class="stat-card"><div class="stat-icon"><Icon name="clipboard" /></div><div><span>作业提交</span><strong>{{ submissions.length }}<small> 个版本</small></strong></div><span class="stat-detail">{{ reviewedCount }} 个已评审</span></article></section>
          <div class="dashboard-columns"><section class="panel journey-panel"><div class="section-heading"><div><span class="eyebrow">循序渐进，完成交付</span><h2>你的 10 周路线</h2></div><a href="#/course" class="text-link">全部课时<Icon name="arrow" :size="15" /></a></div><button v-for="week in course.weeks" :key="week.id" class="journey-row" :class="{ current: week.id === nextItem?.week.id, done: weekCompleted(week) === week.tasks.length }" @click="expandedWeek = week.id; navigate('course')"><span class="week-number"><Icon v-if="weekCompleted(week) === week.tasks.length" name="check" :size="17" /><template v-else>{{ String(week.number).padStart(2,'0') }}</template></span><span class="journey-label"><strong>{{ week.title }}</strong><small>{{ week.goal }}</small></span><span class="journey-status">{{ weekCompleted(week) }}/{{ week.tasks.length }}</span><Icon name="chevron" :size="17" /></button></section><div class="dashboard-side"><section class="panel submissions-preview"><div class="section-heading"><h2>最近的作业</h2><a href="#/submissions" class="text-link">全部<Icon name="arrow" :size="15" /></a></div><template v-if="submissions.length"><button v-for="s in submissions.slice(0,3)" :key="s.id" class="recent-submission" @click="openSubmission(s.id,true)"><span class="file-icon"><Icon name="file" :size="18" /></span><span><strong>{{ taskTitle(s.task_id) }}</strong><small>版本 {{ s.version }} · {{ dateText(s.created_at) }}</small></span><span class="submission-score" v-if="s.latest_review?.report">{{ s.latest_review.report.total_score }}<small>分</small></span><Icon v-else name="chevron" :size="15" /></button></template><div v-else class="small-empty"><span class="empty-icon"><Icon name="clipboard" :size="24" /></span><h3>第一份作品，从这里开始</h3><p>完成课时实践后提交作业，版本与反馈会一直保留。</p><a v-if="nextItem" :href="`#/learn/${nextItem.task.id}`" class="text-link">开始第一项实践<Icon name="arrow" :size="15" /></a></div></section><section class="ai-note-card"><Icon name="sparkles" :size="23" /><h3>{{ aiSettings?.api_key_set ? '让 AI 帮你复盘' : '连接你的 AI 服务' }}</h3><p>评审会对照课时标准，给出建议分、引用证据和下一步修改建议。</p><a href="#/settings" class="text-link">{{ aiSettings?.api_key_set ? '查看模型服务' : isAdmin ? '设置第三方模型' : '查看服务状态' }}<Icon name="arrow" :size="15" /></a><small>评审基于提交材料，实际运行由你验证。</small></section></div></div>
        </template>

        <template v-else-if="view === 'course' && course"><header class="page-heading"><div><span class="eyebrow">{{ course.totalWeeks }} 周 · {{ course.totalHours }} 小时核心实践</span><h1>课程路线</h1><p>每一周都有明确的产物。按自己的节奏学习，完成后留下证据。</p></div><span class="pill outline">已完成 {{ completedCount }} / {{ allTasks.length }}</span></header><div class="course-list"><section v-for="week in course.weeks" :key="week.id" class="week-card" :class="{ expanded: expandedWeek === week.id }"><button class="week-card-heading" :aria-expanded="expandedWeek === week.id" @click="expandedWeek = expandedWeek === week.id ? '' : week.id"><span class="week-label">W{{ String(week.number).padStart(2,'0') }}</span><span class="week-card-title"><strong>{{ week.title }}</strong><small>{{ week.summary }}</small></span><span class="week-hours"><Icon name="clock" :size="15" />{{ week.hours }} 小时</span><span class="week-completion">{{ weekCompleted(week) }} / {{ week.tasks.length }}</span><Icon :name="expandedWeek === week.id ? 'down' : 'chevron'" :size="18" /></button><div v-if="expandedWeek === week.id" class="week-card-body"><p class="week-goal"><Icon name="target" :size="17" /><span>本周目标：{{ week.goal }}</span></p><a v-for="(task,index) in week.tasks" :key="task.id" :href="`#/learn/${task.id}`" class="task-row"><span class="task-sequence" :class="progressOf(task.id).status"><Icon v-if="progressOf(task.id).status === 'completed'" name="check" :size="16" /><template v-else>{{ index + 1 }}</template></span><span class="task-row-title"><strong>{{ task.title }}</strong><small>{{ task.summary }}</small></span><span class="status-pill" :class="progressOf(task.id).status">{{ statusLabels[progressOf(task.id).status] }}</span><span class="task-hours">{{ task.hours }}h</span><Icon name="arrow" :size="17" /></a></div></section></div></template>

        <template v-else-if="view === 'learn' && currentTask && currentItem"><a href="#/course" class="back-link"><Icon name="arrowleft" :size="16" />返回课程路线</a><header class="lesson-heading"><div class="lesson-meta"><span class="pill outline">第 {{ String(currentItem.week.number).padStart(2,'0') }} 周</span><span>{{ currentItem.week.title }}</span><span class="duration"><Icon name="clock" :size="15" />{{ currentTask.hours }} 小时</span></div><h1>{{ currentTask.title }}</h1><p>{{ currentTask.summary }}</p></header><div class="lesson-layout"><div class="lesson-main"><div class="tabs" role="tablist" aria-label="课时内容" @keydown="onLessonTabKey"><button id="tab-lesson" :class="{ active: lessonTab === 'lesson' }" role="tab" :tabindex="lessonTab === 'lesson' ? 0 : -1" :aria-selected="lessonTab === 'lesson'" @click="lessonTab = 'lesson'"><Icon name="book" :size="17" />教程与实践</button><button id="tab-materials" :class="{ active: lessonTab === 'materials' }" role="tab" :aria-selected="lessonTab === 'materials'" :tabindex="lessonTab === 'materials' ? 0 : -1" @click="lessonTab = 'materials'"><Icon name="folder" :size="17" />练习素材</button><button id="tab-submission" :class="{ active: lessonTab === 'submission' }" role="tab" :tabindex="lessonTab === 'submission' ? 0 : -1" :aria-selected="lessonTab === 'submission'" @click="lessonTab = 'submission'"><Icon name="upload" :size="17" />提交与评审</button><button id="tab-history" :class="{ active: lessonTab === 'history' }" role="tab" :tabindex="lessonTab === 'history' ? 0 : -1" :aria-selected="lessonTab === 'history'" @click="lessonTab = 'history'"><Icon name="clock" :size="17" />提交历史<span v-if="taskSubmissions.length" class="tab-count">{{ taskSubmissions.length }}</span></button></div>
          <div v-if="lessonTab === 'lesson'" class="lesson-sections" role="tabpanel"><section class="panel objectives-panel"><div class="section-heading"><h2><Icon name="target" :size="21" />完成后，你将能够</h2></div><ul class="check-list"><li v-for="(item,i) in currentTask.objectives" :key="i"><span><Icon name="check" :size="15" /></span>{{ item }}</li></ul></section><section v-for="(section,index) in currentTask.tutorial" :key="index" class="panel tutorial-panel"><div class="tutorial-heading"><span>{{ String(index + 1).padStart(2,'0') }}</span><h2>{{ section.title }}</h2></div><MarkdownBlock :content="section.body" /></section><section class="panel"><div class="section-heading"><h2>动手实践</h2><span class="subtle-tag">{{ currentTask.steps.length }} 个步骤</span></div><ol class="steps-list"><li v-for="(step,i) in currentTask.steps" :key="i"><span class="step-number">{{ i + 1 }}</span><div><h3>{{ step.title }}</h3><p>{{ step.description }}</p></div></li></ol></section><section class="panel"><div class="section-heading"><h2>本次需要交付什么</h2><Icon name="folder" /></div><ul class="deliverables"><li v-for="(item,i) in currentTask.deliverables" :key="i"><Icon name="file" :size="17" /><span>{{ item }}</span></li></ul><div class="lesson-cta"><p>准备好材料后，提交一个版本并获取反馈。</p><button class="button primary" @click="lessonTab = 'submission'">提交本次作业<Icon name="arrow" :size="17" /></button></div></section></div>
          <MaterialsWorkspace v-else-if="lessonTab === 'materials'" :key="`${sessionKey}:${currentTask.id}`" :tasks="allTasks.map(item => item.task)" :task-id="currentTask.id" :model-ready="Boolean(aiSettings?.api_key_set && aiSettings?.model)" :provider-label="aiSettings?.provider_label || ''" :usage="usage" @changed="materialsChanged" @select="useMaterial" />
          <div v-else-if="lessonTab === 'submission'"  class="lesson-sections" role="tabpanel"><template v-if="!selectedSubmission"><section class="panel submission-form-panel"><div class="section-heading"><div><span class="eyebrow">保存你的实践成果</span><h2>提交一个新版本</h2></div><Icon name="upload" :size="23" /></div><div class="submission-prompt"><strong>本次提交提示</strong><p>{{ currentTask.submissionPrompt }}</p></div><form @submit.prevent="submitAssignment"><label for="assignment-material">关联练习素材 <span class="optional">选填</span></label><select id="assignment-material" v-model="draft.material_pack_id"><option value="">不关联素材</option><option v-if="draft.material_pack_id && !submissionMaterials.some(p => p.id === draft.material_pack_id)" :value="draft.material_pack_id">已选择的素材包</option><option v-for="pack in submissionMaterials" :key="pack.id" :value="pack.id">V{{ pack.version }} · {{ pack.title }}</option></select><small class="field-help">只显示本课已完成的素材包。素材作为练习背景；评分依据你提交的成果和证据。</small><div v-if="materialListError" class="inline-note">{{ materialListError }}<button type="button" class="text-link" @click="loadTaskMaterials">重新加载</button></div><button type="button" class="text-link material-entry" @click="lessonTab = 'materials'"><Icon name="sparkles" :size="15" />先生成或查看本课素材</button><label for="assignment-content">作业内容与实现说明</label><textarea id="assignment-content" v-model="draft.content" rows="11" maxlength="60000" placeholder="说明你做了什么、如何实现，以及遇到了哪些问题。可以直接粘贴关键代码、文档或评测结果。"></textarea><div class="input-meta"><span>支持纯文本与 Markdown 内容</span><span>{{ draft.content.length.toLocaleString() }} / 60,000</span></div><label for="assignment-evidence">运行证据与补充说明 <span class="optional">选填</span></label><textarea id="assignment-evidence" v-model="draft.evidence_notes" rows="4" maxlength="10000" placeholder="描述运行环境、验证命令、实际输出、失败案例和修复过程。链接可作补充；AI 不会自动拉取外部仓库。"></textarea><label>附件</label><div class="upload-zone" :class="{ dragging: dragOver }" @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false" @drop.prevent="onDrop"><Icon name="upload" :size="26" /><p>拖入文件，或 <button type="button" class="inline-link" @click="fileInput?.click()">选择文件</button></p><small>代码、文本、PDF、DOCX · 最多 5 个 · 单个 2 MB · 总计 8 MB</small><small>PDF 仅提取前 30 页可复制文字，DOCX 仅提取正文；不读取图片或扫描件。</small><input ref="fileInput" type="file" multiple :accept="acceptedFiles" class="visually-hidden" aria-label="上传作业附件" @change="addFiles(($event.target as HTMLInputElement).files)" /></div><ul v-if="draft.files.length" class="file-list"><li v-for="(file,index) in draft.files" :key="`${file.name}-${index}`"><Icon name="file" :size="18" /><span>{{ file.name }}<small>{{ fileSize(file.size) }}</small></span><button type="button" class="icon-button" :aria-label="`移除 ${file.name}`" @click="draft.files.splice(index,1)"><Icon name="close" :size="16" /></button></li></ul><p v-if="submissionError" class="form-error" role="alert">{{ submissionError }}</p><div class="form-actions"><p>保存作业后，可单独发起 AI 评审。</p><button class="button primary" :disabled="submissionBusy"><span v-if="submissionBusy" class="spinner small"></span>{{ submissionBusy ? '正在保存…' : '提交作业' }}<Icon v-if="!submissionBusy" name="arrow" :size="17" /></button></div></form></section></template><template v-else><section class="panel saved-submission"><div class="section-heading"><div><span class="eyebrow">已保存的作业</span><h2>版本 {{ selectedSubmission.version }}<span class="saved-check"><Icon name="checkcircle" :size="17" />已提交</span></h2><small>{{ dateText(selectedSubmission.created_at) }}</small></div><button class="button secondary small-button" @click="reviseSubmission">修改并提交新版本</button></div><p v-if="selectedSubmission.material_pack_id" class="inline-note"><Icon name="folder" :size="16" />本版本已关联练习素材，AI 评审会将其作为背景参考。</p><details class="submission-details"><summary>查看本次提交内容<Icon name="down" :size="16" /></summary><pre class="submitted-text">{{ selectedSubmission.content || '本次主要通过附件提交。' }}</pre><template v-if="selectedSubmission.evidence_notes"><h4>补充证据</h4><pre class="submitted-text">{{ selectedSubmission.evidence_notes }}</pre></template></details><ul v-if="selectedSubmission.files.length" class="file-list saved-files"><li v-for="file in selectedSubmission.files" :key="file.id"><Icon name="file" :size="18" /><span><a :href="safeDownload(file.download_url)" download>{{ file.filename }}</a><small>{{ fileSize(file.size) }} · 提取 {{ file.extracted_chars.toLocaleString() }} 字符<span v-if="file.truncated" class="warning-text"> · 内容已截断</span></small><small v-if="file.extraction_note">{{ file.extraction_note }}</small></span><a :href="safeDownload(file.download_url)" class="icon-button" :aria-label="`下载 ${file.filename}`" download><Icon name="download" :size="17" /></a></li></ul><div v-if="selectedSubmission.static_checks.length" class="static-checks"><h4>系统静态检查</h4><p class="field-help">格式与可读取性检查，不代表代码已经执行。</p><div v-for="(check,i) in selectedSubmission.static_checks" :key="i" class="static-check" :class="check.status"><Icon :name="check.status === 'passed' ? 'checkcircle' : 'alert'" :size="17" /><div><strong>{{ check.name }}</strong><span>{{ check.message }}</span></div></div></div></section><section class="panel review-request"><div class="section-heading"><div><h2><Icon name="sparkles" :size="20" />AI 作业评审</h2><p>对照本课评分标准，分析你的材料与证据。</p></div></div><div v-if="!aiSettings?.api_key_set || !aiSettings?.model" class="inline-note"><Icon name="info" :size="18" /><span>{{ isAdmin ? '先配置模型服务，即可评审这份已保存的作业。' : '请联系管理员配置模型服务后进行评审。' }}</span><a href="#/settings" class="text-link">前往设置<Icon name="arrow" :size="15" /></a></div><template v-else><label class="checkbox-label"><input v-model="aiConsent" type="checkbox" /><span>将本次作业文本、附件提取内容和关联素材背景发送到 {{ aiSettings.provider_label || '已配置的 AI 服务' }} 进行评审。</span></label><div class="review-request-actions"><small>会使用服务商的调用额度。评审不会自动完成课时。</small><button class="button primary" :disabled="!aiConsent || reviewBusy || ['queued','running'].includes(selectedSubmission.latest_review?.status || '')" @click="requestReview"><span v-if="reviewBusy" class="spinner small"></span><Icon v-else name="sparkles" :size="17" />{{ ['queued','running'].includes(selectedSubmission.latest_review?.status || '') ? '评审进行中' : selectedSubmission.latest_review ? '重新评审' : '开始 AI 评审' }}</button></div></template></section><section v-if="selectedSubmission.reviews && selectedSubmission.reviews.length > 1" class="review-version-picker"><label for="review-version">评审记录</label><select id="review-version" v-model="activeReviewId"><option v-for="review in selectedSubmission.reviews" :key="review.id" :value="review.id">{{ dateText(review.created_at) }} · {{ reviewLabels[review.status] }}</option></select></section><ReviewCard v-if="activeReview" :review="activeReview" /></template></div>
          <section v-else class="panel" role="tabpanel"><div class="section-heading"><h2>本课提交历史</h2><span class="subtle-tag">{{ taskSubmissions.length }} 个版本</span></div><div v-if="!taskSubmissions.length" class="empty-state"><Icon name="clipboard" :size="35" /><h3>还没有提交记录</h3><p>每次提交会保留独立版本，方便比较改进前后的结果。</p><button class="button primary" @click="lessonTab = 'submission'">提交第一版</button></div><div v-else class="history-cards"><button v-for="s in taskSubmissions" :key="s.id" class="history-card" @click="openSubmission(s.id)"><div><span class="version-tag">V{{ s.version }}</span><strong>{{ dateText(s.created_at) }}</strong><span class="muted">{{ s.files.length }} 个附件</span></div><div><span v-if="s.latest_review?.report" class="score-inline">{{ s.latest_review.report.total_score }}<small>建议分</small></span><span v-else class="status-pill" :class="s.latest_review?.status || 'not_started'">{{ s.latest_review ? reviewLabels[s.latest_review.status] : '待评审' }}</span><Icon name="arrow" :size="17" /></div></button></div></section>
        </div><aside class="lesson-aside"><section class="panel progress-editor"><div class="section-heading"><h3>学习记录</h3><span class="status-pill" :class="progressOf(currentTask.id).status">{{ statusLabels[progressOf(currentTask.id).status] }}</span></div><form @submit.prevent="saveProgress()"><label for="learning-status">当前状态</label><select id="learning-status" v-model="progressDraft.status"><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="completed">已完成</option></select><label for="actual-hours">实际投入 <span class="optional">小时</span></label><input id="actual-hours" v-model="progressDraft.actual_hours" type="number" min="0" max="10000" step="0.5" placeholder="例如 4" /><label for="learning-notes">验收记录与复盘</label><textarea id="learning-notes" v-model="progressDraft.notes" rows="4" maxlength="5000" placeholder="记录完成情况、验证证据与下一步。"></textarea><p class="field-help">请对照验收标准确认完成。AI 建议分与学习状态分别记录。</p><button class="button secondary full" :disabled="progressBusy"><span v-if="progressBusy" class="spinner small"></span>{{ progressBusy ? '保存中…' : '保存学习记录' }}</button></form></section><section v-if="currentTask.prerequisites.length" class="panel prerequisites"><h3>建议先完成</h3><a v-for="id in currentTask.prerequisites" :key="id" :href="`#/learn/${id}`"><Icon :name="progressOf(id).status === 'completed' ? 'checkcircle' : 'circle'" :size="17" /><span>{{ taskTitle(id) }}</span><Icon name="chevron" :size="14" /></a></section><section class="panel acceptance-panel"><h3>本课验收标准</h3><ol><li v-for="(criterion,i) in currentTask.acceptanceCriteria" :key="i">{{ criterion }}</li></ol></section><section class="panel rubric-panel"><h3>评分维度</h3><div v-for="rubric in currentTask.rubric" :key="rubric.id"><div><strong>{{ rubric.title }}</strong><span>{{ rubric.weight }} 分</span></div><p>{{ rubric.description }}</p></div></section><section v-if="currentTask.resources.length" class="panel resources-panel"><h3>参考资料</h3><a v-for="resource in currentTask.resources" :key="resource.url" :href="safeLink(resource.url)" target="_blank" rel="noopener noreferrer"><span>{{ resource.title }}</span><Icon name="external" :size="15" /></a></section></aside></div></template>

        <template v-else-if="view === 'submissions'"><header class="page-heading"><div><span class="eyebrow">每个版本，都是一次积累</span><h1>作业记录</h1><p>查看提交版本、评审反馈与证据，继续完善你的作品。</p></div><button class="button secondary" @click="loadSubmissions().catch(e => notify(errorMessage(e),true))"><Icon name="refresh" :size="16" />刷新记录</button></header><section class="panel submissions-panel"><div class="section-heading"><h2>{{ submissions.length }} 个提交版本</h2><label class="filter-select"><span class="visually-hidden">按课时筛选</span><select v-model="historyFilter"><option value="all">全部课时</option><option v-for="item in allTasks" :key="item.task.id" :value="item.task.id">{{ item.task.title }}</option></select></label></div><div v-if="!filteredSubmissions.length" class="empty-state large"><span class="empty-icon"><Icon name="folder" :size="33" /></span><h3>{{ submissions.length ? '这项实践还没有提交记录' : '你的作品集，即将从这里开始' }}</h3><p>进入课时完成实践后，提交说明、代码或文档。每一版作业都会保存。</p><a :href="nextItem ? `#/learn/${nextItem.task.id}` : '#/course'" class="button primary">进入课程<Icon name="arrow" :size="17" /></a></div><div v-else class="submission-table-wrap"><table class="submission-table"><thead><tr><th>课时与作业</th><th>提交时间</th><th>评审状态</th><th>AI 建议分</th><th><span class="visually-hidden">操作</span></th></tr></thead><tbody><tr v-for="s in filteredSubmissions" :key="s.id"><td><button class="submission-title" @click="openSubmission(s.id,true)">{{ taskTitle(s.task_id) }}</button><small>版本 {{ s.version }} · {{ s.files.length }} 个附件</small></td><td>{{ dateText(s.created_at) }}</td><td><span class="status-pill" :class="s.latest_review?.status || 'not_started'">{{ s.latest_review ? reviewLabels[s.latest_review.status] : '待评审' }}</span></td><td><strong class="table-score">{{ s.latest_review?.report?.total_score ?? '—' }}</strong></td><td><button class="icon-button" aria-label="查看提交与评审" @click="openSubmission(s.id,true)"><Icon name="arrow" :size="18" /></button></td></tr></tbody></table></div></section></template>

        <MaterialsWorkspace v-else-if="view === 'materials'" :key="sessionKey" :tasks="allTasks.map(item => item.task)" :model-ready="Boolean(aiSettings?.api_key_set && aiSettings?.model)" :provider-label="aiSettings?.provider_label || ''" :usage="usage" @changed="materialsChanged" @select="useMaterial" />
        <UserManagement v-else-if="view === 'users' && isAdmin && auth.user" :key="sessionKey" :current-user-id="auth.user.id" />
        <section v-else-if="view === 'users'" class="panel empty-state"><Icon name="lock" :size="32" /><h2>此页面仅限管理员</h2><p>如需开通账号或调整额度，请联系管理员。</p><a href="#/dashboard" class="button secondary">返回学习概览</a></section>
        <template v-else-if="view === 'account'"><header class="page-heading"><div><span class="eyebrow">{{ isAdmin ? '管理员' : '学习者' }}</span><h1>我的账号</h1><p>{{ auth.user?.display_name || auth.user?.username }} · @{{ auth.user?.username }}</p></div></header><section v-if="usage" class="panel usage-panel"><div class="section-heading"><h2>今日 AI 用量</h2><button class="text-link" @click="loadUsage">刷新</button></div><div class="form-row"><div><strong>作业评审</strong><p>{{ usage.reviews.used }} / {{ usage.reviews.limit }} 次</p><small>全站剩余 {{ usage.reviews.global_remaining }} 次</small></div><div><strong>素材生成</strong><p>{{ usage.materials.used }} / {{ usage.materials.limit }} 次</p><small>全站剩余 {{ usage.materials.global_remaining }} 次</small></div></div><p class="field-help">按 UTC 日统计，北京时间每日 08:00 重置。申请失败也计入当日额度。</p></section><PasswordForm :key="sessionKey" @changed="passwordChanged" /></template>
        <template v-else-if="view === 'settings'"><header class="page-heading"><div><span class="eyebrow">共用模型服务，独立学习记录</span><h1>{{ isAdmin ? '模型设置' : '模型服务' }}</h1><p>模型服务用于作业评审与素材生成，由管理员统一配置。</p></div><span class="pill outline"><Icon name="lock" :size="14" />API Key 由服务器保存</span></header><div class="settings-layout"><section v-if="!isAdmin" class="panel shared-model-panel"><div class="section-heading"><h2>当前模型服务</h2><span class="status-pill" :class="aiSettings?.api_key_set ? 'completed' : 'not_started'">{{ aiSettings?.api_key_set ? '已配置' : '待配置' }}</span></div><dl><dt>服务名称</dt><dd>{{ aiSettings?.provider_label || '尚未配置' }}</dd><dt>模型</dt><dd>{{ aiSettings?.model || '尚未配置' }}</dd></dl><p class="field-help">服务地址与密钥由管理员管理。需要更换模型或调整额度时，请联系管理员。</p><div v-if="usage" class="usage-summary"><p>今日评审 {{ usage.reviews.used }} / {{ usage.reviews.limit }} 次</p><p>今日素材 {{ usage.materials.used }} / {{ usage.materials.limit }} 次</p></div><a href="#/account" class="text-link">查看用量与账号信息<Icon name="arrow" :size="16" /></a></section><section v-else class="panel settings-form"><div class="section-heading"><h2>服务连接</h2><span v-if="aiSettings?.api_key_set" class="status-pill completed">已保存密钥</span></div><form @submit.prevent="persistSettings()"><label for="provider-name">服务名称 <span class="optional">便于识别</span></label><input id="provider-name" v-model.trim="settingsForm.provider_label" maxlength="80" required placeholder="例如 我的模型服务" /><label for="base-url">API Base URL</label><input id="base-url" v-model.trim="settingsForm.base_url" type="url" required maxlength="500" placeholder="https://api.example.com/v1" autocomplete="off" /><small class="field-help">填写服务商提供的接口基地址，通常以 /v1 结尾；也支持完整的 /chat/completions 地址。</small><label for="model-name">模型名称</label><input id="model-name" v-model.trim="settingsForm.model" required maxlength="120" placeholder="填写服务商提供的模型 ID" autocomplete="off" /><label for="api-key">API Key <span v-if="aiSettings?.api_key_set" class="optional">已保存，留空保持原值</span></label><input id="api-key" v-model="settingsForm.api_key" type="password" maxlength="4096" autocomplete="new-password" :placeholder="aiSettings?.api_key_set ? '•••••••• 已安全保存' : '输入你的 API Key'" :disabled="settingsForm.clear_api_key" /><label v-if="aiSettings?.api_key_set" class="checkbox-label compact"><input v-model="settingsForm.clear_api_key" type="checkbox" /><span>保存时清除当前密钥</span></label><details class="advanced-settings"><summary>调用参数<Icon name="down" :size="16" /></summary><div class="form-row"><div><label for="max-tokens">评审最大输出 Token</label><input id="max-tokens" v-model.number="settingsForm.max_tokens" type="number" min="256" max="8192" step="1" required /></div><div><label for="timeout">超时 <span class="optional">秒</span></label><input id="timeout" v-model.number="settingsForm.timeout_seconds" type="number" min="10" max="180" step="1" required /></div></div><label for="material-max-tokens">素材最大输出 Token</label><input id="material-max-tokens" v-model.number="settingsForm.material_max_tokens" type="number" min="256" max="8192" step="1" required /><small class="field-help">素材包通常包含多个文件，可单独设置较大的输出预算。</small><label for="temperature">Temperature</label><input id="temperature" v-model.number="settingsForm.temperature" type="number" min="0" max="1" step="0.1" required /><small class="field-help">参数是否支持以服务商说明为准，评审结果也会受模型能力影响。</small></details><p v-if="settingsError" class="form-error" role="alert">{{ settingsError }}</p><div v-if="testResult" class="success-box" role="status"><Icon name="checkcircle" :size="20" /><div><strong>连接测试成功</strong><p>{{ testResult.message }}</p><small>{{ testResult.model }} · {{ (testResult.latency_ms / 1000).toFixed(2) }} 秒</small></div></div><div class="form-actions"><button type="button" class="button secondary" :disabled="settingsBusy || testing || !settingsForm.base_url || !settingsForm.model || settingsForm.clear_api_key" @click="testConnection"><span v-if="testing" class="spinner small"></span><Icon v-else name="refresh" :size="17" />{{ testing ? '正在测试…' : '保存并测试连接' }}</button><button class="button primary" :disabled="settingsBusy || testing"><span v-if="settingsBusy && !testing" class="spinner small"></span>{{ settingsBusy && !testing ? '正在保存…' : '保存配置' }}</button></div></form></section><aside class="settings-aside"><section class="panel"><span class="settings-illustration"><Icon name="sparkles" :size="29" /></span><h3>评审如何工作</h3><ol class="numbered-note"><li>你提交作业文本、代码或文档。</li><li>服务器读取材料，执行适用的静态检查。</li><li>你确认后，将材料与课时标准发送给模型。</li><li>保留建议分、证据、修改建议和评审版本。</li></ol></section><section class="panel quiet-panel"><h3><Icon name="shield" :size="18" />读懂验证边界</h3><p>AI 评审基于提交材料，不会运行你上传的代码，也不会验证生产环境中的实际效果。</p><p>运行日志、测试结果与部署记录有助于评审；课时是否完成由你对照验收标准确认。</p></section><section class="settings-small-note"><Icon name="info" :size="17" /><p>课程阅读与作业保存可以独立使用。测试连接和评审会产生服务商的调用用量。</p></section></aside></div></template>
        <div v-else-if="view === 'learn'" class="empty-state panel"><Icon name="book" :size="32" /><h2>没有找到这项实践</h2><p>请从课程路线选择一个课时。</p><a href="#/course" class="button primary">返回课程</a></div>
      </main><footer class="workspace-footer"><span>FIELDWORK · 学习有路径，交付有记录</span><span>v1.1.0 · 独立学习空间</span></footer>
    </div>
  </div>
  <Transition name="toast"><div v-if="toast" class="toast-message" :class="{ error: toast.error }" role="status"><Icon :name="toast.error ? 'alert' : 'checkcircle'" :size="19" /><span>{{ toast.text }}</span><button class="icon-button" aria-label="关闭提示" @click="toast = null"><Icon name="close" :size="16" /></button></div></Transition>
</template>
