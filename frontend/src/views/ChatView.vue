<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'

defineOptions({ name: 'ChatView' })

const chat = useChatStore()
const listRef = ref<HTMLElement | null>(null)

async function scrollBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

watch(
  () => [chat.messages.length, chat.progressSteps.length, chat.streaming],
  () => {
    scrollBottom()
  },
)

function statusType(status?: string) {
  if (status === 'done') return 'success'
  if (status === 'error') return 'danger'
  return 'warning'
}
</script>

<template>
  <div class="page" style="display: flex; flex-direction: column; height: calc(100vh - 80px)">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
      <h2 style="margin: 0">对话 Agent</h2>
      <div style="display: flex; align-items: center; gap: 8px">
        <el-tag v-if="chat.streaming" type="warning">
          {{ chat.currentTitle }} · {{ chat.elapsedLabel }}
        </el-tag>
        <el-tag v-else-if="chat.lastElapsedLabel" type="info">
          上次用时 {{ chat.lastElapsedLabel }}
        </el-tag>
        <el-button size="small" @click="chat.clearHistory()">清空对话</el-button>
      </div>
    </div>

    <div
      ref="listRef"
      style="flex: 1; overflow: auto; background: #fff; border-radius: 8px; padding: 16px; margin-top: 12px"
    >
      <el-empty v-if="!chat.messages.length && !chat.streaming" description="开始提问吧（切换页面不会中断进行中的回答）" />
      <div v-for="(m, i) in chat.messages" :key="i" style="margin-bottom: 12px">
        <div style="display: flex; align-items: center; gap: 8px">
          <el-tag size="small" :type="m.role === 'user' ? 'primary' : 'success'">
            {{ m.role === 'user' ? '我' : 'FitPilot' }}
          </el-tag>
          <span v-if="m.elapsedMs != null" style="color: #6b7280; font-size: 12px">
            耗时 {{ chat.formatMs(m.elapsedMs) }}
          </span>
        </div>
        <div style="white-space: pre-wrap; margin-top: 6px">{{ m.content }}</div>
        <div v-if="m.meta?.citations?.length" style="margin-top: 6px; color: #6b7280; font-size: 12px">
          引用：
          <span v-for="c in m.meta.citations" :key="c.index">[{{ c.index }}] {{ c.citation }}；</span>
        </div>
      </div>

      <el-card v-if="chat.streaming || chat.progressSteps.length" shadow="never" style="margin-top: 8px; background: #fffbeb">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>
              {{ chat.streaming ? '执行链路（实时）' : '最近一次链路' }}
            </span>
            <el-tag size="small" type="warning" v-if="chat.streaming">用时 {{ chat.elapsedLabel }}</el-tag>
          </div>
        </template>
        <el-timeline style="padding-left: 4px; max-height: 280px; overflow: auto">
          <el-timeline-item
            v-for="(step, idx) in chat.progressSteps"
            :key="idx"
            :type="statusType(step.status)"
            :timestamp="chat.formatMs(step.at)"
            placement="top"
          >
            <div style="font-weight: 600">{{ step.title }}</div>
            <div v-if="step.tool" style="color: #6b7280; font-size: 12px; margin-top: 2px">
              工具 / 组件：{{ step.tool }}
            </div>
            <div v-if="step.detail" style="color: #374151; font-size: 13px; margin-top: 2px; white-space: pre-wrap">
              {{ step.detail }}
            </div>
          </el-timeline-item>
        </el-timeline>
        <div v-if="chat.streaming" style="color: #d97706; font-size: 13px; margin-top: 8px">
          当前环节：{{ chat.currentTitle }}…
        </div>
      </el-card>
    </div>

    <el-alert
      v-if="chat.pending"
      style="margin-top: 12px"
      type="warning"
      :closable="false"
      title="需要确认计划写入"
    >
      <pre style="white-space: pre-wrap">{{ chat.pending }}</pre>
      <el-button type="primary" size="small" @click="chat.approvePlan(true)">批准</el-button>
      <el-button size="small" @click="chat.approvePlan(false)">拒绝</el-button>
    </el-alert>

    <div style="display: flex; gap: 8px; margin-top: 12px">
      <el-input
        v-model="chat.input"
        type="textarea"
        :rows="2"
        placeholder="输入问题，Ctrl+Enter 发送；切到其他页面不会中断"
        @keydown.ctrl.enter="chat.send()"
      />
      <el-button type="primary" :loading="chat.streaming" @click="chat.send()">
        {{ chat.streaming ? `${chat.currentTitle} ${chat.elapsedLabel}` : '发送' }}
      </el-button>
    </div>
  </div>
</template>
