<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { unwrap } from '@/api/client'

const form = reactive<any>({
  display_name: '',
  sex: 'male',
  age: 28,
  height_cm: 175,
  weight_kg: 70,
  goal: 'fat_loss',
  activity_level: 'moderate',
  equipment: '哑铃,杠铃',
  injuries: '',
  diet_prefs: '',
  restrictions: '',
  experience_level: 'intermediate',
  weekly_sessions: 4,
})
const estimate = ref<any>(null)

async function load() {
  const data = unwrap<Record<string, any>>(await api.get('/users/me/profile'))
  Object.assign(form, data)
  estimate.value = data.nutrition_estimate
}

async function save() {
  const data = unwrap<Record<string, any>>(await api.put('/users/me/profile', form))
  estimate.value = data.nutrition_estimate
  ElMessage.success('档案已保存')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>个人档案</h2>
    <el-card>
      <el-form label-width="110px" style="max-width: 640px">
        <el-form-item label="昵称"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.sex"><el-option label="男" value="male" /><el-option label="女" value="female" /></el-select>
        </el-form-item>
        <el-form-item label="年龄"><el-input-number v-model="form.age" :min="10" :max="100" /></el-form-item>
        <el-form-item label="身高 cm"><el-input-number v-model="form.height_cm" :min="100" :max="250" /></el-form-item>
        <el-form-item label="体重 kg"><el-input-number v-model="form.weight_kg" :min="30" :max="300" /></el-form-item>
        <el-form-item label="目标">
          <el-select v-model="form.goal">
            <el-option label="减脂" value="fat_loss" />
            <el-option label="增肌" value="muscle_gain" />
            <el-option label="维持" value="maintain" />
          </el-select>
        </el-form-item>
        <el-form-item label="活动水平">
          <el-select v-model="form.activity_level">
            <el-option label="久坐" value="sedentary" />
            <el-option label="轻度" value="light" />
            <el-option label="中等" value="moderate" />
            <el-option label="活跃" value="active" />
            <el-option label="运动员" value="athlete" />
          </el-select>
        </el-form-item>
        <el-form-item label="器械"><el-input v-model="form.equipment" /></el-form-item>
        <el-form-item label="伤病史"><el-input v-model="form.injuries" type="textarea" /></el-form-item>
        <el-form-item label="饮食偏好"><el-input v-model="form.diet_prefs" /></el-form-item>
        <el-form-item label="忌口/过敏"><el-input v-model="form.restrictions" /></el-form-item>
        <el-form-item label="每周训练"><el-input-number v-model="form.weekly_sessions" :min="0" :max="14" /></el-form-item>
        <el-button type="primary" @click="save">保存</el-button>
      </el-form>
      <el-alert v-if="estimate" style="margin-top: 16px" type="success" :closable="false"
        :title="`BMR ${estimate.bmr} / TDEE ${estimate.tdee}；目标热量 ${estimate.targets?.kcal}，蛋白 ${estimate.targets?.protein_g}g`" />
    </el-card>
  </div>
</template>
