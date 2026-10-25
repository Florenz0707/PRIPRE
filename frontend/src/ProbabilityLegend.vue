<script setup lang="ts">
import { probabilityGradient, probabilityTicks } from './heatmap'
</script>

<template>
  <div class="probability-legend" role="group" aria-label="触达概率红色色标">
    <p class="legend-title">触达概率 · 浅红低，深红高</p>
    <div class="legend-bar" :style="{ background: probabilityGradient }"></div>
    <div class="legend-ticks">
      <span
        v-for="tick in probabilityTicks"
        :key="tick.label"
        :style="{ left: tick.position }"
        >{{ tick.label }}</span
      >
    </div>
  </div>
</template>

<style scoped>
.probability-legend {
  min-width: 740px;
  padding: 0 20px 24px 135px;
  color: #50666e;
  font-size: 12px;
}
.legend-title {
  margin: 0 0 8px;
  font-size: 12px;
}
.legend-bar {
  height: 12px;
  border: 1px solid #e8c9c9;
  border-radius: 3px;
}
.legend-ticks {
  position: relative;
  height: 24px;
}
.legend-ticks span {
  position: absolute;
  padding-top: 9px;
  transform: translateX(-50%);
}
.legend-ticks span::before {
  position: absolute;
  top: 0;
  left: 50%;
  height: 5px;
  border-left: 1px solid #9a6464;
  content: '';
}
</style>
