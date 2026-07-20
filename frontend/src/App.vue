<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isLogin = computed(() => route.name === 'login')

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container style="min-height: 100vh">
    <el-aside v-if="!isLogin" width="220px" style="background: #111827; color: #fff">
      <div style="padding: 20px; font-weight: 700; font-size: 18px">FitPilot</div>
      <el-menu
        :default-active="route.path"
        background-color="#111827"
        text-color="#e5e7eb"
        active-text-color="#60a5fa"
        router
      >
        <el-menu-item index="/">仪表盘</el-menu-item>
        <el-menu-item index="/chat">对话 Agent</el-menu-item>
        <el-menu-item index="/plans">计划</el-menu-item>
        <el-menu-item index="/logs">今日记录</el-menu-item>
        <el-menu-item index="/foods">食物库</el-menu-item>
        <el-menu-item index="/exercises">动作库</el-menu-item>
        <el-menu-item index="/profile">个人档案</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header
        v-if="!isLogin"
        style="display: flex; align-items: center; justify-content: space-between; background: #fff; border-bottom: 1px solid #e5e7eb"
      >
        <div>个性化训练与膳食协同</div>
        <div>
          <span style="margin-right: 12px">{{ auth.email }}</span>
          <el-button size="small" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main style="padding: 0">
        <router-view v-slot="{ Component, route: r }">
          <keep-alive include="ChatView">
            <component :is="Component" :key="r.name" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>
