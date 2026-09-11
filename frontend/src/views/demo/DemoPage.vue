<template>
  <div class="demo-page">
    <header class="demo-header">
      <span class="logo">MemWeave <i>忆织</i></span>
      <div>
        <el-button text @click="router.push('/login')">登录</el-button>
        <el-button type="primary" @click="router.push('/register')">开始使用</el-button>
      </div>
    </header>

    <section class="hero">
      <h1>编织你的知识与人生经验</h1>
      <p>
        把你看过的书、领悟到的道理、现实生活中的亲身体悟，一键沉淀为独属于你自己的结构化知识图库。
        多源沉淀 · 结构编织 · 抗遗忘回顾。
      </p>
      <el-button type="primary" size="large" @click="router.push('/login?mode=register')">
        立即开始
      </el-button>
    </section>

    <section class="features">
      <div class="feature mw-card">
        <h3>多源沉淀</h3>
        <p>文字、文档、图片随手导入，AI 自动提取为「标题-摘要-要点-问答-标签」结构化卡片。</p>
      </div>
      <div class="feature mw-card">
        <h3>结构编织</h3>
        <p>基于知识卡片一键生成思维导图，知识体系一目了然；自定义编排你自己的理解。</p>
      </div>
      <div class="feature mw-card">
        <h3>抗遗忘回顾</h3>
        <p>遗忘曲线驱动回顾计划，先自测再揭示，让学过悟过的东西不再随时间流逝而消失。</p>
      </div>
    </section>

    <footer class="demo-footer">
      第十一届华为ICT大赛创新赛 · 赛道一参赛作品 · 开源于
      <a href="https://github.com/CDSlice06/Huawei-ICIT" target="_blank" rel="noopener">GitHub</a>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.demo-page {
  min-height: 100vh;
  max-width: 1080px;
  margin: 0 auto;
  padding: 20px 32px;
}
.demo-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 80px;
}
.logo {
  font-size: 20px;
  font-weight: 700;
}
.logo i {
  font-style: normal;
  margin-left: 8px;
  font-size: 15px;
  color: var(--mw-text-tertiary);
}
.hero {
  text-align: center;
  padding: 40px 0 64px;
}
.hero h1 {
  font-size: 40px;
  margin: 0 0 18px;
  letter-spacing: 1px;
}
.hero p {
  max-width: 640px;
  margin: 0 auto 32px;
  color: var(--mw-text-secondary);
  line-height: 1.9;
}
.features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 80px;
}
.feature {
  padding: 28px;
}
.feature h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
.feature p {
  margin: 0;
  font-size: 13px;
  color: var(--mw-text-secondary);
  line-height: 1.8;
}
.demo-footer {
  text-align: center;
  padding: 24px 0;
  color: var(--mw-text-tertiary);
  font-size: 13px;
}
</style>