<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import type { ResearchReport } from './api'
import Chart from './Chart.vue'

const props = defineProps<{ report: ResearchReport }>()
const model = ref(props.report.model)
const start = ref('')
const end = ref('')
watch(
  () => props.report.model,
  (value) => {
    model.value = value
  },
)
const selected = computed(() => props.report.models[model.value])
const days = computed(() =>
  props.report.market_context.filter(
    (day) =>
      (!start.value || day.date >= start.value) &&
      (!end.value || day.date <= end.value),
  ),
)
const labels: Record<string, string> = {
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
          <option v-for="(_, name) in report.models" :key="name" :value="name">
            {{ labels[name] ?? name }}
          </option>
        </select></label
      >
    </div>
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
      <section>
        <h3>不同波动阶段</h3>
        <table>
          <thead>
            <tr>
              <th>阶段</th>
              <th>Brier</th>
              <th>格子数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in selected?.by_regime" :key="row.regime">
              <td>
                {{
                  { low: '低波动', normal: '常规', high: '高波动' }[
                    row.regime
                  ] ?? row.regime
                }}
              </td>
              <td>{{ fmt(row.brier) }}</td>
              <td>{{ row.count }}</td>
            </tr>
          </tbody>
        </table>
        <p>
          分组阈值只使用对应折的训练数据。超出分布的预测起点共
          {{ report.out_of_distribution_origins }} 个，仍计入研究误差。
        </p>
      </section>
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
      <h3>全周期行情上下文</h3>
      <div class="date-filter">
        <label>起始日期<input v-model="start" type="date" /></label
        ><label>结束日期<input v-model="end" type="date" /></label>
      </div>
    </div>
    <p class="notice">
      日期筛选只影响下方行情图；上方概率指标来自报告中的完整样本外测试集。
    </p>
    <Chart :option="market" label="研究日期范围的 BTC 价格" />
    <Chart :option="volatility" label="研究日期范围的市场波动阶段" />
    <details>
      <summary>滚动验证区间与限制</summary>
      <ul>
        <li v-for="(fold, i) in report.folds" :key="i">
          第 {{ i + 1 }} 折：训练 {{ fold.train_start }}–{{
            fold.train_end
          }}；校准 {{ fold.calibration_start }}–{{ fold.calibration_end }}；测试
          {{ fold.test_start }}–{{ fold.test_end }}。
        </li>
        <li v-for="item in report.limitations" :key="item">{{ item }}</li>
      </ul>
    </details>
  </div>
</template>
