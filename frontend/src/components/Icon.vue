<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string[]> = {
  dashboard: ['M3 3h7v7H3z','M14 3h7v7h-7z','M3 14h7v7H3z','M14 14h7v7h-7z'],
  book: ['M12 5v16','M12 5C8 2 4 3 2 4v15c3-1 7-1 10 2','M12 5c4-3 8-2 10-1v15c-3-1-7-1-10 2'],
  clipboard: ['M9 5H5v16h14V5h-4','M9 3h6v4H9z','M8 12h8','M8 16h5'],
  settings: ['M9 4l1-2h4l1 2 3 2 2 1v4l-2 1-1 3v2l-3 2-2-1-3 1-2-1-1-3-2-2v-4l2-1 1-3z','M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0'],
  arrow: ['M4 12h16','M14 6l6 6-6 6'],
  arrowleft: ['M20 12H4','M10 6l-6 6 6 6'],
  chevron: ['M9 5l7 7-7 7'],
  down: ['M6 9l6 6 6-6'],
  check: ['M5 12l4 4L19 6'],
  checkcircle: ['M22 11v1a10 10 0 1 1-6-9','M22 4l-10 10-3-3'],
  upload: ['M12 16V3','M7 8l5-5 5 5','M4 16v5h16v-5'],
  code: ['M8 6l-6 6 6 6','M16 6l6 6-6 6','M14 3l-4 18'],
  logout: ['M9 5H4v14h5','M9 12h12','M17 8l4 4-4 4'],
  clock: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0','M12 6v6l4 2'],
  close: ['M6 6l12 12','M6 18L18 6'],
  file: ['M14 2H4v20h16V8z','M14 2v6h6','M8 13h8','M8 17h5'],
  external: ['M14 3h7v7','M10 14L21 3','M10 3H3v18h18v-7'],
  sparkles: ['M12 3l2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6z','M20 2v4','M18 4h4'],
  alert: ['M12 3L2 21h20z','M12 9v5','M12 17h.01'],
  info: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0','M12 11v6','M12 7h.01'],
  user: ['M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0','M4 21v-2a8 8 0 0 1 16 0v2'],
  lock: ['M5 10h14v12H5z','M8 10V6a4 4 0 0 1 8 0v4','M12 15v3'],
  refresh: ['M20 7v5h-5','M4 17v-5h5','M6 7a7 7 0 0 1 12-2l2 3','M18 17a7 7 0 0 1-12 2l-2-3'],
  download: ['M12 3v13','M7 11l5 5 5-5','M4 17v4h16v-4'],
  menu: ['M3 6h18','M3 12h18','M3 18h18'],
  target: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0','M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0','M12 12h.01'],
  folder: ['M3 5h7l2 3h9v13H3z'],
  trash: ['M3 6h18','M9 6V3h6v3','M5 6l1 15h12l1-15','M10 10v7','M14 10v7'],
  shield: ['M12 2L3 6v6c0 5 9 10 9 10s9-5 9-10V6z','M8 12l3 3 5-6'],
  play: ['M7 3l14 9-14 9z'],
  circle: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'],
}
</script>
<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path v-for="(d,i) in paths[name] || paths.circle" :key="i" :d="d" /></svg>
</template>
