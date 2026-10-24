<script setup lang="ts">
import type { GroupMetrics } from './api'
defineProps<{
  title: string
  rows: GroupMetrics[]
  axis?: 'regime' | 'distance_steps' | 'start_seconds'
}>()
const labels: Record<string, string> = {
  low: '低波动',
  normal: '常规波动',
  high: '高波动',
  uptrend: '上行趋势',
  downtrend: '下行趋势',
  range: '震荡',
  unclassified: '未分类',
  out_of_distribution: '超出训练分布',
  in_distribution: '训练分布内',
  extreme_day: '特殊事件日',
  ordinary_day: '普通日',
}
const fmt = (n: number | null | undefined) => (n == null ? '—' : n.toFixed(5))
</script>
<template>
  <section>
    <h3>{{ title }}</h3>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>分组</th>
            <th>Brier</th>
            <th>格子数 / 未知</th>
            <th>起点 / 日期数</th>
            <th>按日 95% 区间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row[axis ?? 'regime'])">
            <td>
              {{
                labels[String(row[axis ?? 'regime'])] ?? row[axis ?? 'regime']
              }}
            </td>
            <td>{{ fmt(row.brier) }}</td>
            <td>{{ row.count }} / {{ row.unknown }}</td>
            <td>{{ row.origins ?? '—' }} / {{ row.dates ?? '—' }}</td>
            <td>
              {{ row.day_block_brier_95?.map(fmt).join(' – ') ?? '样本不足' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
