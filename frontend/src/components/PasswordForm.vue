<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, json, errorMessage, currentSessionEpoch } from '../api'
import type { AuthState } from '../types'
import Icon from './Icon.vue'
defineProps<{ requiredChange?: boolean }>()
const emit = defineEmits<{ changed: [AuthState] }>()
const form = reactive({ current_password: '', new_password: '', confirmation: '' })
const busy = ref(false)
const error = ref('')
async function save() {
  const epoch = currentSessionEpoch()
  error.value = ''
  if (form.new_password !== form.confirmation) { error.value = '两次输入的新密码不一致。'; return }
  if (form.current_password === form.new_password) { error.value = '新密码需要与当前密码不同。'; return }
  busy.value = true
  try {
    const result = await api<AuthState>('/auth/change-password', { method: 'POST', body: json({ current_password: form.current_password, new_password: form.new_password }) })
    if (epoch !== currentSessionEpoch()) return
    form.current_password = ''; form.new_password = ''; form.confirmation = ''
    emit('changed', result)
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>
<template>
  <section class="panel password-panel">
    <div class="section-heading"><div><span class="eyebrow">账号安全</span><h2>{{ requiredChange ? '设置你的专属密码' : '修改登录密码' }}</h2></div><Icon name="lock" /></div>
    <p class="muted">{{ requiredChange ? '当前使用的是初始或重置密码。修改后即可进入学习空间。' : '修改成功后，其他设备的登录会话会失效。当前设备将保持登录。' }}</p>
    <form @submit.prevent="save">
      <label for="current-password">{{ requiredChange ? '初始 / 重置密码' : '当前密码' }}</label><input id="current-password" v-model="form.current_password" type="password" autocomplete="current-password" required minlength="12" maxlength="128" />
      <label for="new-password">新密码</label><input id="new-password" v-model="form.new_password" type="password" autocomplete="new-password" required minlength="12" maxlength="128" />
      <small class="field-help">12–128 个字符，建议使用较长且不重复的密码。</small>
      <label for="confirm-password">再次输入新密码</label><input id="confirm-password" v-model="form.confirmation" type="password" autocomplete="new-password" required minlength="12" maxlength="128" />
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="form-actions"><button class="button primary" :disabled="busy"><span v-if="busy" class="spinner small"></span>{{ busy ? '正在修改…' : '保存新密码' }}</button></div>
    </form>
  </section>
</template>
