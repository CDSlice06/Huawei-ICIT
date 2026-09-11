<template>
  <!-- 薄壳：注册页复用登录页组件（tab 切换至注册，ui-design.md §3.1） -->
  <LoginPage initial-mode="register" />
</template>

<script setup lang="ts">
import LoginPage from './LoginPage.vue'
</script>