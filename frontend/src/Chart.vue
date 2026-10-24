<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use, type EChartsType } from 'echarts/core'
import { HeatmapChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

use([
  HeatmapChart,
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
])
const props = defineProps<{ option: EChartsOption; label: string }>()
const element = ref<HTMLDivElement>()
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
onMounted(() => {
  if (!element.value) return
  chart = init(element.value)
  chart.setOption(props.option)
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(element.value)
})
watch(
  () => props.option,
  (option) => chart?.setOption(option, { notMerge: true }),
)
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>
<template>
  <div ref="element" class="chart" role="img" :aria-label="label"></div>
</template>
