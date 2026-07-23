<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
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

const pendingDiffLines = computed(() => {
  const d = chat.pending?.diff
  if (!d) return [] as { side: string; text: string }[]
  const lines: { side: string; text: string }[] = []
  const push = (arr: unknown, label: string) => {
    if (!Array.isArray(arr)) return
    for (const x of arr) {
      const text = String(x)
      lines.push({
        side: text.startsWith('+') ? 'add' : text.startsWith('-') ? 'del' : label,
        text,
      })
    }
  }
  if (Array.isArray(d)) {
    push(d, 'chg')
  } else if (typeof d === 'object') {
    push(d.workout || d.training, 'workout')
    push(d.diet || d.nutrition, 'diet')
    for (const [k, v] of Object.entries(d)) {
      if (k === 'workout' || k === 'diet' || k === 'training' || k === 'nutrition') continue
      if (Array.isArray(v)) push(v, k)
      else if (v != null) lines.push({ side: 'chg', text: `${k}: ${JSON.stringify(v)}` })
    }
  }
  return lines
})

const pendingRiskNotes = computed(() => {
  const notes = chat.pending?.risk_notes
  return Array.isArray(notes) ? notes.map(String) : []
})

const pendingLogBasis = computed(() => chat.pending?.data_basis?.logs || null)
const pendingOperation = computed(() => chat.pending?.operation || '将预览计划写入正式版本')
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
              {{ chat.streaming ? 'Agent 执行轨迹（实时）' : '最近一次执行轨迹' }}
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

      <el-collapse v-if="chat.lastCitations?.length || chat.lastEvidence" style="margin-top: 12px">
        <el-collapse-item title="RAG 证据面板" name="evidence">
          <div v-if="chat.lastEvidence" style="margin-bottom: 8px; color: #6b7280; font-size: 13px">
            Evidence Gate：
            answerable={{ chat.lastEvidence.answerable ?? '-' }}；
            confidence={{ chat.lastEvidence.confidence ?? '-' }}；
            coverage={{ chat.lastEvidence.coverage ?? '-' }}；
            reason={{ chat.lastEvidence.reason ?? '-' }}
          </div>
          <el-table
            v-if="chat.lastCitations?.length"
            :data="chat.lastCitations"
            size="small"
            stripe
            style="width: 100%"
          >
            <el-table-column prop="index" label="#" width="48" />
            <el-table-column prop="title" label="标题" min-width="120" />
            <el-table-column prop="section_path" label="章节" min-width="120" />
            <el-table-column prop="citation" label="引用" min-width="160" />
            <el-table-column prop="score" label="相关度" width="90" />
          </el-table>
          <div
            v-for="(ev, i) in chat.lastEvidence?.selected_evidence || []"
            :key="i"
            style="margin-top: 8px; padding: 8px; background: #f9fafb; border-radius: 6px; font-size: 13px"
          >
            <div style="font-weight: 600">{{ ev.title || ev.chunk_id || `证据 ${i + 1}` }}</div>
            <div style="color: #6b7280">{{ ev.section_path || ev.citation }}</div>
            <div style="white-space: pre-wrap; margin-top: 4px">{{ ev.text_preview || '' }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <el-alert
      v-if="chat.pending"
      style="margin-top: 12px"
      type="warning"
      :closable="false"
      :title="pendingOperation"
    >
      <div v-if="chat.pending.weekly_reason" style="margin-bottom: 8px">
        <strong>调整依据：</strong>{{ chat.pending.weekly_reason }}
      </div>
      <div v-if="pendingLogBasis" style="margin-bottom: 8px; font-size: 13px; color: #374151">
        <strong>数据依据：</strong>
        近{{ pendingLogBasis.days || '-' }}天训练
        {{ pendingLogBasis.workout_count ?? '-' }} 次；
        饮食热量 {{ pendingLogBasis.diet_kcal ?? '-' }} kcal
      </div>
      <div v-if="pendingDiffLines.length" style="margin-bottom: 8px">
        <strong>计划 Diff</strong>
        <pre
          v-for="(line, i) in pendingDiffLines"
          :key="i"
          style="margin: 2px 0; white-space: pre-wrap; font-size: 12px"
          :style="{ color: line.side === 'add' ? '#059669' : line.side === 'del' ? '#dc2626' : '#374151' }"
        >{{ line.text }}</pre>
      </div>
      <div v-if="pendingRiskNotes.length" style="margin-bottom: 8px; font-size: 12px; color: #92400e">
        <div v-for="(n, i) in pendingRiskNotes" :key="i">• {{ n }}</div>
      </div>
      <div v-if="chat.pending.can_rollback !== false" style="margin-bottom: 8px; font-size: 12px; color: #6b7280">
        确认后可回滚到上一计划版本。
      </div>
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
