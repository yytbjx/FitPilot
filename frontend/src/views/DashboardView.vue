<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import api, { unwrap } from '@/api/client'

const profile = ref<any>(null)
const plans = ref<any>(null)

const goalLabel = computed(() => {
  const map: Record<string, string> = {
    fat_loss: '减脂',
    muscle_gain: '增肌',
    maintain: '维持',
  }
  return map[profile.value?.goal] || profile.value?.goal || '未设置'
})

const activityLabel = computed(() => {
  const map: Record<string, string> = {
    sedentary: '久坐',
    light: '轻度',
    moderate: '中等',
    active: '活跃',
    athlete: '运动员',
  }
  return map[profile.value?.activity_level] || profile.value?.activity_level || '-'
})

onMounted(async () => {
  try {
    profile.value = unwrap(await api.get('/users/me/profile'))
    plans.value = unwrap(await api.get('/plans/current'))
  } catch {
    /* ignore */
  }
})
</script>

<template>
  <div class="page">
    <h2>仪表盘</h2>
    <div class="card-grid">
      <el-card>
        <template #header>档案摘要</template>
        <div v-if="profile">
          <p>昵称：{{ profile.display_name || '-' }}</p>
          <p>目标：{{ goalLabel }}</p>
          <p>活动水平：{{ activityLabel }}</p>
          <p>身高 / 体重：{{ profile.height_cm || '-' }} cm / {{ profile.weight_kg || '-' }} kg</p>
          <p v-if="profile.nutrition_estimate">
            BMR {{ profile.nutrition_estimate.bmr }} kcal　
            TDEE {{ profile.nutrition_estimate.tdee }} kcal
          </p>
          <p v-if="profile.nutrition_estimate?.targets">
            目标热量 {{ profile.nutrition_estimate.targets.kcal }} kcal　
            蛋白 {{ profile.nutrition_estimate.targets.protein_g }} g　
            碳水 {{ profile.nutrition_estimate.targets.carb_g }} g　
            脂肪 {{ profile.nutrition_estimate.targets.fat_g }} g
          </p>
        </div>
        <el-empty v-else description="暂无档案" />
      </el-card>

      <el-card>
        <template #header>当前计划</template>
        <div v-if="plans?.workout || plans?.diet">
          <p>
            训练：{{ plans?.workout?.title || '无' }}
            <el-tag size="small" style="margin-left: 6px">v{{ plans?.workout?.current_version || 0 }}</el-tag>
          </p>
          <p>
            饮食：{{ plans?.diet?.title || '无' }}
            <el-tag size="small" style="margin-left: 6px">v{{ plans?.diet?.current_version || 0 }}</el-tag>
          </p>
        </div>
        <el-empty v-else description="暂无已批准计划，可在「计划 / 对话」中生成" />
      </el-card>
    </div>
  </div>
</template>
