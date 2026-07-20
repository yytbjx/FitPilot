<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import api, { unwrap } from '@/api/client'

const plans = ref<any>(null)
const previewData = ref<any>(null)
const approving = ref(false)
const adjusting = ref(false)

const diffItems = computed(() => {
  const d = previewData.value?.diff
  if (!d) return []
  const items: { kind: string; text: string }[] = []

  for (const c of d.changes || []) {
    const field = String(c.field || '')
    const kind = field.startsWith('diet') ? '饮食' : '训练'
    const before = typeof c.before === 'object' ? JSON.stringify(c.before) : String(c.before ?? '—')
    const after = typeof c.after === 'object' ? JSON.stringify(c.after) : String(c.after ?? '—')
    items.push({ kind, text: `${field}: ${before} → ${after}` })
  }

  for (const w of d.workout_changes || []) {
    items.push({ kind: '训练', text: String(w) })
  }
  for (const x of d.diet_changes || []) {
    items.push({ kind: '饮食', text: String(x) })
  }

  const weekly = previewData.value?.weekly_changes
  if (weekly && typeof weekly === 'object') {
    for (const [k, v] of Object.entries(weekly)) {
      items.push({ kind: '周调整', text: `${k}: ${JSON.stringify(v)}` })
    }
  }

  return items
})

async function load() {
  plans.value = unwrap(await api.get('/plans/current'))
}

async function preview() {
  previewData.value = unwrap(await api.post('/plans/preview', {}))
}

async function weeklyAdjust() {
  adjusting.value = true
  try {
    previewData.value = unwrap(await api.post('/plans/weekly-adjust', {}))
  } finally {
    adjusting.value = false
  }
}

async function approve(okFlag: boolean) {
  approving.value = true
  try {
    const planId = previewData.value?.workout_plan_id || plans.value?.workout?.id
    if (!planId) return
    unwrap(await api.post(`/plans/${planId}/approve`, { approve: okFlag }))
    previewData.value = null
    await load()
  } finally {
    approving.value = false
  }
}
</script>

<template>
  <div class="page">
    <h2>训练 / 饮食计划</h2>
    <el-space wrap>
      <el-button type="primary" @click="preview">生成预览</el-button>
      <el-button :loading="adjusting" @click="weeklyAdjust">周联合调整</el-button>
      <el-button :loading="approving" type="success" @click="approve(true)">批准写入</el-button>
      <el-button @click="approve(false)">拒绝</el-button>
      <el-button @click="load">刷新</el-button>
    </el-space>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card header="当前计划">
          <div v-if="plans?.workout">
            <h4>训练 · {{ plans.workout.title }} (v{{ plans.workout.current_version }})</h4>
            <p v-if="plans.workout.latest?.content?.days">
              {{ plans.workout.latest.content.days.length }} 天课表
            </p>
          </div>
          <div v-if="plans?.diet" style="margin-top: 12px">
            <h4>饮食 · {{ plans.diet.title }}</h4>
            <p v-if="plans.diet.latest?.content?.daily_targets">
              目标热量 {{ plans.diet.latest.content.daily_targets.kcal }} kcal
            </p>
          </div>
          <el-empty v-if="!plans?.workout && !plans?.diet" description="暂无激活计划" />
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card header="预览 / 差异">
          <template v-if="previewData">
            <el-alert
              v-if="previewData.weekly_reason"
              :title="previewData.weekly_reason"
              type="info"
              show-icon
              style="margin-bottom: 12px"
            />
            <el-table v-if="diffItems.length" :data="diffItems" size="small" stripe>
              <el-table-column prop="kind" label="类型" width="80" />
              <el-table-column prop="text" label="变更" />
            </el-table>
            <el-empty v-else description="与当前计划无显著差异" />
            <el-collapse style="margin-top: 12px">
              <el-collapse-item title="预览详情" name="detail">
                <pre style="white-space: pre-wrap; font-size: 12px">{{ previewData.preview }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>
          <el-empty v-else description="点击「生成预览」或「周联合调整」" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
