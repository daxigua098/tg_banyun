<template>
  <div v-if="!authenticated" class="login-shell">
    <el-card class="login-card">
      <h1>TG-Mirror-Bot 管理后台</h1>
      <p>请输入管理员用户名和密码</p>
      <el-input v-model="loginForm.username" placeholder="管理员用户名" @keyup.enter="login" />
      <el-input v-model="loginForm.password" type="password" show-password placeholder="管理员密码" class="login-input" @keyup.enter="login" />
      <el-button type="primary" class="login-button" @click="login">登录</el-button>
    </el-card>
  </div>

  <el-container v-else class="app-shell">
    <el-aside width="220px" class="sidebar">
      <div class="brand">
        <div class="brand-title">TG-Mirror-Bot</div>
        <div class="brand-subtitle">中文管理后台</div>
      </div>
      <el-menu :default-active="activePage" class="menu" @select="selectPage">
        <el-menu-item index="dashboard">运行总览</el-menu-item>
        <el-menu-item index="sources">搬运源</el-menu-item>
        <el-menu-item index="targets">接收目标</el-menu-item>
        <el-menu-item index="routes">路由关系</el-menu-item>
        <el-menu-item index="rules">过滤规则</el-menu-item>
        <el-menu-item index="jobs">投递任务</el-menu-item>
        <el-menu-item index="commands">控制命令</el-menu-item>
        <el-menu-item index="audit">操作日志</el-menu-item>
        <el-menu-item index="login_history">登录历史</el-menu-item>
        <el-menu-item v-if="userRole === 'super_admin'" index="users">用户管理</el-menu-item>
        <el-menu-item index="account">账号安全</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <div class="page-title">{{ pageTitle }}</div>
          <div class="page-subtitle">最后刷新：{{ lastRefresh || '-' }}</div>
        </div>
        <div class="actions">
          <el-button @click="refreshAll">刷新</el-button>
          <el-button type="warning" :disabled="status?.paused" @click="pause">暂停</el-button>
          <el-button type="success" :disabled="!status?.paused" @click="resume">恢复</el-button>
          <el-button type="danger" plain @click="retry">重试失败</el-button>
          <el-button plain @click="logout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="content" v-loading="loading">
        <section v-if="activePage === 'dashboard'">
          <div class="stat-grid">
            <el-card><div class="stat-label">运行状态</div><div class="stat-value">{{ runtimeText }}</div></el-card>
            <el-card><div class="stat-label">搬运状态</div><div class="stat-value">{{ status?.paused ? '已暂停' : '运行中' }}</div></el-card>
            <el-card><div class="stat-label">源 / 目标</div><div class="stat-value">{{ status?.source_count || 0 }} / {{ status?.target_count || 0 }}</div></el-card>
            <el-card><div class="stat-label">路由</div><div class="stat-value">{{ status?.route_count || 0 }}</div></el-card>
          </div>
          <el-card class="chart-card">
            <template #header>投递任务统计</template>
            <div ref="chartElement" class="chart"></div>
          </el-card>
        </section>

        <el-card v-else-if="activePage === 'sources'">
          <el-table :data="sources" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="title" label="名称" min-width="180" />
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" @change="changeSourceEnabled(row)" />
              </template>
            </el-table-column>
            <el-table-column prop="sync_status" label="同步状态" width="110" />
            <el-table-column prop="last_synced_message_id" label="最新消息 ID" width="150" />
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'targets'">
          <el-table :data="targets" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="title" label="名称" min-width="180" />
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" @change="changeTargetEnabled(row)" />
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'routes'">
          <div class="filters">
            <el-select v-model="newRoute.source_id" placeholder="选择源" style="width: 180px">
              <el-option v-for="source in sources" :key="source.id" :label="`${source.id} - ${source.title}`" :value="source.id" />
            </el-select>
            <el-select v-model="newRoute.target_id" placeholder="选择目标" style="width: 180px">
              <el-option v-for="target in targets" :key="target.id" :label="`${target.id} - ${target.title}`" :value="target.id" />
            </el-select>
            <el-button type="primary" @click="addRoute">建立路由</el-button>
          </div>
          <el-table :data="routes" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="source_id" label="源 ID" width="100" />
            <el-table-column prop="target_id" label="目标 ID" width="100" />
            <el-table-column prop="enabled" label="状态" width="100" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button type="danger" link @click="removeRoute(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'rules'">
          <el-table :data="rules" stripe>
            <el-table-column prop="source_id" label="源 ID" width="80" />
            <el-table-column prop="source_title" label="源名称" min-width="160" />
            <el-table-column label="图片" width="70"><template #default="{ row }">{{ row.allow_photo ? '开' : '关' }}</template></el-table-column>
            <el-table-column label="视频" width="70"><template #default="{ row }">{{ row.allow_video ? '开' : '关' }}</template></el-table-column>
            <el-table-column label="仅频道" width="80"><template #default="{ row }">{{ row.post_only ? '是' : '否' }}</template></el-table-column>
            <el-table-column label="仅管理" width="80"><template #default="{ row }">{{ row.admin_only ? '是' : '否' }}</template></el-table-column>
            <el-table-column label="关键词白名单" min-width="180"><template #default="{ row }">{{ row.keyword_whitelist.join('、') || '-' }}</template></el-table-column>
            <el-table-column label="指定账号" min-width="180"><template #default="{ row }">{{ row.sender_whitelist.join('、') || '-' }}</template></el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }"><el-button type="primary" link @click="openRule(row)">编辑</el-button></template>
            </el-table-column>
          </el-table>
        </el-card>

        <section v-else-if="activePage === 'account'">
          <el-card class="command-card">
            <template #header>修改密码</template>
            <el-form label-width="120px">
              <el-form-item label="当前密码"><el-input v-model="passwordForm.current" type="password" show-password /></el-form-item>
              <el-form-item label="新密码"><el-input v-model="passwordForm.next" type="password" show-password /></el-form-item>
              <el-form-item label="确认新密码"><el-input v-model="passwordForm.confirm" type="password" show-password /></el-form-item>
              <el-form-item><el-button type="primary" @click="changePasswordAction">保存密码</el-button></el-form-item>
            </el-form>
          </el-card>
          <el-card>
            <template #header>会话安全</template>
            <p>强制退出当前账号在其他设备上的全部会话。</p>
            <el-button type="danger" plain @click="logoutAllAction">全部设备下线</el-button>
          </el-card>
        </section>

        <el-card v-else-if="activePage === 'users'">
          <div class="filters"><el-button type="primary" @click="userDialog = true">新增用户</el-button></div>
          <el-table :data="webUsers" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="username" label="用户名" min-width="160" />
            <el-table-column label="角色" width="160">
              <template #default="{ row }">
                <el-select v-model="row.role" @change="changeUserRole(row)">
                  <el-option label="超级管理员" value="super_admin" />
                  <el-option label="操作员" value="operator" />
                  <el-option label="只读用户" value="viewer" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-switch v-model="row.enabled" @change="changeUserEnabled(row)" /></template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'login_history'">
          <template #header>最近登录记录</template>
          <el-table :data="loginHistory" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="username" label="用户名" width="160" />
            <el-table-column label="结果" width="100">
              <template #default="{ row }"><el-tag :type="row.success ? 'success' : 'danger'">{{ row.success ? '成功' : '失败' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="ip_address" label="IP" width="150" />
            <el-table-column prop="reason" label="原因" min-width="140" />
            <el-table-column prop="user_agent" label="客户端" min-width="240" show-overflow-tooltip />
            <el-table-column prop="created_at" label="时间" min-width="180" />
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'audit'">
          <template #header>最近操作日志</template>
          <el-table :data="auditLogs" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="username" label="用户" width="140" />
            <el-table-column prop="method" label="方法" width="90" />
            <el-table-column prop="path" label="接口" min-width="240" />
            <el-table-column prop="status_code" label="状态码" width="90" />
            <el-table-column prop="ip_address" label="IP" width="140" />
            <el-table-column prop="created_at" label="时间" min-width="180" />
          </el-table>
        </el-card>

        <section v-else-if="activePage === 'commands'">
          <el-card class="command-card">
            <template #header>添加搬运源</template>
            <div class="command-row">
              <el-input v-model="commandForm.source" placeholder="频道链接、@用户名或私有邀请链接" />
              <el-checkbox v-model="commandForm.join">允许加入</el-checkbox>
              <el-button type="primary" @click="queueAddSource">提交</el-button>
            </div>
          </el-card>
          <el-card class="command-card">
            <template #header>添加接收目标</template>
            <div class="command-row">
              <el-input v-model="commandForm.target" placeholder="Telegram 频道或群组链接" />
              <el-button type="primary" @click="queueAddTarget">提交</el-button>
            </div>
          </el-card>
          <el-card class="command-card">
            <template #header>同步历史消息</template>
            <div class="command-row">
              <el-select v-model="commandForm.syncSource" placeholder="选择源或全部" style="width: 220px">
                <el-option label="全部源" value="all" />
                <el-option v-for="source in sources" :key="source.id" :label="`${source.id} - ${source.title}`" :value="source.id" />
              </el-select>
              <el-input-number v-model="commandForm.syncLimit" :min="1" :max="5000" />
              <el-button type="primary" @click="queueSync">提交</el-button>
            </div>
          </el-card>
          <el-card>
            <template #header>最近控制命令</template>
            <el-table :data="commands" stripe>
              <el-table-column prop="id" label="ID" width="80" />
              <el-table-column prop="command_type" label="命令" width="140" />
              <el-table-column prop="status" label="状态" width="110" />
              <el-table-column prop="result" label="结果" min-width="220" show-overflow-tooltip />
              <el-table-column prop="error" label="错误" min-width="220" show-overflow-tooltip />
              <el-table-column prop="created_at" label="创建时间" min-width="180" />
            </el-table>
          </el-card>
        </section>

        <el-card v-else-if="activePage === 'jobs'">
          <div class="filters">
            <el-select v-model="jobStatus" placeholder="全部状态" clearable style="width: 180px" @change="loadJobs">
              <el-option label="等待" value="pending" />
              <el-option label="处理中" value="processing" />
              <el-option label="重试中" value="retrying" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="已跳过" value="skipped" />
            </el-select>
            <el-button @click="loadJobs">查询</el-button>
          </div>
          <el-table :data="jobs" stripe>
            <el-table-column prop="id" label="任务 ID" width="90" />
            <el-table-column prop="source_id" label="源 ID" width="80" />
            <el-table-column prop="source_message_id" label="源消息" width="110" />
            <el-table-column prop="target_id" label="目标 ID" width="90" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="attempt_count" label="尝试" width="70" />
            <el-table-column prop="last_error" label="错误" min-width="240" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-main>
    </el-container>

    <el-dialog v-model="ruleDialog" title="编辑过滤规则" width="620px">
      <el-form label-width="120px">
        <el-form-item label="图片"><el-switch v-model="ruleForm.allow_photo" /></el-form-item>
        <el-form-item label="视频"><el-switch v-model="ruleForm.allow_video" /></el-form-item>
        <el-form-item label="仅频道帖子"><el-switch v-model="ruleForm.post_only" /></el-form-item>
        <el-form-item label="仅管理员"><el-switch v-model="ruleForm.admin_only" /></el-form-item>
        <el-form-item label="跳过转发"><el-switch v-model="ruleForm.skip_forwarded" /></el-form-item>
        <el-form-item label="关键词白名单"><el-input v-model="ruleForm.keyword_whitelist_text" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="关键词黑名单"><el-input v-model="ruleForm.keyword_blacklist_text" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="指定账号"><el-input v-model="ruleForm.sender_whitelist_text" placeholder="数字 ID，逗号分隔" /></el-form-item>
        <el-form-item label="排除账号"><el-input v-model="ruleForm.sender_blacklist_text" placeholder="数字 ID，逗号分隔" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userDialog" title="新增用户" width="480px">
      <el-form label-width="90px">
        <el-form-item label="用户名"><el-input v-model="userForm.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="userForm.password" type="password" show-password /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role">
            <el-option label="超级管理员" value="super_admin" />
            <el-option label="操作员" value="operator" />
            <el-option label="只读用户" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import {
  changePassword,
  checkAuth,
  createRoute,
  login as loginRequest,
  logoutAllSessions,
  logoutSession,
  deleteRoute,
  enqueueAddSource,
  enqueueAddTarget,
  enqueueSync,
  createUser,
  getControlCommands,
  getLoginHistory,
  getUsers,
  getJobs,
  getRoutes,
  getRules,
  getSources,
  getStatus,
  getTargets,
  pauseRuntime,
  resumeRuntime,
  retryFailed,
  setSourceEnabled,
  setTargetEnabled,
  updateUser,
  updateRule,
} from './api'

const authenticated = ref(Boolean(localStorage.getItem('admin_api_token')))
const tokenInput = ref('')
const activePage = ref('dashboard')
const status = ref(null)
const sources = ref([])
const targets = ref([])
const routes = ref([])
const rules = ref([])
const jobs = ref([])
const jobStatus = ref('')
const loading = ref(false)
const lastRefresh = ref('')
const chartElement = ref(null)
const newRoute = ref({ source_id: null, target_id: null })
const commands = ref([])
const auditLogs = ref([])
const loginHistory = ref([])
const webUsers = ref([])
const userDialog = ref(false)
const userForm = ref({ username: '', password: '', role: 'viewer' })
const passwordForm = ref({ current: '', next: '', confirm: '' })
const commandForm = ref({ source: '', target: '', join: false, syncSource: 'all', syncLimit: 100 })
const ruleDialog = ref(false)
const ruleForm = ref({})
let chart = null

const pageTitles = {
  dashboard: '运行总览',
  sources: '搬运源',
  targets: '接收目标',
  routes: '路由关系',
  rules: '过滤规则',
  jobs: '投递任务',
}
const pageTitle = computed(() => pageTitles[activePage.value] || '管理后台')
const runtimeText = computed(() => status.value?.runtime === 'running' ? '运行中' : status.value?.runtime || '未知')

function renderChart() {
  if (!chartElement.value || activePage.value !== 'dashboard') return
  chart = chart || echarts.init(chartElement.value)
  const counts = status.value?.jobs || {}
  chart.setOption({
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['42%', '70%'],
      data: Object.entries(counts).map(([name, value]) => ({ name, value })),
    }],
  })
  chart.resize()
}

async function refreshAll() {
  loading.value = true
  try {
    const [statusData, sourceData, targetData, routeData, ruleData, commandData] = await Promise.all([
      getStatus(), getSources(), getTargets(), getRoutes(), getRules(), getControlCommands(),
    ])
    status.value = statusData
    sources.value = sourceData
    targets.value = targetData
    routes.value = routeData
    rules.value = ruleData
    commands.value = commandData
    auditLogs.value = authenticated.value ? await getAuditLogs() : []
    loginHistory.value = authenticated.value ? await getLoginHistory() : []
    webUsers.value = authenticated.value && userRole.value === 'super_admin' ? await getUsers() : []
    await loadJobs()
    lastRefresh.value = new Date().toLocaleString()
    await nextTick()
    renderChart()
  } catch (error) {
    if (error.response?.status === 401) {
      logout(false)
      ElMessage.error('管理令牌无效，请重新登录')
    } else {
      ElMessage.error(error.response?.data?.detail || error.message || '加载失败')
    }
  } finally {
    loading.value = false
  }
}

async function loadJobs() {
  jobs.value = await getJobs(jobStatus.value)
}

async function pause() {
  await pauseRuntime()
  ElMessage.success('已暂停搬运')
  await refreshAll()
}

async function resume() {
  await resumeRuntime()
  ElMessage.success('已恢复搬运')
  await refreshAll()
}

async function retry() {
  const result = await retryFailed()
  ElMessage.success(`已重新加入 ${result.retried} 个失败任务`)
  await refreshAll()
}

async function changeSourceEnabled(row) {
  await setSourceEnabled(row.id, row.enabled)
  ElMessage.success('源状态已更新')
}

async function changeTargetEnabled(row) {
  await setTargetEnabled(row.id, row.enabled)
  ElMessage.success('目标状态已更新')
}

async function addRoute() {
  if (!newRoute.value.source_id || !newRoute.value.target_id) {
    ElMessage.warning('请选择源和目标')
    return
  }
  await createRoute(newRoute.value.source_id, newRoute.value.target_id)
  ElMessage.success('路由已建立')
  await refreshAll()
}

async function removeRoute(row) {
  await deleteRoute(row.id)
  ElMessage.success('路由已删除')
  await refreshAll()
}

function openRule(row) {
  ruleForm.value = {
    source_id: row.source_id,
    allow_photo: row.allow_photo,
    allow_video: row.allow_video,
    post_only: row.post_only,
    admin_only: row.admin_only,
    skip_forwarded: row.skip_forwarded,
    keyword_whitelist_text: row.keyword_whitelist.join(','),
    keyword_blacklist_text: row.keyword_blacklist.join(','),
    sender_whitelist_text: row.sender_whitelist.join(','),
    sender_blacklist_text: row.sender_blacklist.join(','),
  }
  ruleDialog.value = true
}

function parseTextList(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

function parseIdList(value) {
  return parseTextList(value).map(Number).filter((item) => Number.isInteger(item))
}

async function saveRule() {
  const form = ruleForm.value
  await updateRule(form.source_id, {
    allow_photo: form.allow_photo,
    allow_video: form.allow_video,
    post_only: form.post_only,
    admin_only: form.admin_only,
    skip_forwarded: form.skip_forwarded,
    keyword_whitelist: parseTextList(form.keyword_whitelist_text),
    keyword_blacklist: parseTextList(form.keyword_blacklist_text),
    sender_whitelist: parseIdList(form.sender_whitelist_text),
    sender_blacklist: parseIdList(form.sender_blacklist_text),
  })
  ruleDialog.value = false
  ElMessage.success('过滤规则已保存')
  await refreshAll()
}

async function queueAddSource() {
  if (!commandForm.value.source) return ElMessage.warning('请输入源链接')
  await enqueueAddSource(commandForm.value.source, commandForm.value.join)
  ElMessage.success('添加源命令已进入队列')
  commandForm.value.source = ''
  await refreshAll()
}

async function queueAddTarget() {
  if (!commandForm.value.target) return ElMessage.warning('请输入目标链接')
  await enqueueAddTarget(commandForm.value.target)
  ElMessage.success('添加目标命令已进入队列')
  commandForm.value.target = ''
  await refreshAll()
}

async function queueSync() {
  await enqueueSync(commandForm.value.syncSource, commandForm.value.syncLimit)
  ElMessage.success('同步命令已进入队列')
  await refreshAll()
}

async function login() {
  if (!loginForm.value.username || !loginForm.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  try {
    const result = await loginRequest(loginForm.value.username, loginForm.value.password)
    localStorage.setItem('admin_session_token', result.token)
    localStorage.setItem('admin_user_role', result.role || 'viewer')
    userRole.value = result.role || 'viewer'
    localStorage.removeItem('admin_api_token')
    authenticated.value = true
    loginForm.value.password = ''
    await refreshAll()
  } catch (error) {
    localStorage.removeItem('admin_session_token')
  localStorage.removeItem('admin_user_role')
  userRole.value = ''
    authenticated.value = false
    ElMessage.error(error.response?.data?.detail || '登录失败')
  }
}

function logout(showMessage = true) {
  localStorage.removeItem('admin_session_token')
  localStorage.removeItem('admin_user_role')
  userRole.value = ''
  localStorage.removeItem('admin_api_token')
  authenticated.value = false
  if (showMessage) ElMessage.success('已退出登录')
}

async function changePasswordAction() {
  if (!passwordForm.value.current || !passwordForm.value.next) return ElMessage.warning('请填写密码')
  if (passwordForm.value.next !== passwordForm.value.confirm) return ElMessage.warning('两次新密码不一致')
  try {
    await changePassword(passwordForm.value.current, passwordForm.value.next)
    ElMessage.success('密码已修改，请重新登录')
    logout(false)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '密码修改失败')
  }
}

async function logoutAllAction() {
  const result = await logoutAllSessions()
  ElMessage.success(`已撤销 ${result.revoked} 个会话`)
  logout(false)
}

async function saveUser() {
  if (!userForm.value.username || !userForm.value.password) return ElMessage.warning('请填写用户名和密码')
  await createUser(userForm.value)
  ElMessage.success('用户已创建')
  userDialog.value = false
  userForm.value = { username: '', password: '', role: 'viewer' }
  await refreshAll()
}

async function changeUserRole(row) {
  await updateUser(row.id, { role: row.role })
  ElMessage.success('角色已更新')
}

async function changeUserEnabled(row) {
  await updateUser(row.id, { enabled: row.enabled })
  ElMessage.success('用户状态已更新')
}

function selectPage(index) {
  activePage.value = index
  nextTick(renderChart)
}

onMounted(() => {
  if (authenticated.value) refreshAll()
})
</script>
