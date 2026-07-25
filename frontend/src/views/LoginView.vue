<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const mode = ref<'login' | 'register'>('login')
const email = ref('demo@fitpilot.local')
const password = ref('demo123456')
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    if (mode.value === 'login') await auth.login(email.value, password.value)
    else await auth.register(email.value, password.value)
    ElMessage.success(mode.value === 'login' ? '登录成功' : '注册成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (e: any) {
    ElMessage.error(e?.message || '认证失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page" style="max-width: 420px; margin: 80px auto">
    <el-card>
      <h2 style="margin-top: 0">FitPilot {{ mode === 'login' ? '登录' : '注册' }}</h2>
      <el-form @submit.prevent="submit">
        <el-form-item label="邮箱">
          <el-input v-model="email" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
          {{ mode === 'login' ? '登录' : '注册' }}
        </el-button>
      </el-form>
      <el-button text style="margin-top: 12px" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? '没有账号？去注册' : '已有账号？去登录' }}
      </el-button>
    </el-card>
  </div>
</template>
