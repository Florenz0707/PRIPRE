<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import type { ResearchReport } from './api'
import Chart from './Chart.vue'
import GroupMetrics from './GroupMetrics.vue'
import ReplayPanel from './ReplayPanel.vue'
import ResearchDiagnostics from './ResearchDiagnostics.vue'
import { useRemoteJSON } from './useRemoteJSON'

const props = defineProps<{ report: ResearchReport }>()
const model = shallowRef(props.report.model)
const start = shallowRef('')
const end = shallowRef('')
const applied = shallowRef({ start: '', end: '' })
const formError = shallowRef('')
const query = computed(() => {
  if (!applied.value.start && !applied.value.end) return null
  const params = new URLSearchParams()
  if (applied.value.start) params.set('start', applied.value.start)
  if (applied.value.end) params.set('end', applied.value.end)
  return `/api/research?${params}`
})
const filtered = useRemoteJSON<ResearchReport>(query)
const report = computed(() =>
  query.value ? filtered.data.value : props.report,
)
function applyRange() {
  formError.value = ''
  if (start.value && end.value && start.value > end.value) {
    formError.value = '起始日期不能晚于结束日期。'
    return
  }
  applied.value = { start: start.value, end: end.value }
}
function resetRange() {
  start.value = ''
  end.value = ''
  applyRange()
}
watch(() => props.report, resetRange)
watch(
  () => props.report.model,
  (value) => {
    model.value = value
  },
)
const selected = computed(() => report.value?.models[model.value])
const days = computed(() => report.value?.market_context ?? [])
const labels: Record<string, string> = {
  'frequency-baseline': '分状态历史频率',
  'empirical-baseline': '历史路径基准',
  'conditional-raw': '条件原始概率',
  'conditional-calibrated': '条件校准概率',
}
const fmt = (value: number | null | undefined) =>
  value == null ? '—' : value.toFixed(5)
const reliability = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0 },
  grid: { left: 55, right: 20, top: 25, bottom: 65 },
  xAxis: {
    type: 'value',
    min: 0,
    max: 1,
    name: '预测概率',
    nameLocation: 'middle',
    nameGap: 28,
  },
  yAxis: { type: 'value', min: 0, max: 1, name: '实际频率' },
  series: [
    {
      name: '理想校准',
      type: 'line',
      data: [
        [0, 0],
        [1, 1],
      ],
      symbol: 'none',
      lineStyle: { type: 'dashed', color: '#94a3a8' },
    },
    {
      name: '样本结果',
      type: 'line',
      data:
        selected.value?.summary.reliability
          .filter((bin) => bin.count > 0)
          .map((bin) => [bin.predicted, bin.observed]) ?? [],
      lineStyle: { color: '#16775f' },
    },
  ],
}))
const market = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 70, right: 20, top: 20, bottom: 60 },
  xAxis: { type: 'category', data: days.value.map((day) => day.date) },
  yAxis: {
    type: 'value',
    scale: true,
    name: `${props.report.config.instrument.base} / ${props.report.config.instrument.quote}`,
  },
  dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }],
  series: [
    {
      type: 'line',
      data: days.value.map((day) => day.close),
      symbol: 'none',
      lineStyle: { color: '#16775f' },
    },
  ],
}))
const volatility = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 70, right: 20, top: 30, bottom: 35 },
  xAxis: { type: 'category', data: days.value.map((day) => day.date) },
  yAxis: { type: 'value', name: '分钟收益波动率' },
  series: [
    {
      type: 'line',
      data: days.value.map((day) => day.volatility),
      symbol: 'none',
      lineStyle: { color: '#b27020' },
    },
  ],
}))
const distances = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 55, right: 20, top: 25, bottom: 45 },
  xAxis: {
    type: 'category',
    name: '距中心格数',
    data: selected.value?.by_distance.map((row) => row.distance_steps) ?? [],
  },
  yAxis: { type: 'value', name: 'Brier' },
  series: [
    {
      type: 'line',
      data: selected.value?.by_distance.map((row) => row.brier) ?? [],
      lineStyle: { color: '#16775f' },
    },
  ],
}))
const windows = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 55, right: 20, top: 25, bottom: 45 },
  xAxis: {
    type: 'category',
    name: '窗口起点 / 秒',
    data: selected.value?.by_window.map((row) => row.start_seconds) ?? [],
  },
  yAxis: { type: 'value', name: 'Brier' },
  series: [
    {
      type: 'line',
      data: selected.value?.by_window.map((row) => row.brier) ?? [],
      lineStyle: { color: '#16775f' },
    },
  ],
}))
</script>
<template>
  <div class="research-panel">
    <div class="panel-heading">
      <div>
        <h2>校准与历史研究</h2>
        <p>分钟上下文与成交级回测分别记录覆盖范围。</p>
      </div>
      <label
        >评估模型<select v-model="model">
          <option
            v-for="(_, name) in props.report.models"
            :key="name"
            :value="name"
          >
            {{ labels[name] ?? name }}
          </option>
        </select></label
      >
    </div>
    <form class="date-filter" @submit.prevent="applyRange">
      <label>起始日期（UTC）<input v-model="start" type="date" /></label>
      <label>结束日期（UTC）<input v-model="end" type="date" /></label>
      <button type="submit" :disabled="filtered.pending.value">应用范围</button>
      <button type="button" class="secondary" @click="resetRange">
        全范围
      </button>
    </form>
    <p v-if="formError || filtered.error.value" role="alert">
      {{ formError || `研究读取失败：${filtered.error.value}` }}
    </p>
    <p v-if="filtered.pending.value" role="status">
      正在汇总所选日期的样本外预测…
    </p>
    <template v-if="report">
      <p class="notice">
        指标范围：{{ applied.start || '最早日期' }} 至
        {{
          applied.end || '报告末端'
        }}。日期筛选同步影响校准、分组和行情；不重新训练模型。
      </p>
      <p v-if="report.selection?.origins === 0">
        所选范围没有样本外预测；下方空指标不代表误差为零。
      </p>
      <div class="metrics-row">
        <div>
          <span>分钟记录</span
          ><strong>{{ report.data.minute_rows.toLocaleString() }}</strong>
        </div>
        <div>
          <span>成交样本日期</span
          ><strong>{{ report.data.sample_dates.length }}</strong>
        </div>
        <div>
          <span>成交记录</span
          ><strong>{{ report.data.trade_rows.toLocaleString() }}</strong>
        </div>
        <div>
          <span>模型计算 P95</span
          ><strong>{{ report.latency_ms.p95.toFixed(1) }} ms</strong>
        </div>
      </div>
      <p class="notice">
        覆盖：{{
          report.data.minute_start_us
            ? new Date(report.data.minute_start_us / 1000)
                .toISOString()
                .slice(0, 10)
            : '—'
        }}
        至
        {{
          report.data.minute_end_us
            ? new Date(report.data.minute_end_us / 1000)
                .toISOString()
                .slice(0, 16) + ' UTC'
            : '—'
        }}。分钟间断
        {{ report.data.minute_gap_count }} 处。精确触达仅在抽样成交窗口内验证。
      </p>
      <div class="table-scroll">
        <table>
          <caption>
            相同测试集上的模型比较
          </caption>
          <thead>
            <tr>
              <th>模型</th>
              <th>Brier ↓</th>
              <th>已知格子数</th>
              <th>未知格子数</th>
              <th>按日重采样 95% 区间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(result, name) in report.models" :key="name">
              <td>{{ labels[name] ?? name }}</td>
              <td>{{ fmt(result.summary.brier) }}</td>
              <td>{{ result.summary.count.toLocaleString() }}</td>
              <td>{{ result.summary.unknown }}</td>
              <td>
                {{
                  result.day_block_brier_95?.map(fmt).join(' – ') ?? '样本不足'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="chart-grid">
        <section>
          <h3>可靠性曲线</h3>
          <Chart :option="reliability" label="预测概率与实际触达频率" />
        </section>
        <GroupMetrics title="不同波动阶段" :rows="selected?.by_regime ?? []" />
      </div>
      <div class="chart-grid">
        <section>
          <h3>价格距离误差</h3>
          <Chart :option="distances" label="按价格距离分组的 Brier 分数" />
        </section>
        <section>
          <h3>时间窗口误差</h3>
          <Chart :option="windows" label="按未来时间窗口分组的 Brier 分数" />
        </section>
      </div>
      <div class="panel-heading">
        <h3>所选范围行情上下文</h3>
      </div>
      <Chart
        :option="market"
        :label="`研究日期范围的 ${report.config.instrument.base} 价格`"
      />
      <Chart :option="volatility" label="研究日期范围的市场波动阶段" />
      <details>
        <summary>滚动验证区间与限制</summary>
        <p v-if="report.warmup_dates?.length">
          初始预热：{{ report.warmup_dates[0] }} 至
          {{ report.warmup_dates.at(-1) }}；这些日期不作为样本外测试。
        </p>
        <ul>
          <li v-for="(fold, i) in report.folds" :key="i">
            第 {{ i + 1 }} 折：训练 {{ fold.train_start }}–{{
              fold.train_end
            }}；校准 {{ fold.calibration_start }}–{{
              fold.calibration_end
            }}；测试 {{ fold.test_start }}–{{ fold.test_end }}。
          </li>
          <li v-for="item in report.limitations" :key="item">{{ item }}</li>
        </ul>
      </details>
      <details>
        <summary>分组样本量与不确定性</summary>
        <h3>可靠性分箱</h3>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>预测概率均值</th>
                <th>实际触达频率</th>
                <th>格子数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(bin, i) in selected?.summary.reliability" :key="i">
                <td>{{ fmt(bin.predicted) }}</td>
                <td>{{ fmt(bin.observed) }}</td>
                <td>{{ bin.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <GroupMetrics
          title="价格距离（格数）"
          :rows="selected?.by_distance ?? []"
          axis="distance_steps"
        />
        <GroupMetrics
          title="窗口起点（秒）"
          :rows="selected?.by_window ?? []"
          axis="start_seconds"
        />
        <GroupMetrics
          title="趋势与震荡（事后标注）"
          :rows="selected?.by_phase ?? []"
        />
        <GroupMetrics title="特殊事件日期" :rows="selected?.by_event ?? []" />
        <GroupMetrics title="超出训练分布" :rows="selected?.by_anomaly ?? []" />
      </details>
      <p v-if="selected?.live_policy">
        超分布暂停 {{ selected.live_policy.suppressed_origins }} 个起点（{{
          ((selected.live_policy.suppression_ratio ?? 0) * 100).toFixed(2)
        }}%）；剩余发布起点 Brier
        {{
          fmt(selected.live_policy.published.brier)
        }}。完整研究指标仍包含被暂停起点。
      </p>
      <ReplayPanel
        v-if="props.report.run_id"
        :start="applied.start"
        :end="applied.end"
        :model="model"
        :run-id="props.report.run_id"
      />
    </template>
    <ResearchDiagnostics :report="props.report" />
  </div>
</template>
