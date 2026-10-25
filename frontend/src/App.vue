<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { EChartsOption } from 'echarts'
import { fetchHealth, getJSON, type ResearchReport, type Settings } from './api'
import { createLiveConnection } from './live'
import Chart from './Chart.vue'
import ResearchPanel from './ResearchPanel.vue'

const health = ref('正在连接后端…')
const settings = ref<Settings | null>(null)
const report = ref<ResearchReport | null>(null)
const reportError = ref('')
const tab = ref<'live' | 'research'>('live')
const live = createLiveConnection()
const frame = live.snapshot
const statusLabels: Record<string, string> = {
  starting: '服务正在启动',
  disabled: '实时采集尚未启用',
  disconnected: '行情连接中或已中断',
  warming_up: '正在积累 60 秒连续行情',
  stale: '行情已过期，矩阵暂停',
  clock_unavailable: '行情校时已失效，矩阵暂停',
  model_unavailable: '模型尚未就绪，请检查本地样本',
  ready: '实时概率矩阵',
  out_of_distribution: '波动超出训练范围，矩阵暂停',
  calculation_overdue: '计算超时，矩阵暂停',
  model_error: '模型计算失败',
  journal_error: '预测日志写入失败，矩阵暂停',
  connection_stale: '推送已过期，等待重连',
  connection_lost: '服务连接中断，正在重连',
  invalid_response: '矩阵数据无效',
}
const frameStatus = computed(() =>
  frame.value
    ? (statusLabels[frame.value.status] ?? frame.value.status)
    : '等待矩阵状态…',
)
const matrixOption = computed<EChartsOption>(() => {
  const current = frame.value
  if (current?.status !== 'ready' || !current.grid || !current.probabilities)
    return {}
  const grid = current.grid
  return {
    animation: false,
    tooltip: { position: 'top' },
    grid: { left: 135, right: 20, top: 15, bottom: 90 },
    xAxis: {
      type: 'category',
      data: grid.windows.map(
        (window) =>
          `+${Math.round((window.start_us - grid.timestamp_us) / 1e6)}s`,
      ),
      splitArea: { show: true },
      name: '未来窗口',
    },
    yAxis: {
      type: 'category',
      data: grid.prices.map(
        (price) =>
          `[${Number(price.lower).toFixed(2)}, ${Number(price.upper).toFixed(2)})`,
      ),
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 10,
      text: ['100%', '0%'],
      inRange: { color: ['#f2f6f4', '#b5d8c8', '#388f72', '#115344'] },
    },
    series: [
      {
        type: 'heatmap',
        data: current.probabilities.flatMap((row, y) =>
          row.map((p, x) => [x, y, Number(p.toFixed(4))]),
        ),
        emphasis: { itemStyle: { borderColor: '#173f35', borderWidth: 1 } },
      },
    ],
  }
})
async function refresh() {
  health.value = '正在连接后端…'
  try {
    const data = await fetchHealth()
    health.value = `后端已连接 · v${data.version}`
  } catch {
    health.value = '后端暂时不可用，请检查服务后重试。'
  }
}
async function loadReport() {
  reportError.value = ''
  try {
    report.value = await getJSON<ResearchReport>('/api/research')
  } catch {
    report.value = null
    reportError.value = '尚无可用研究报告，请完成数据采集并运行回测。'
  }
}
onMounted(async () => {
  live.connect()
  await Promise.allSettled([
    refresh(),
    loadReport(),
    getJSON<Settings>('/api/config').then((data) => {
      settings.value = data
    }),
  ])
})
onBeforeUnmount(live.stop)
</script>
<template>
  <main>
    <header>
      <p class="eyebrow">PRIPRE / PROBABILITY RESEARCH</p>
      <h1>价格区间触达概率研究</h1>
      <p class="intro">
        估计未来窗口内至少一次成交触达的概率，用实际频率检验预测。
      </p>
    </header>
    <div class="toolbar">
      <p role="status" aria-live="polite">{{ health }}</p>
      <button class="secondary" @click="refresh">重新检查</button>
    </div>
    <nav aria-label="研究视图">
      <button :aria-pressed="tab === 'live'" @click="tab = 'live'">
        实时概率</button
      ><button :aria-pressed="tab === 'research'" @click="tab = 'research'">
        校准与回测
      </button>
    </nav>
    <section v-if="tab === 'live'" class="panel" aria-labelledby="matrix-title">
      <div class="panel-heading">
        <div>
          <h2 id="matrix-title">{{ frameStatus }}</h2>
          <p>
            {{ settings?.instrument?.base ?? 'BTC' }} /
            {{ settings?.instrument?.quote ?? 'USDT' }} ·
            {{ settings?.source?.provider ?? 'binance' }} · 每秒共享更新
          </p>
        </div>
        <span
          class="status-badge"
          :class="{ active: frame?.status === 'ready' }"
          >{{ frame?.status === 'ready' ? '运行中' : '等待有效预测' }}</span
        >
      </div>
      <div class="metrics-row">
        <div>
          <span>参考成交价</span
          ><strong>{{
            frame?.reference_price
              ? Number(frame.reference_price).toLocaleString(undefined, {
                  maximumFractionDigits: 2,
                })
              : '—'
          }}</strong>
        </div>
        <div>
          <span>计算耗时</span
          ><strong>{{ frame?.calculation_ms?.toFixed(1) ?? '—' }} ms</strong>
        </div>
        <div>
          <span>共享客户端</span
          ><strong
            >{{ frame?.clients ?? 0 }} /
            {{ settings?.runtime.max_clients ?? 50 }}</strong
          >
        </div>
        <div>
          <span>更新时间</span
          ><strong>{{
            frame?.timestamp_us
              ? new Date(frame.timestamp_us / 1000).toLocaleTimeString()
              : '—'
          }}</strong>
        </div>
      </div>
      <template v-if="frame?.status === 'ready'"
        ><div class="matrix-scroll">
          <Chart
            :option="matrixOption"
            label="价格区间与未来时间窗口的触达概率热力图"
          />
        </div>
        <p class="notice">
          颜色表示窗口内至少一笔成交触达的概率。区间与时间窗左闭右开，各格概率之和不必为
          100%。
        </p></template
      >
      <div v-else class="empty-state">
        <h3>{{ frameStatus }}</h3>
        <p>只有行情连续、新鲜且模型就绪时才展示有效概率。</p>
        <p v-if="frame?.status === 'disabled'">
          在项目配置中启用实时行情后重启服务。
        </p>
      </div>
      <p v-if="settings" class="notice">
        价格步长 {{ settings.grid.price_step }}
        {{ settings.instrument?.quote }} ·
        {{ settings.grid.half_width * 2 + 1 }} 个价格区间 · 窗口
        {{ settings.grid.window_seconds }} 秒 · 从 +{{
          settings.grid.first_window_seconds
        }}
        秒至 +{{ settings.grid.horizon_seconds }} 秒。参数由项目配置文件提供。
      </p>
    </section>
    <section v-else class="panel">
      <div class="toolbar">
        <p>
          当前报告：{{
            report?.generated_at
              ? new Date(report.generated_at).toLocaleString()
              : '尚未生成'
          }}
        </p>
        <button class="secondary" @click="loadReport">刷新报告</button>
      </div>
      <ResearchPanel v-if="report" :report="report" />
      <p v-else class="empty-state">{{ reportError || '正在读取研究报告…' }}</p>
    </section>
    <footer>请结合校准结果、样本覆盖与不同波动阶段评估概率质量。</footer>
  </main>
</template>
