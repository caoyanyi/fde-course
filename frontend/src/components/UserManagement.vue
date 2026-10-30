<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, json, errorMessage } from '../api'
import type { User } from '../types'
import Icon from './Icon.vue'
const props = defineProps<{ currentUserId: number }>()
const users = ref<User[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const success = ref('')
const editingId = ref<number | null>(null)
const resetId = ref<number | null>(null)
const resetPassword = ref('')
const form = reactive({ username: '', password: '', display_name: '', role: 'learner' as User['role'], review_daily_limit: 100, material_daily_limit: 100 })
const edit = reactive({ display_name: '', role: 'learner' as User['role'], is_active: true, review_daily_limit: 100, material_daily_limit: 100 })
async function load() { loading.value = true; error.value = ''; try { users.value = (await api<{ items: User[] }>('/admin/users')).items } catch (e) { error.value = errorMessage(e) } finally { loading.value = false } }
async function create() {
  busy.value = true; error.value = ''; success.value = ''
  try {
    const user = await api<User>('/admin/users', { method: 'POST', body: json(form) })
    form.username = ''; form.password = ''; form.display_name = ''
    success.value = `账号 ${user.username} 已创建。请将初始密码单独交给使用者；首次登录必须修改。`
    await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
function beginEdit(user: User) { editingId.value = user.id; resetId.value = null; resetPassword.value = ''; Object.assign(edit, { display_name: user.display_name, role: user.role, is_active: user.is_active, review_daily_limit: user.review_daily_limit, material_daily_limit: user.material_daily_limit }); error.value = ''; success.value = '' }
async function saveEdit() {
  if (editingId.value === null) return
  busy.value = true; error.value = ''; success.value = ''
  try {
    await api(`/admin/users/${editingId.value}`, { method: 'PATCH', body: json(edit) })
    editingId.value = null; success.value = '账号资料与额度已保存。'; await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
function beginReset(user: User) { resetId.value = user.id; resetPassword.value = ''; editingId.value = null; error.value = ''; success.value = '' }
async function reset() {
  if (resetId.value === null) return
  busy.value = true; error.value = ''; success.value = ''
  try {
    await api(`/admin/users/${resetId.value}/password`, { method: 'POST', body: json({ new_password: resetPassword.value }) })
    resetPassword.value = ''; resetId.value = null; success.value = '密码已重置，旧会话已失效。使用者下次登录需要再次修改密码。'; await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <header class="page-heading"><div><span class="eyebrow">独立账号，共用学习平台</span><h1>用户管理</h1><p>账号由管理员创建，每位使用者拥有独立的进度、作业和素材空间。</p></div><button class="button secondary" :disabled="loading || busy" @click="load"><Icon name="refresh" :size="17" />刷新</button></header>
  <div v-if="error" class="error-box" role="alert">{{ error }}</div><div v-if="success" class="success-box" role="status">{{ success }}</div>
  <div class="management-layout">
    <section class="panel create-user-panel"><h2>新增账号</h2><form @submit.prevent="create">
      <label for="new-username">用户名</label><input id="new-username" v-model.trim="form.username" required minlength="3" maxlength="40" pattern="[A-Za-z0-9_-]+" autocomplete="off" placeholder="英文字母、数字、下划线或短横线" />
      <label for="new-display-name">显示名称</label><input id="new-display-name" v-model.trim="form.display_name" maxlength="80" placeholder="例如 Ethan" />
      <label for="initial-password">初始密码</label><input id="initial-password" v-model="form.password" type="password" required minlength="12" maxlength="128" autocomplete="new-password" /><small class="field-help">首次登录必须修改。系统不发送邮件或保存明文密码。</small>
      <label for="new-role">角色</label><select id="new-role" v-model="form.role"><option value="learner">学习者</option><option value="admin">管理员</option></select>
      <div class="form-row"><div><label for="new-review-quota">每日评审额度</label><input id="new-review-quota" v-model.number="form.review_daily_limit" type="number" min="0" max="1000" required /></div><div><label for="new-material-quota">每日素材额度</label><input id="new-material-quota" v-model.number="form.material_daily_limit" type="number" min="0" max="1000" required /></div></div>
      <small class="field-help">每日按 UTC 计数（北京时间 08:00 重置），同时受全站额度限制。0 表示禁止发起此类调用。</small>
      <div class="form-actions"><button class="button primary" :disabled="busy"><Icon name="user" :size="17" />创建账号</button></div>
    </form></section>
    <section class="panel users-panel"><div class="section-heading"><h2>账号列表</h2><span class="subtle-tag">{{ users.length }} 个账号</span></div><div v-if="loading && !users.length" class="content-loading"><span class="spinner"></span></div>
      <article v-for="user in users" :key="user.id" class="user-row">
        <div class="user-heading"><span class="avatar">{{ (user.display_name || user.username).slice(0,1).toUpperCase() }}</span><div><strong>{{ user.display_name || user.username }} <small v-if="user.id === props.currentUserId">（当前账号）</small></strong><small>@{{ user.username }}</small></div><span class="status-pill" :class="user.is_active ? 'completed' : 'failed'">{{ !user.is_active ? '已停用' : user.role === 'admin' ? '管理员' : '学习者' }}</span></div>
        <p class="user-limits">每日评审 {{ user.review_daily_limit }} 次 · 素材 {{ user.material_daily_limit }} 次<span v-if="user.must_change_password"> · 待修改初始密码</span></p>
        <div class="user-actions"><button class="button secondary small-button" :disabled="busy" @click="beginEdit(user)">编辑账号与额度</button><button v-if="user.id !== props.currentUserId" class="text-link" :disabled="busy" @click="beginReset(user)">重置密码</button></div>
        <form v-if="editingId === user.id" class="inline-editor" @submit.prevent="saveEdit"><label :for="`display-${user.id}`">显示名称</label><input :id="`display-${user.id}`" v-model.trim="edit.display_name" maxlength="80" /><div class="form-row"><div><label :for="`role-${user.id}`">角色</label><select :id="`role-${user.id}`" v-model="edit.role" :disabled="user.id === props.currentUserId"><option value="learner">学习者</option><option value="admin">管理员</option></select></div><div><label :for="`active-${user.id}`">账号状态</label><select :id="`active-${user.id}`" v-model="edit.is_active" :disabled="user.id === props.currentUserId"><option :value="true">启用</option><option :value="false">停用</option></select></div></div><div class="form-row"><div><label :for="`review-${user.id}`">每日评审额度</label><input :id="`review-${user.id}`" v-model.number="edit.review_daily_limit" type="number" min="0" max="1000" required /></div><div><label :for="`material-${user.id}`">每日素材额度</label><input :id="`material-${user.id}`" v-model.number="edit.material_daily_limit" type="number" min="0" max="1000" required /></div></div><p class="field-help">停用账号会立即撤销其登录会话。修改角色后，该使用者需要重新登录。</p><div class="user-actions"><button class="button primary small-button" :disabled="busy">保存修改</button><button type="button" class="button subtle small-button" :disabled="busy" @click="editingId = null">取消</button></div></form>
        <form v-if="resetId === user.id" class="inline-editor" @submit.prevent="reset"><label :for="`reset-${user.id}`">新的临时密码</label><input :id="`reset-${user.id}`" v-model="resetPassword" type="password" required minlength="12" maxlength="128" autocomplete="new-password" /><p class="field-help">提交后，该账号在所有设备的会话都会失效。</p><div class="user-actions"><button class="button primary small-button" :disabled="busy">确认重置</button><button type="button" class="button subtle small-button" :disabled="busy" @click="resetId = null; resetPassword = ''">取消</button></div></form>
      </article>
    </section>
  </div>
</template>
