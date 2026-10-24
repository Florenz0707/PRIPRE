<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchHealth } from './api'

const status = ref<'loading' | 'online' | 'offline'>('loading')
const version = ref('')

async function refresh() {
  status.value = 'loading'
  try {
    const health = await fetchHealth()
    version.value = health.version
    status.value = 'online'
  } catch {
    status.value = 'offline'
  }
}

onMounted(refresh)
</script>

<template>
  <main>
    <header>
      <p class="eyebrow">PRIPRE / RESEARCH WORKSPACE</p>
      <h1>价格区间触达概率研究</h1>
      <p class="intro">
        从真实成交出发，估计未来窗口内的触达概率，并用实际频率检验预测。
      </p>
    </header>
    <section class="connection" aria-labelledby="service-title">
      <div>
        <h2 id="service-title">服务连接</h2>
        <p role="status" aria-live="polite">
          <template v-if="status === 'loading'">正在连接后端…</template>
          <template v-else-if="status === 'online'"
            >后端已连接 · v{{ version }}</template
          >
          <template v-else>后端暂时不可用，请检查服务后重试。</template>
        </p>
      </div>
      <button :disabled="status === 'loading'" @click="refresh">
        重新检查
      </button>
    </section>
    <section aria-labelledby="research-title">
      <h2 id="research-title">研究流程</h2>
      <div class="cards">
        <article>
          <span>01</span>
          <h3>成交数据</h3>
          <p>历史回放与实时订阅，统一成交口径和质量检查。</p>
        </article>
        <article>
          <span>02</span>
          <h3>概率矩阵</h3>
          <p>按价格区间与未来时间窗，估计至少一次成交触达的概率。</p>
        </article>
        <article>
          <span>03</span>
          <h3>校准回测</h3>
          <p>跨波动阶段比较预测概率与真实频率。</p>
        </article>
      </div>
    </section>
    <p class="notice">当前为项目框架阶段，尚未接入行情、概率模型或回测结果。</p>
  </main>
</template>
