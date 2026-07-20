<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api, { unwrap } from '@/api/client'

const q = ref('')
const source = ref<string | undefined>()
const items = ref<any[]>([])
const total = ref(0)

async function load() {
  const data = unwrap(
    await api.get('/foods', {
      params: {
        q: q.value || undefined,
        source: source.value || undefined,
        limit: 100,
      },
    }),
  )
  items.value = data.items || []
  total.value = data.total ?? data.count ?? items.value.length
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>食物库</h2>
    <p style="color: #666; margin-top: -8px">
      中文常用食物（manual）+ USDA Foundation Foods 宏量营养（每 100g）。当前 {{ total }} 条。
    </p>
    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px">
      <el-input v-model="q" placeholder="搜索食物" style="max-width: 280px" @keyup.enter="load" />
      <el-select v-model="source" clearable placeholder="来源" style="width: 180px" @change="load">
        <el-option label="中文种子" value="manual" />
        <el-option label="USDA Foundation" value="usda-foundation" />
      </el-select>
      <el-button type="primary" @click="load">搜索</el-button>
    </div>
    <el-table :data="items" stripe>
      <el-table-column prop="name" label="名称" min-width="200" />
      <el-table-column prop="name_en" label="英文" min-width="180" />
      <el-table-column prop="source" label="来源" width="140" />
      <el-table-column prop="category" label="分类" width="140" />
      <el-table-column prop="kcal_per_100g" label="kcal/100g" width="110" />
      <el-table-column prop="protein_g_per_100g" label="蛋白" width="90" />
      <el-table-column prop="carb_g_per_100g" label="碳水" width="90" />
      <el-table-column prop="fat_g_per_100g" label="脂肪" width="90" />
    </el-table>
  </div>
</template>
