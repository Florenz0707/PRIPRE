<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import type { ReplayPage, ReplayDetail } from './api'
import { useRemoteJSON } from './useRemoteJSON'
import Chart from './Chart.vue'
import {
  heatmapTooltip,
  labelVisualMap,
  probabilityHeatmapData,
  probabilityVisualMap,
} from './heatmap'
import ProbabilityLegend from './ProbabilityLegend.vue'

const props = defineProps<{
  start: string
  end: string
  model: string
  runId: string
}>()
const offset = shallowRef(0)
watch(
  () => [props.start, props.end, props.runId],
  () => {
    offset.value = 0
  },
)
const pageURL = computed(() => {
  const params = new URLSearchParams({
    offset: String(offset.value),
    limit: '100',
  })
  if (props.start) params.set('start', props.start)
  if (props.end) params.set('end', props.end)
  return `/api/replay?${params}`
})
const page = useRemoteJSON<ReplayPage>(pageURL)
const timestamp = shallowRef('')
watch(page.data, (value) => {
  timestamp.value = String(value?.origins[0]?.timestamp_us ?? '')
})
const detailURL = computed(() =>
  timestamp.value
    ? `/api/replay/${timestamp.value}?model=${encodeURIComponent(props.model)}`
    : null,
)
const detail = useRemoteJSON<ReplayDetail>(detailURL)
const frame = computed(() =>
  detail.data.value?.run_id === props.runId ? detail.data.value : null,
)
function heatmap(labels: boolean): EChartsOption {
  const current = frame.value
  if (!current) return {}
  const matrix = labels ? current.labels : current.probabilities
  return {
    animation: false,
    tooltip: heatmapTooltip(current.grid, labels),
    grid: { left: 135, right: 20, top: 20, bottom: 45 },
    xAxis: {
      type: 'category',
      data: current.grid.windows.map(
        (w) => `+${(w.start_us - current.grid.timestamp_us) / 1e6}s`,
      ),
    },
    yAxis: {
      type: 'category',
      data: current.grid.prices.map((p) => `[${p.lower}, ${p.upper})`),
    },
    visualMap: labels ? labelVisualMap() : probabilityVisualMap(),
    series: [
      {
        type: 'heatmap',
        data: labels
          ? matrix.flatMap((row, y) =>
              row.map((v, x) => [x, y, v]).filter((v) => v[2] !== null),
            )
          : probabilityHeatmapData(current.probabilities),
        emphasis: { itemStyle: { borderColor: '#ffffff', borderWidth: 2 } },
      },
    ],
  }
}
const probabilities = computed(() => heatmap(false))
const labels = computed(() => heatmap(true))
const bins = computed(() => {
  const values = frame.value?.probabilities.flat() ?? []
  return Array.from({ length: 10 }, (_, i) => ({
    lower: i / 10,
    upper: (i + 1) / 10,
    count: values.filter(
      (p) => p >= i / 10 && (i === 9 ? p <= 1 : p < (i + 1) / 10),
    ).length,
  }))
})
</script>
<template>
  <section aria-label="历史预测复盘">
    <h3>历史预测复盘</h3>
    <p>查看当时冻结的价格区间。真实标签：1 为触达、0 为未触达，空白为未知。</p>
    <p v-if="page.error.value || detail.error.value" role="alert">
      复盘读取失败：{{ page.error.value || detail.error.value }}
    </p>
    <p v-if="page.pending.value || detail.pending.value" role="status">
      正在读取复盘…
    </p>
    <div class="toolbar">
      <button
        class="secondary"
        :disabled="offset === 0 || page.pending.value"
        @click="offset = Math.max(0, offset - 100)"
      >
        上一页
      </button>
      <span
        >共 {{ page.data.value?.total ?? 0 }} 个起点 · 第
        {{ offset + 1 }} 项起</span
      >
      <button
        class="secondary"
        :disabled="
          offset + 100 >= (page.data.value?.total ?? 0) || page.pending.value
        "
        @click="offset += 100"
      >
        下一页
      </button>
    </div>
    <label
      >预测时刻（UTC）<select
        v-model="timestamp"
        :disabled="page.pending.value"
      >
        <option
          v-for="item in page.data.value?.origins"
          :key="item.timestamp_us"
          :value="String(item.timestamp_us)"
        >
          {{ new Date(item.timestamp_us / 1000).toISOString() }} ·
          {{ item.reference_price }}
        </option>
      </select></label
    >
    <template v-if="frame">
      <p>
        参考价 {{ frame.grid.reference_price }} · 模型 {{ frame.model }} ·
        {{ frame.status === 'ready' ? '有效预测' : '超分布：实时会暂停发布' }}
      </p>
      <p class="notice">
        预测概率使用与实时矩阵一致的连续红色色阶；色深按概率平方根映射，增强低概率细节，图例显示真实百分比。
      </p>
      <div class="chart-grid">
        <div class="matrix-scroll">
          <h4>预测触达概率</h4>
          <Chart :option="probabilities" label="历史冻结预测概率矩阵" />
          <ProbabilityLegend />
        </div>
        <div class="matrix-scroll">
          <h4>实际触达标签</h4>
          <Chart :option="labels" label="历史实际触达标签矩阵" />
        </div>
      </div>
      <details>
        <summary>该矩阵的预测概率分布</summary>
        <table>
          <thead>
            <tr>
              <th>概率区间</th>
              <th>格子数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="bin in bins" :key="bin.lower">
              <td>{{ bin.lower.toFixed(1) }}–{{ bin.upper.toFixed(1) }}</td>
              <td>{{ bin.count }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
    <p v-else-if="!page.pending.value && !detail.pending.value">
      当前范围没有可展示的历史预测；报告若已更新，请刷新后重试。
    </p>
  </section>
</template>

<style scoped>
.toolbar {
  flex-wrap: wrap;
}
select {
  width: 100%;
  min-width: 0;
}
.chart-grid > div {
  min-width: 0;
}
</style>
