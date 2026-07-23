import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import api, { unwrap } from '@/api/client'

export type ChatMsg = {
  role: 'user' | 'assistant' | 'system'
  content: string
  meta?: any
  elapsedMs?: number
}

export type ProgressStep = {
  event?: string
  stage?: string
  title: string
  detail?: string | null
  tool?: string | null
  status?: string
  at: number
}

export const useChatStore = defineStore('chat', () => {
  const input = ref('减脂期蛋白质怎么安排？')
  const messages = ref<ChatMsg[]>([])
  const events = ref<any[]>([])
  const progressSteps = ref<ProgressStep[]>([])
  const currentStep = ref<ProgressStep | null>(null)
  const pending = ref<any>(null)
  const streaming = ref(false)
  const elapsedMs = ref(0)
  const lastElapsedMs = ref<number | null>(null)
  const lastCitations = ref<any[]>([])
  const lastEvidence = ref<any>(null)

  let timerId: number | null = null
  let startedAt = 0
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

  const elapsedLabel = computed(() => formatMs(elapsedMs.value))
  const lastElapsedLabel = computed(() =>
    lastElapsedMs.value == null ? null : formatMs(lastElapsedMs.value),
  )
  const currentTitle = computed(() => currentStep.value?.title || '准备中')

  function formatMs(ms: number) {
    const total = Math.max(0, Math.floor(ms / 1000))
    const m = Math.floor(total / 60)
    const s = total % 60
    if (m > 0) return `${m}分${String(s).padStart(2, '0')}秒`
    return `${s}秒`
  }

  function startTimer() {
    stopTimer()
    startedAt = performance.now()
    elapsedMs.value = 0
    timerId = window.setInterval(() => {
      elapsedMs.value = performance.now() - startedAt
    }, 200)
  }

  function stopTimer() {
    if (timerId != null) {
      window.clearInterval(timerId)
      timerId = null
    }
    if (startedAt) {
      lastElapsedMs.value = performance.now() - startedAt
      elapsedMs.value = lastElapsedMs.value
    }
  }

  function pushProgress(payload: any) {
    const step: ProgressStep = {
      event: payload.event,
      stage: payload.stage,
      title: payload.title || payload.stage || payload.event || '进度',
      detail: payload.detail,
      tool: payload.tool,
      status: payload.status || 'running',
      at: performance.now() - startedAt,
    }
    progressSteps.value.push(step)
    currentStep.value = step
  }

  async function send() {
    const auth = useAuthStore()
    const text = input.value.trim()
    if (!text || streaming.value) return

    messages.value.push({ role: 'user', content: text })
    input.value = ''
    streaming.value = true
    events.value = []
    progressSteps.value = []
    currentStep.value = null
    pending.value = null
    lastCitations.value = []
    lastEvidence.value = null
    startTimer()
    pushProgress({ event: 'progress', title: '已提交问题', detail: text.slice(0, 80), status: 'done' })

    try {
      const created = unwrap(
        await api.post(
          '/agent/tasks',
          { message: text },
          { headers: { 'Idempotency-Key': `fe-${Date.now()}` } },
        ),
      )
      const taskId = created.task_id
      pushProgress({
        event: 'progress',
        title: '任务已创建',
        detail: `task_id=${taskId}`,
        tool: 'POST /agent/tasks',
        status: 'done',
      })

      const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
      const url = `${base}/agent/tasks/${taskId}/stream`
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (!resp.ok || !resp.body) throw new Error('SSE 连接失败')

      reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          const lines = part.split('\n')
          let event = 'message'
          let data = ''
          for (const line of lines) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            if (line.startsWith('data:')) data += line.slice(5).trim()
          }
          if (!data) continue
          const payload = JSON.parse(data)
          events.value.push({ event, payload })

          if (event === 'progress' || event === 'task_started' || event === 'node_started') {
            pushProgress({
              ...payload,
              event,
              title:
                payload.title ||
                (event === 'node_started'
                  ? `进入节点：${payload.node}${payload.intent_label ? `（${payload.intent_label}）` : ''}`
                  : event),
            })
          }
          if (event === 'approval_required') {
            pending.value = { ...payload, task_id: payload.task_id || taskId }
            pushProgress({
              event,
              title: '等待计划确认',
              detail: '需要人工批准后才会写入正式计划',
              tool: 'request_confirmation',
              status: 'done',
            })
          }
          if (event === 'completed') {
            const assistant = payload.reply || payload.message || JSON.stringify(payload)
            if (payload.citations?.length) {
              lastCitations.value = payload.citations
            } else if (payload.meta?.citations?.length) {
              lastCitations.value = payload.meta.citations
            }
            if (payload.evidence_assessment) {
              lastEvidence.value = payload.evidence_assessment
            }
            if (payload.retrieved_evidence?.length && !lastEvidence.value) {
              lastEvidence.value = { selected_evidence: payload.retrieved_evidence }
            }
            messages.value.push({
              role: 'assistant',
              content: assistant,
              meta: payload,
              elapsedMs: performance.now() - startedAt,
            })
            pushProgress({
              event,
              title: '回答完成',
              detail: payload.final_status || payload.status || 'completed',
              status: 'done',
            })
          }
          if (event === 'failed') {
            messages.value.push({
              role: 'assistant',
              content: `失败：${payload.message || JSON.stringify(payload)}`,
              elapsedMs: performance.now() - startedAt,
            })
            pushProgress({
              event,
              title: '执行失败',
              detail: payload.message || payload.code,
              status: 'error',
            })
          }
        }
      }
    } catch (e: any) {
      ElMessage.error(e?.message || '发送失败')
      messages.value.push({
        role: 'assistant',
        content: `请求异常：${e?.message || e}`,
        elapsedMs: performance.now() - startedAt,
      })
      pushProgress({
        event: 'failed',
        title: '请求异常',
        detail: e?.message || String(e),
        status: 'error',
      })
    } finally {
      stopTimer()
      streaming.value = false
      reader = null
    }
  }

  async function approvePlan(okFlag: boolean) {
    const planId = pending.value?.plan_id || pending.value?.workout_plan_id
    const taskId = pending.value?.task_id
    if (taskId) {
      unwrap(await api.post(`/agent/tasks/${taskId}/approve`, { approve: okFlag }))
    } else if (planId) {
      unwrap(await api.post(`/plans/${planId}/approve`, { approve: okFlag }))
    } else {
      return
    }
    ElMessage.success(okFlag ? '已批准' : '已拒绝')
    pending.value = null
  }

  function clearHistory() {
    if (streaming.value) {
      ElMessage.warning('请等待当前回答完成后再清空')
      return
    }
    messages.value = []
    events.value = []
    progressSteps.value = []
    currentStep.value = null
    pending.value = null
    lastCitations.value = []
    lastEvidence.value = null
    lastElapsedMs.value = null
    elapsedMs.value = 0
  }

  return {
    input,
    messages,
    events,
    progressSteps,
    currentStep,
    currentTitle,
    pending,
    streaming,
    elapsedMs,
    lastElapsedMs,
    elapsedLabel,
    lastElapsedLabel,
    lastCitations,
    lastEvidence,
    send,
    approvePlan,
    clearHistory,
    formatMs,
  }
})
