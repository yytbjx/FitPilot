<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { unwrap } from '@/api/client'

const today = new Date().toISOString().slice(0, 10)
const workoutForm = reactive({ log_date: today, exercise: '深蹲', sets: 3, reps: 8, weight_kg: 60, notes: '' })
const dietForm = reactive({ log_date: today, food_item_id: undefined as number | undefined, amount_g: 150, meal: 'lunch', notes: '' })
const bodyForm = reactive({ log_date: today, weight_kg: 70, body_fat_pct: undefined as number | undefined, notes: '' })
const foods = ref<any[]>([])
const workouts = ref<any[]>([])
const diets = ref<any[]>([])
const bodies = ref<any[]>([])

async function refresh() {
  foods.value = unwrap<{ items?: any[] }>(await api.get('/foods')).items || []
  workouts.value =
    unwrap<{ items?: any[] }>(await api.get('/workouts/logs', { params: { log_date: today } }))
      .items || []
  diets.value =
    unwrap<{ items?: any[] }>(await api.get('/diet/logs', { params: { log_date: today } })).items ||
    []
  bodies.value = unwrap<{ items?: any[] }>(await api.get('/body-metrics')).items || []
}

async function addWorkout() {
  await api.post('/workouts/logs', workoutForm)
  ElMessage.success('训练记录已添加')
  refresh()
}
async function addDiet() {
  await api.post('/diet/logs', dietForm)
  ElMessage.success('饮食记录已添加')
  refresh()
}
async function addBody() {
  await api.post('/body-metrics', bodyForm)
  ElMessage.success('体测已添加')
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <h2>今日记录</h2>
    <div class="card-grid">
      <el-card>
        <template #header>训练</template>
        <el-form label-width="80px">
          <el-form-item label="动作"><el-input v-model="workoutForm.exercise" /></el-form-item>
          <el-form-item label="组数"><el-input-number v-model="workoutForm.sets" /></el-form-item>
          <el-form-item label="次数"><el-input-number v-model="workoutForm.reps" /></el-form-item>
          <el-form-item label="重量"><el-input-number v-model="workoutForm.weight_kg" /></el-form-item>
          <el-button type="primary" @click="addWorkout">添加</el-button>
        </el-form>
        <el-table :data="workouts" size="small" style="margin-top: 12px">
          <el-table-column prop="exercise" label="动作" />
          <el-table-column prop="sets" label="组" width="60" />
          <el-table-column prop="reps" label="次" width="60" />
          <el-table-column prop="weight_kg" label="kg" width="70" />
        </el-table>
      </el-card>
      <el-card>
        <template #header>饮食</template>
        <el-form label-width="80px">
          <el-form-item label="食物">
            <el-select v-model="dietForm.food_item_id" filterable style="width: 100%">
              <el-option v-for="f in foods" :key="f.id" :label="f.name" :value="f.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="克数"><el-input-number v-model="dietForm.amount_g" /></el-form-item>
          <el-form-item label="餐次"><el-input v-model="dietForm.meal" /></el-form-item>
          <el-button type="primary" @click="addDiet">添加</el-button>
        </el-form>
        <el-table :data="diets" size="small" style="margin-top: 12px">
          <el-table-column prop="food_name" label="食物" />
          <el-table-column prop="amount_g" label="g" width="70" />
          <el-table-column prop="kcal" label="kcal" width="80" />
          <el-table-column prop="protein_g" label="蛋白" width="70" />
        </el-table>
      </el-card>
      <el-card>
        <template #header>体测</template>
        <el-form label-width="80px">
          <el-form-item label="体重"><el-input-number v-model="bodyForm.weight_kg" /></el-form-item>
          <el-form-item label="体脂%"><el-input-number v-model="bodyForm.body_fat_pct" /></el-form-item>
          <el-button type="primary" @click="addBody">添加</el-button>
        </el-form>
        <el-table :data="bodies" size="small" style="margin-top: 12px">
          <el-table-column prop="log_date" label="日期" />
          <el-table-column prop="weight_kg" label="kg" />
          <el-table-column prop="body_fat_pct" label="体脂%" />
        </el-table>
      </el-card>
    </div>
  </div>
</template>
