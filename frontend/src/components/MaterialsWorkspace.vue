<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api, json, errorMessage, currentSessionEpoch } from '../api'
import type { MaterialKind, MaterialPack, MaterialPage, Task, Usage } from '../types'
import Icon from './Icon.vue'
import MarkdownBlock from './MarkdownBlock.vue'
const props = defineProps<{ tasks: Task[]; taskId?: string; modelReady: boolean; providerLabel: string; usage: Usage | null }>()
const emit = defineEmits<{ changed: []; select: [MaterialPack] }>()
const kinds: { value: MaterialKind; title: string; description: string }[] = [
  { value: 'scenario', title: '业务案例', description: '角色、需求与约束' },
  { value: 'sample_data', title: '样例数据', description: '练习用的模拟数据' },
  { value: 'knowledge_docs', title: '知识文档', description: '检索与问答语料' },
  { value: 'test_cases', title: '测试用例', description: '边界与预期结果' },
  { value: 'starter_template', title: '起步模板', description: '待你完善的骨架' },
]
const statusLabels = { queued: '排队中', running: '生成中', completed: '已生成', failed: '生成失败' }
const taskFilter = ref(props.taskId || '')
const selectedTaskId = ref(props.taskId || props.tasks[0]?.id || '')
const form = reactive({ scenario: '', difficulty: 'beginner', tech_stack: 'PHP / Vue / SQLite', material_types: ['scenario', 'sample_data'] as MaterialKind[], requirements: '' })
const consent = ref(false)
const busy = ref(false)
const loading = ref(false)
const loadingDetail = ref(false)
const error = ref('')
const notice = ref('')
const syncError = ref('')
const packs = ref<MaterialPack[]>([])
const total = ref(0)
const offset = ref(0)
const pageSize = 20
const detail = ref<MaterialPack | null>(null)
const activeFileId = ref('')
const activeFile = computed(() => detail.value?.files.find(f => f.id === activeFileId.value) || detail.value?.files[0])
const selectedTask = computed(() => props.tasks.find(t => t.id === selectedTaskId.value))
const remaining = computed(() => props.usage ? Math.max(0, Math.min(props.usage.materials.limit - props.usage.materials.used, props.usage.materials.global_remaining)) : null)
const canGenerate = computed(() => props.modelReady && selectedTaskId.value && form.material_types.length && consent.value && !busy.value && remaining.value !== 0)
let alive = true
let listRequest = 0
let detailRequest = 0
let polling = false
let timer: number | undefined
function taskTitle(id: string) { return props.tasks.find(t => t.id === id)?.title || id }
function dateText(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function fileSize(n: number) { return n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B` }
function packDownload(id: string) { return `/api/materials/${encodeURIComponent(id)}/download` }
function fileDownload(packId: string, fileId: string) { return `/api/materials/${encodeURIComponent(packId)}/files/${encodeURIComponent(fileId)}` }
async function loadList(nextOffset = offset.value, quiet = false) {
  const epoch = currentSessionEpoch()
  const request = ++listRequest
  const filter = taskFilter.value
  if (!quiet) { loading.value = true; error.value = '' }
  try {
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(nextOffset) })
    if (filter) query.set('task_id', filter)
    const result = await api<MaterialPage>(`/materials?${query}`)
    if (!alive || epoch !== currentSessionEpoch() || request !== listRequest) return
    packs.value = result.items; total.value = result.total; offset.value = result.offset
    syncError.value = ''
  } catch (e) { if (alive && request === listRequest) { if (quiet) syncError.value = errorMessage(e); else error.value = errorMessage(e) } }
  finally { if (alive && request === listRequest) loading.value = false }
}
async function openPack(id: string, quiet = false) {
  const epoch = currentSessionEpoch()
  const request = ++detailRequest
  if (!quiet) { loadingDetail.value = true; error.value = ''; detail.value = null; activeFileId.value = '' }
  try {
    const result = await api<MaterialPack>(`/materials/${encodeURIComponent(id)}`)
    if (!alive || epoch !== currentSessionEpoch() || request !== detailRequest) return
    const changedStatus = detail.value?.id === id && detail.value.status !== result.status
    detail.value = result
    if (!result.files.some(f => f.id === activeFileId.value)) activeFileId.value = result.files[0]?.id || ''
    syncError.value = ''
    if (changedStatus) emit('changed')
  } catch (e) { if (alive && request === detailRequest) { if (quiet) syncError.value = errorMessage(e); else error.value = errorMessage(e) } }
  finally { if (alive && request === detailRequest) loadingDetail.value = false }
}
async function generate() {
  const epoch = currentSessionEpoch()
  if (!canGenerate.value) return
  const taskId = selectedTaskId.value
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const result = await api<{ material_id: string; status: MaterialPack['status'] }>(`/tasks/${encodeURIComponent(taskId)}/materials`, { method: 'POST', body: json({ ...form, consent: true }) })
    if (!alive || epoch !== currentSessionEpoch()) return
    consent.value = false; notice.value = '素材生成任务已创建。生成过程在服务器继续，可以离开此页面后再查看。'
    emit('changed')
    if (taskFilter.value && taskFilter.value !== taskId) taskFilter.value = props.taskId || taskId
    await loadList(0)
    await openPack(result.material_id)
  } catch (e) { if (alive) error.value = errorMessage(e) } finally { if (alive) busy.value = false }
}
async function poll() {
  if (!alive || polling || document.hidden || loading.value || loadingDetail.value || busy.value) return
  const pending = packs.value.some(p => p.status === 'queued' || p.status === 'running') || ['queued', 'running'].includes(detail.value?.status || '')
  if (!pending && !syncError.value) return
  polling = true
  try {
    await loadList(offset.value, true)
    if (detail.value && ['queued', 'running'].includes(detail.value.status)) await openPack(detail.value.id, true)
  } finally { polling = false }
}
function selectPack() { if (detail.value?.status === 'completed') emit('select', detail.value) }
watch(taskFilter, value => { if (value) selectedTaskId.value = value; void loadList(0) })
watch(() => props.taskId, value => { taskFilter.value = value || ''; if (value) selectedTaskId.value = value; detail.value = null; detailRequest++ })
watch(() => props.tasks, tasks => { if (!selectedTaskId.value && tasks[0]) selectedTaskId.value = tasks[0].id })
onMounted(() => { void loadList(0); timer = window.setInterval(poll, 3000) })
onUnmounted(() => { alive = false; listRequest++; detailRequest++; window.clearInterval(timer) })
</script>
<template>
  <div class="materials-workspace">
    <header v-if="!taskId" class="page-heading"><div><span class="eyebrow">围绕任务组织练习输入</span><h1>我的素材库</h1><p>生成模拟案例与数据，按课时保留独立版本，避免散落在不同文档中。</p></div><span class="pill outline"><Icon name="lock" :size="14" />仅当前账号可见</span></header>
    <div class="material-intro"><Icon name="sparkles" :size="20" /><p>素材用来开始练习。完成分析、编码与验证后，再提交你自己的作业和运行证据。生成内容未经过实际运行验证。</p></div>
    <section class="panel material-generator"><div class="section-heading"><div><span class="eyebrow">定制本次练习</span><h2>生成练习素材</h2></div><span v-if="remaining !== null" class="subtle-tag">今日可用 {{ remaining }} 次</span></div>
      <div v-if="!modelReady" class="inline-note"><Icon name="info" :size="18" /><span>请联系管理员配置模型服务。已有素材仍可查看和下载。</span><a href="#/settings" class="text-link">服务状态</a></div>
      <form @submit.prevent="generate">
        <label for="material-task">关联课时</label><select id="material-task" v-model="selectedTaskId" :disabled="Boolean(taskId) || busy" required><option value="" disabled>选择一个课时</option><option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.title }}</option></select><small v-if="selectedTask" class="field-help">{{ selectedTask.summary }}</small>
        <label for="material-scenario">业务场景</label><textarea id="material-scenario" v-model.trim="form.scenario" rows="3" maxlength="2000" required placeholder="例如：为一家小型电商设计客服知识库，覆盖退换货、物流查询和会员权益。"></textarea>
        <div class="form-row"><div><label for="material-stack">使用的技术栈</label><input id="material-stack" v-model.trim="form.tech_stack" maxlength="500" placeholder="例如 PHP / Vue / MySQL" /></div><div><label for="material-difficulty">练习难度</label><select id="material-difficulty" v-model="form.difficulty"><option value="beginner">入门：最小可完成范围</option><option value="intermediate">进阶：增加边界与约束</option><option value="advanced">挑战：接近真实交付</option></select></div></div>
        <fieldset class="material-kind-fieldset"><legend>需要哪些素材</legend><div class="material-kind-options"><label v-for="kind in kinds" :key="kind.value" class="material-kind" :class="{ selected: form.material_types.includes(kind.value) }"><input v-model="form.material_types" type="checkbox" :value="kind.value" /><span><strong>{{ kind.title }}</strong><small>{{ kind.description }}</small></span></label></div></fieldset>
        <label for="material-requirements">补充要求 <span class="optional">选填</span></label><textarea id="material-requirements" v-model.trim="form.requirements" maxlength="3000" rows="3" placeholder="例如：模拟 20 条订单；包含缺失字段和异常状态；给出 CSV 与 JSON 文件。"></textarea>
        <label class="checkbox-label"><input v-model="consent" type="checkbox" /><span>将本课要求和以上参数发送至 {{ providerLabel || '已配置的模型服务' }} 生成素材，并使用服务商调用额度。请使用模拟场景，避免填入真实客户隐私。</span></label>
        <small class="field-help">每次最多 8 个文本文件。生成失败也计入当日申请额度；系统不自动重试。额度按 UTC 日统计（北京时间 08:00 重置）。</small>
        <div class="form-actions"><p>每次重新生成会保留为新版本。</p><button class="button primary" :disabled="!canGenerate"><span v-if="busy" class="spinner small"></span><Icon v-else name="sparkles" :size="17" />{{ busy ? '正在提交…' : '生成素材包' }}</button></div>
      </form>
    </section>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><div v-if="notice" class="success-box" role="status">{{ notice }}</div><div v-if="syncError" class="inline-note" role="status">状态同步暂时失败：{{ syncError }} 系统会继续重试。<button class="text-link" @click="poll">立即重试</button></div>
    <div class="material-library-grid">
      <section class="panel material-list-panel"><div class="section-heading"><h2>素材版本 <span class="subtle-tag">{{ total }}</span></h2><button class="icon-button" :disabled="loading" aria-label="刷新素材列表" @click="loadList(); emit('changed')"><Icon name="refresh" :size="17" /></button></div>
        <label v-if="!taskId" class="filter-select"><span class="visually-hidden">按课时筛选素材</span><select v-model="taskFilter"><option value="">全部课时</option><option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.title }}</option></select></label>
        <div v-if="loading && !packs.length" class="content-loading"><span class="spinner"></span></div><div v-else-if="!packs.length" class="small-empty"><Icon name="folder" :size="28" /><h3>还没有素材包</h3><p>填写场景后生成，所有版本会保存在这里。</p></div>
        <button v-for="pack in packs" :key="pack.id" class="material-item" :class="{ active: detail?.id === pack.id }" @click="openPack(pack.id)"><div><span class="version-tag">V{{ pack.version }}</span><span class="status-pill" :class="pack.status">{{ statusLabels[pack.status] }}</span></div><strong>{{ pack.title || pack.params.scenario || taskTitle(pack.task_id) }}</strong><small>{{ taskTitle(pack.task_id) }}</small><small>{{ dateText(pack.created_at) }} · {{ pack.files.length }} 个文件</small></button>
        <div v-if="total > pageSize" class="material-pagination"><button class="button secondary small-button" :disabled="loading || offset === 0" @click="loadList(Math.max(0,offset-pageSize))">上一页</button><small>{{ Math.floor(offset/pageSize)+1 }} / {{ Math.ceil(total/pageSize) }}</small><button class="button secondary small-button" :disabled="loading || offset+pageSize >= total" @click="loadList(offset+pageSize)">下一页</button></div>
      </section>
      <section class="panel material-detail-panel"><div v-if="loadingDetail" class="content-loading"><span class="spinner"></span><p>正在读取素材…</p></div><template v-else-if="detail"><div class="section-heading"><div><span class="eyebrow">{{ taskTitle(detail.task_id) }} · V{{ detail.version }}</span><h2>{{ detail.title || '练习素材包' }}</h2></div><span class="status-pill" :class="detail.status">{{ statusLabels[detail.status] }}</span></div>
        <div v-if="detail.status === 'queued' || detail.status === 'running'" class="review-pending"><span class="spinner"></span><div><strong>{{ detail.status === 'queued' ? '已加入生成队列' : '模型正在生成素材' }}</strong><p>完成后会自动更新。重复提交相同的进行中任务不会另建版本。</p></div></div>
        <div v-else-if="detail.status === 'failed'" class="error-box"><Icon name="alert" :size="20" /><div><strong>本次生成未完成</strong><p>{{ detail.error || '请检查模型服务后重新生成。' }}</p><small>失败记录会保留。确认原因后，可在上方手动提交新的生成任务。</small></div></div>
        <template v-else><p class="material-summary">{{ detail.summary }}</p><div class="material-provenance"><span>AI 生成的模拟素材</span><span>{{ detail.provider_label }} · {{ detail.model }}</span><span>课程 {{ detail.course_version }}</span></div><p class="field-help">{{ detail.verification_note }}</p><div class="material-actions"><a :href="packDownload(detail.id)" class="button secondary small-button" download><Icon name="download" :size="16" />下载全部 ZIP</a><button class="button primary small-button" @click="selectPack"><Icon name="clipboard" :size="16" />用于本课作业</button></div><div v-if="detail.how_to_use.length" class="material-usage"><h3>如何使用这些素材</h3><ol><li v-for="(step,i) in detail.how_to_use" :key="i">{{ step }}</li></ol></div>
          <div class="material-files"><label for="material-file-preview">预览文件</label><select id="material-file-preview" v-model="activeFileId"><option v-for="file in detail.files" :key="file.id" :value="file.id">{{ file.filename }}</option></select><template v-if="activeFile"><div class="material-file-meta"><div><strong>{{ activeFile.filename }}</strong><small>{{ activeFile.description }} · {{ fileSize(activeFile.size) }}</small></div><a :href="fileDownload(detail.id,activeFile.id)" class="icon-button" :aria-label="`下载 ${activeFile.filename}`" download><Icon name="download" :size="17" /></a></div><div class="material-preview"><MarkdownBlock v-if="activeFile.filename.toLowerCase().endsWith('.md')" :content="activeFile.content || ''" /><pre v-else>{{ activeFile.content }}</pre></div><details class="material-digest"><summary>文件校验值 SHA-256</summary><code>{{ activeFile.sha256 }}</code></details></template></div>
        </template><details class="material-params"><summary>查看本次生成参数</summary><dl><dt>场景</dt><dd>{{ detail.params.scenario }}</dd><dt>技术栈</dt><dd>{{ detail.params.tech_stack || '未指定' }}</dd><dt>补充要求</dt><dd>{{ detail.params.requirements || '无' }}</dd></dl></details>
      </template><div v-else class="small-empty material-detail-empty"><Icon name="file" :size="32" /><h3>选择一个素材版本</h3><p>查看内容、生成参数与文件，或打包下载后开始实践。</p></div></section>
    </div>
  </div>
</template>
