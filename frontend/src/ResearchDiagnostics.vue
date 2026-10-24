<script setup lang="ts">
import { computed } from 'vue'
import type { ExperimentReport, ResearchReport } from './api'
import { useRemoteJSON } from './useRemoteJSON'
const props = defineProps<{ report: ResearchReport }>()
const url = computed(() => `/api/experiments?run=${props.report.run_id ?? ''}`)
const experiments = useRemoteJSON<ExperimentReport>(url)
const fmt = (n: number) => n.toFixed(5)
</script>
<template>
  <details>
    <summary>全量数据覆盖、排除审计与开发实验</summary>
    <p>
      以下覆盖和实验说明属于完整报告，不随上方日期筛选变化。回放起点间隔
      {{ report.origin_stride_seconds ?? 60 }} 秒；实时更新仍为每秒。
    </p>
    <p v-if="report.origin_audit">
      候选起点 {{ report.origin_audit.candidate_origins }}，有效
      {{ report.origin_audit.accepted_origins }}，排除
      {{
        report.origin_audit.excluded_origins
      }}。有效起点包含训练与预热日期，不能全部解释为样本外测试。
    </p>
    <ul>
      <li
        v-for="(count, reason) in report.origin_audit?.excluded_by_reason"
        :key="reason"
      >
        {{ reason }}：{{ count }}
      </li>
    </ul>
    <template v-if="report.stage_analysis">
      <p>
        特殊事件为日内绝对收益前 5%
        的日期；每日采样不等于覆盖整个事件。趋势标注为事后诊断，不用于预测。
      </p>
      <p>事件日期：{{ report.stage_analysis.event_dates.join('、') }}</p>
      <p>
        有样本外成交样本的事件日期：{{
          report.stage_analysis.sampled_event_dates.join('、')
        }}
      </p>
      <p
        v-for="(days, phase) in report.stage_analysis.phase_dates"
        :key="phase"
      >
        {{ phase }}：{{ days.length }} 日
      </p>
    </template>
    <p v-if="experiments.pending.value">正在读取实验…</p>
    <p v-if="experiments.error.value">
      尚无可用参数实验，请运行 experiments 命令。
    </p>
    <template v-if="experiments.data.value">
      <p
        v-if="
          experiments.data.value.dataset_fingerprint !==
          report.dataset_fingerprint
        "
        role="alert"
      >
        实验与当前报告的数据指纹不同，请重新执行实验。
      </p>
      <h3>参数与抽样误差（开发集）</h3>
      <p>
        训练 {{ experiments.data.value.train_dates.join(' 至 ') }}；开发
        {{ experiments.data.value.validation_dates.join(' 至 ') }}，{{
          experiments.data.value.validation_origins
        }}
        个起点；本轮不参与实验的日期
        {{
          experiments.data.value.untouched_test_dates.join(' 至 ')
        }}。末端日期曾在首次报告中查看过，不是全新独立测试集。
      </p>
      <p>
        实验不自动改变实时模型。不同路径长度的目标不同，不跨长度排名；4096
        路径参考仍有抽样误差。
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>路径数</th>
              <th>种子数</th>
              <th>平均格子标准差</th>
              <th>最大格子标准差</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in experiments.data.value.monte_carlo"
              :key="row.paths"
            >
              <td>{{ row.paths }}</td>
              <td>{{ row.seeds }}</td>
              <td>{{ fmt(row.mean_cell_std) }}</td>
              <td>{{ fmt(row.max_cell_std) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>路径数 / 种子</th>
              <th>候选比例 / 下限</th>
              <th>价格映射</th>
              <th>长度 / 起点间隔（秒）</th>
              <th>开发 Brier</th>
              <th>对参考 RMSE</th>
              <th>耗时 ms</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in experiments.data.value.variants" :key="i">
              <td>{{ row.count }} / {{ row.seed }}</td>
              <td>{{ row.fraction.toFixed(2) }} / {{ row.minimum }}</td>
              <td>{{ row.mapping }}</td>
              <td>{{ row.horizon }} / {{ row.stride }}</td>
              <td>{{ fmt(row.brier) }}</td>
              <td>{{ fmt(row.rmse_vs_4096_paths) }}</td>
              <td>{{ row.mean_ms.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </details>
</template>
