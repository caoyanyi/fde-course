<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
const props = defineProps<{ content: string }>()
const safeHtml = computed(() => {
  const parsed = marked.parse(props.content || '', { async: false, gfm: true })
  const clean = DOMPurify.sanitize(parsed, { USE_PROFILES: { html: true }, FORBID_TAGS: ['style','iframe','object','embed','form','input','button','img','video','audio','link','meta'], FORBID_ATTR: ['style'] })
  const dom = new DOMParser().parseFromString(clean, 'text/html')
  dom.querySelectorAll('a').forEach(a => { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer') })
  return dom.body.innerHTML
})
</script>
<template><div class="markdown" v-html="safeHtml"></div></template>
