<script setup lang="ts">
import Icon from './Icon.vue'
import type { Review } from '../types'
defineProps<{ review: Review }>()
const confidence = { low: '低', medium: '中', high: '高' }
const safePercent = (score: number, weight: number) => Math.max(0, Math.min(100, weight ? score / weight * 100 : 0))
</script>
<template>
  <section class="review-card" aria-label="AI 作业评审">
    <div v-if="review.status === 'queued' || review.status === 'running'" class="review-pending" role="status">
      <span class="spinner"></span><div><strong>{{ review.status === 'queued' ? '作业已进入评审队列' : 'AI 正在对照验收标准评审' }}</strong><p>页面会自动更新。提交内容已经保存，你可以继续阅读课程。</p></div>
    </div>
    <div v-else-if="review.status === 'failed'" class="error-box" role="alert"><Icon name="alert" /><div><strong>本次评审未完成</strong><p>{{ review.error || '模型服务未返回有效结果，请检查配置后重新评审。' }}</p><small>本次没有生成评分，已提交的作业仍然保留。</small></div></div>
    <template v-else-if="review.report">
      <header class="review-heading"><div class="review-score"><span>{{ review.report.total_score }}</span><small>/ {{ review.report.max_score || 100 }}</small></div><div><div class="eyebrow">本次 AI 建议分</div><h3>让改进有据可循</h3><p>{{ review.model }} <span class="dot">·</span> AI 自评把握：{{ confidence[review.report.confidence] || '未提供' }}</p></div></header>
      <div class="verification-label"><Icon name="shield" :size="17" /><span>文本与材料评审 · 未运行提交代码</span></div>
      <p class="review-summary">{{ review.report.summary }}</p>
      <div class="rubric-results"><article v-for="item in review.report.rubric" :key="item.id" class="rubric-result"><div class="rubric-line"><strong>{{ item.title }}</strong><span>{{ item.score }} <small>/ {{ item.weight }}</small></span></div><div class="progress-track mini"><i :style="{ width: `${safePercent(item.score, item.weight)}%` }"></i></div><p>{{ item.feedback }}</p><ul v-if="item.evidence?.length" class="evidence-list"><li v-for="(e,i) in item.evidence" :key="i">{{ e }}</li></ul></article></div>
      <div class="review-feedback-grid">
        <section v-if="review.report.strengths?.length"><h4><Icon name="checkcircle" :size="17" />已经做好的</h4><ul><li v-for="(s,i) in review.report.strengths" :key="i">{{ s }}</li></ul></section>
        <section v-if="review.report.improvements?.length"><h4><Icon name="target" :size="17" />优先改进</h4><ul><li v-for="(s,i) in review.report.improvements" :key="i">{{ s }}</li></ul></section>
        <section v-if="review.report.missing_evidence?.length"><h4><Icon name="file" :size="17" />需要补充的证据</h4><ul><li v-for="(s,i) in review.report.missing_evidence" :key="i">{{ s }}</li></ul></section>
        <section v-if="review.report.next_steps?.length"><h4><Icon name="arrow" :size="17" />下一步行动</h4><ol><li v-for="(s,i) in review.report.next_steps" :key="i">{{ s }}</li></ol></section>
      </div>
      <div class="review-footnote"><p v-if="review.report.evidence_truncated" class="warning-text">本次提交材料超出评审输入上限，模型只看到了截取的部分。请精简关键证据后再次提交。</p><p>{{ review.report.verification_note || '本次结果基于提交文本和附件提取内容。实际运行、生产部署与业务效果需要你提供记录并自行核验。' }}</p><span v-if="review.usage">输入 Token：{{ review.usage.input_tokens ?? '未提供' }} <span class="dot">·</span> 输出 Token：{{ review.usage.output_tokens ?? '未提供' }}</span></div>
    </template>
  </section>
</template>
