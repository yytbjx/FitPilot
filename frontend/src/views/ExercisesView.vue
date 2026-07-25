<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api, { unwrap } from '@/api/client'

const q = ref('')
const bodyPart = ref<string | undefined>()
const equipment = ref<string | undefined>()
const muscle = ref<string | undefined>()
const items = ref<any[]>([])
const total = ref(0)
const facets = ref<{ body_parts: string[]; equipments: string[]; muscles: string[]; total: number }>({
  body_parts: [],
  equipments: [],
  muscles: [],
  total: 0,
})
const detail = ref<any | null>(null)
const drawerOpen = ref(false)
const shuffling = ref(false)

async function loadFacets() {
  facets.value = unwrap(await api.get('/exercises/facets'))
}

async function load() {
  const data = unwrap<{ items?: any[]; total?: number; count?: number }>(
    await api.get('/exercises', {
      params: {
        q: q.value || undefined,
        body_part: bodyPart.value || undefined,
        equipment: equipment.value || undefined,
        muscle: muscle.value || undefined,
        limit: 50,
      },
    }),
  )
  items.value = data.items || []
  total.value = data.total || 0
}

async function shuffle() {
  shuffling.value = true
  try {
    const data = unwrap<{ items?: any[]; count?: number }>(
      await api.post('/exercises/shuffle', {
        body_parts: bodyPart.value ? [bodyPart.value] : [],
        equipments: equipment.value ? [equipment.value] : [],
        exclude_ids: items.value.map((x) => x.id),
        limit: 6,
      }),
    )
    items.value = data.items || []
    total.value = data.count || items.value.length
  } finally {
    shuffling.value = false
  }
}

async function openDetail(row: any) {
  detail.value = unwrap(await api.get(`/exercises/${row.id}`))
  drawerOpen.value = true
}

onMounted(async () => {
  await loadFacets()
  await load()
})
</script>

<template>
  <div class="page">
    <h2>动作库</h2>
    <p style="color: #666; margin-top: -8px">
      数据来自 exercises-dataset（MIT 文本）；筛选理念参考 workout.cool（器械 × 部位）。共
      {{ facets.total }} 条，当前匹配 {{ total }} 条。媒体 GIF 因版权未入库。
    </p>
    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px">
      <el-input v-model="q" placeholder="搜索动作名/肌群" style="max-width: 240px" @keyup.enter="load" />
      <el-select v-model="bodyPart" clearable placeholder="部位" style="width: 160px" @change="load">
        <el-option v-for="b in facets.body_parts" :key="b" :label="b" :value="b" />
      </el-select>
      <el-select v-model="equipment" clearable filterable placeholder="器械" style="width: 180px" @change="load">
        <el-option v-for="e in facets.equipments" :key="e" :label="e" :value="e" />
      </el-select>
      <el-select v-model="muscle" clearable filterable placeholder="目标肌群" style="width: 160px" @change="load">
        <el-option v-for="m in facets.muscles" :key="m" :label="m" :value="m" />
      </el-select>
      <el-button type="primary" @click="load">搜索</el-button>
      <el-button :loading="shuffling" @click="shuffle">换一组</el-button>
    </div>

    <el-table :data="items" stripe @row-click="openDetail" style="cursor: pointer">
      <el-table-column prop="display_name" label="名称" min-width="180" />
      <el-table-column prop="name_en" label="英文" min-width="160" />
      <el-table-column prop="body_part" label="部位" width="120" />
      <el-table-column prop="equipment" label="器械" width="140" />
      <el-table-column prop="primary_muscle" label="目标肌群" width="140" />
    </el-table>

    <el-drawer v-model="drawerOpen" title="动作详情" size="420px">
      <template v-if="detail">
        <h3>{{ detail.display_name || detail.name_zh || detail.name_en }}</h3>
        <p><b>英文：</b>{{ detail.name_en }}</p>
        <p><b>部位 / 器械：</b>{{ detail.body_part }} · {{ detail.equipment }}</p>
        <p><b>目标肌群：</b>{{ detail.primary_muscle }}</p>
        <p><b>协同：</b>{{ (detail.secondary_muscles || []).join(', ') || '—' }}</p>
        <h4>步骤（中文）</h4>
        <ol>
          <li v-for="(s, i) in detail.steps_zh || []" :key="i">{{ s }}</li>
        </ol>
        <p v-if="!(detail.steps_zh || []).length" style="white-space: pre-wrap">{{ detail.instructions_zh }}</p>
        <p style="color: #999; font-size: 12px">{{ detail.media_note }}</p>
      </template>
    </el-drawer>
  </div>
</template>
