<template>
  <div class="auth-page">
    <!-- 左侧 55% 品牌意境区（ui-design.md §3.1） -->
    <section class="brand-pane">
      <div class="brand-body">
        <h1 class="brand-name">MemWeave <span>忆织</span></h1>
        <p class="brand-sub">编织你的知识与人生经验</p>
        <div class="brand-features">
          <div class="feature">
            <div class="feature-icon">▣</div>
            <div class="feature-text">
              <b>多源沉淀</b>
              <p>文字、文档、图片，一键存入</p>
            </div>
          </div>
          <div class="feature">
            <div class="feature-icon">⌘</div>
            <div class="feature-text">
              <b>结构编织</b>
              <p>知识卡片与思维导图自动生成</p>
            </div>
          </div>
          <div class="feature">
            <div class="feature-icon">◎</div>
            <div class="feature-text">
              <b>抗遗忘回顾</b>
              <p>遗忘曲线驱动，温故知新</p>
            </div>
          </div>
        </div>
        <p class="brand-slogan">沉淀此刻，编织未来的自己</p>
      </div>
    </section>

    <!-- 右侧 45% 表单区（ui-design.md §3.1） -->
    <section class="form-pane">
      <div class="form-box">
        <div class="tab-switch">
          <span :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</span>
          <span :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</span>
        </div>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large">
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="form.email" placeholder="输入邮箱" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="8~32位，须同时包含字母与数字"
            />
          </el-form-item>
          <el-button
            type="primary"
            class="submit-btn"
            :loading="loading"
            @click="handleSubmit"
          >
            {{ mode === 'login' ? '登录' : '注册' }}
          </el-button>
        </el-form>
        <div class="demo-entry" @click="goDemo">体验演示账号 →</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import request from '@/api/request'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ initialMode?: 'login' | 'register' }>()

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>(
  props.initialMode || ((route.query.mode as 'login' | 'register') || 'login'),
)
const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

const rules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    {
      pattern: /^(?=.*[A-Za-z])(?=.*\d)\S{8,32}$/,
      message: '8~32位，须同时包含字母与数字',
      trigger: 'blur',
    },
  ],
}

function switchMode(m: 'login' | 'register') {
  mode.value = m
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const data: any =
      mode.value === 'login'
        ? await request.post('/auth/login', { email: form.email, password: form.password })
        : await request.post('/auth/register', { email: form.email, password: form.password })
    auth.setSession(data.token, { id: data.user?.id, email: data.user?.email })
    ElMessage.success(mode.value === 'login' ? '欢迎回来' : '注册成功')
    const redirect = (route.query.redirect as string) || '/workbench'
    router.push(redirect)
  } finally {
    loading.value = false
  }
}

function goDemo() {
  // 演示账号体验：使用预置账号直接登录（账号信息由后端预置，见任务9.1）
  mode.value = 'login'
  form.email = 'demo@memweave.cn'
  form.password = 'MemWeave2026'
  ElMessage.info('已填入演示账号，点击登录即可体验')
}
</script>

<style scoped>
.auth-page {
  display: flex;
  height: 100vh;
  min-width: 1280px;
}
.brand-pane {
  width: 55%;
  background: var(--mw-bg-page);
  border-right: 1px solid var(--mw-border);
  display: flex;
  align-items: center;
  justify-content: center;
}
.brand-body {
  max-width: 480px;
  padding: 0 48px;
}
.brand-name {
  font-size: 40px;
  font-weight: 700;
  margin: 0;
  letter-spacing: 1px;
}
.brand-name span {
  margin-left: 12px;
  font-size: 26px;
  color: var(--mw-text-secondary);
  font-weight: 500;
}
.brand-sub {
  margin: 14px 0 48px;
  font-size: 16px;
  color: var(--mw-text-secondary);
  letter-spacing: 2px;
}
.brand-features {
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.feature {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.feature-icon {
  width: 40px;
  height: 40px;
  border: 1px solid var(--mw-border);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  background: var(--mw-bg-card);
}
.feature-text b {
  font-size: 14px;
}
.feature-text p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--mw-text-tertiary);
}
.brand-slogan {
  margin-top: 56px;
  font-size: 13px;
  color: var(--mw-text-tertiary);
  letter-spacing: 3px;
}
.form-pane {
  width: 45%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--mw-bg-card);
}
.form-box {
  width: 340px;
}
.tab-switch {
  display: flex;
  gap: 24px;
  margin-bottom: 28px;
}
.tab-switch span {
  font-size: 18px;
  font-weight: 600;
  color: var(--mw-text-tertiary);
  cursor: pointer;
  padding-bottom: 6px;
}
.tab-switch span.active {
  color: var(--mw-text-primary);
  border-bottom: 2px solid var(--mw-text-primary);
}
.submit-btn {
  width: 100%;
  margin-top: 8px;
}
.demo-entry {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
  color: var(--mw-text-tertiary);
  cursor: pointer;
}
.demo-entry:hover {
  color: var(--mw-text-primary);
}
</style>