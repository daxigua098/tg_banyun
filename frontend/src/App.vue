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
        <el-menu-item index="queue">排队任务</el-menu-item>
        <el-menu-item index="audit">操作日志</el-menu-item>
        <el-menu-item index="login_history">登录历史</el-menu-item>
        <el-menu-item v-if="userRole === 'super_admin'" index="users">用户管理</el-menu-item>
        <el-menu-item index="account">账号安全</el-menu-item>
        <el-menu-item index="additional">内容设置</el-menu-item>
        <el-menu-item index="manual_post">手动发帖</el-menu-item>
        <el-menu-item index="ad_image">广告图生成</el-menu-item>
        <el-menu-item index="file_manager">文件管理</el-menu-item>
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
          <template #header>
            <div class="filters"><el-button type="primary" @click="sourceDialog = true">添加搬运源</el-button></div>
          </template>
          <el-table :data="sources" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="名称" min-width="180"><template #default="{ row }">{{ row.display_name || row.title }}</template></el-table-column>
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" @change="changeSourceEnabled(row)" />
              </template>
            </el-table-column>
            <el-table-column prop="sync_status" label="同步状态" width="110" />
            <el-table-column prop="last_synced_message_id" label="最新消息 ID" width="150" />
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-button type="primary" link @click="openImmediateSync(row)">立即搬运</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'targets'">
          <template #header>
            <div class="filters"><el-button type="primary" @click="targetDialog = true">添加接收目标</el-button></div>
          </template>
          <el-table :data="targets" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="名称" min-width="180"><template #default="{ row }">{{ row.display_name || row.title }}</template></el-table-column>
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

        <el-card v-else-if="activePage === 'file_manager'">
          <template #header>
            <div class="filters">
              <el-button type="danger" :disabled="!selectedUploads.length" @click="deleteSelectedUploads">
                批量删除（{{ selectedUploads.length }}）
              </el-button>
              <el-button @click="loadUploadAssets">刷新</el-button>
            </div>
          </template>
          <el-table :data="uploadAssets" stripe @selection-change="onUploadSelectionChange">
            <el-table-column type="selection" width="50" />
            <el-table-column label="预览" width="120">
              <template #default="{ row }">
                <el-image v-if="row.is_image" :src="row.url" :preview-src-list="[row.url]" fit="cover" style="width: 76px; height: 76px" />
                <span v-else>文件</span>
              </template>
            </el-table-column>
            <el-table-column prop="filename" label="文件名" min-width="260" />
            <el-table-column label="大小" width="120">
              <template #default="{ row }">{{ formatFileSize(row.size) }}</template>
            </el-table-column>
            <el-table-column prop="modified_at" label="上传时间" min-width="180" />
            <el-table-column label="操作" width="150">
              <template #default="{ row }">
                <el-link :href="row.url" target="_blank" type="primary">下载</el-link>
                <el-button type="danger" link @click="deleteSingleUpload(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card v-else-if="activePage === 'ad_image'">
          <template #header>智能广告图生成</template>
          <el-form label-width="120px">
            <el-form-item label="广告文字"><el-input v-model="adImageForm.text" type="textarea" :rows="6" placeholder="输入广告文字" /></el-form-item>
            <el-form-item label="宽度"><el-input-number v-model="adImageForm.width" :min="256" :max="4096" /></el-form-item>
            <el-form-item label="高度"><el-input-number v-model="adImageForm.height" :min="256" :max="4096" /></el-form-item>
            <el-form-item label="图片类型">
              <el-radio-group v-model="adImageForm.outputFormat">
                <el-radio-button value="static">静态图</el-radio-button>
                <el-radio-button value="dynamic">动态图</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="背景图">
              <el-upload :show-file-list="false" :http-request="selectAdBackground" accept=".png,.jpg,.jpeg,.webp">
                <el-button>选择背景图</el-button>
              </el-upload>
              <el-button v-if="adImageForm.background" link type="danger" @click="adImageForm.background = null">移除背景</el-button>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="generatingAdImage" @click="generateAdImageAction">
                {{ adImagePreview ? '重新生成' : '一键生成' }}
              </el-button>
              <el-button @click="saveAdImageDefaults">保存默认尺寸</el-button>
            </el-form-item>
          </el-form>
          <div v-if="adImagePreview" class="ad-preview">
            <img :src="adImagePreview" alt="生成的广告图" />
            <div class="command-row">
              <el-button type="success" @click="downloadAdImage">下载</el-button>
              <el-button @click="copyAdImage">复制图片</el-button>
            </div>
          </div>
        </el-card>

        <el-card v-else-if="activePage === 'manual_post'">
          <template #header>编辑并群发帖子</template>
          <el-form label-width="110px">
            <el-form-item label="目标群组">
              <el-select v-model="manualForm.targetIds" multiple placeholder="选择一个或多个目标" style="width: 100%">
                <el-option v-for="target in targets" :key="target.id" :label="`${target.id} - ${target.display_name || target.title}`" :value="target.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="帖子内容">
              <div class="rich-editor-wrap">
                <div class="rich-toolbar">
                  <el-button size="small" @click="editorCommand('bold')"><b>B</b></el-button>
                  <el-button size="small" @click="editorCommand('italic')"><i>I</i></el-button>
                  <el-button size="small" @click="editorCommand('underline')"><u>U</u></el-button>
                  <el-button size="small" @click="insertEditorLink">添加链接</el-button>
                </div>
                <div
                  ref="manualEditor"
                  class="rich-editor"
                  contenteditable="true"
                  data-placeholder="输入帖子内容，可直接粘贴图片"
                  @paste="handleManualPaste"
                ></div>
              </div>
            </el-form-item>
            <el-form-item label="配图">
              <el-upload :show-file-list="false" :http-request="uploadManualImage" accept=".png,.jpg,.jpeg,.webp,.gif">
                <el-button :loading="uploadingManualImage">上传配图</el-button>
              </el-upload>
              <span class="upload-hint">也可以在编辑框中直接 Ctrl+V 粘贴图片</span>
            </el-form-item>
            <el-form-item><el-button type="primary" @click="submitManualPost">加入发送队列</el-button></el-form-item>
          </el-form>
        </el-card>

        <el-card v-else-if="activePage === 'additional'">
          <template #header>附加内容设置</template>
          <el-form label-width="140px">
            <el-form-item label="启用附加内容"><el-switch v-model="additionalForm.enabled" /></el-form-item>
            <el-form-item label="追加广告文字"><el-input v-model="additionalForm.text" type="textarea" :rows="4" placeholder="会追加到每条搬运帖子的文字末尾" /></el-form-item>
            <el-form-item label="广告图/LOGO">
              <div class="command-row">
                <el-upload
                  :show-file-list="false"
                  :http-request="uploadAdditionalImageFile"
                  accept=".png,.jpg,.jpeg,.webp,.gif"
                >
                  <el-button :loading="uploadingImage">上传图片</el-button>
                </el-upload>
                <span class="upload-hint">上传后将自动加入下方路径列表</span>
              </div>
              <el-input v-model="additionalForm.imagePathsText" type="textarea" :rows="3" placeholder="每行一个图片路径，例如 assets/uploads/xxx.png" />
            </el-form-item>
            <el-form-item label="图片说明"><el-input v-model="additionalForm.image_caption" placeholder="发送附加图片时的说明文字" /></el-form-item>
            <el-form-item><el-button type="primary" @click="saveAdditionalSettings">保存设置</el-button></el-form-item>
          </el-form>
          <el-alert title="当前版本会将 LOGO/广告图作为附加图片发送，不会叠加到原图上。图片水印需要后续接入 FFmpeg。" type="info" :closable="false" />
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

        <el-card v-else-if="activePage === 'queue'">
          <template #header>
            <div class="filters">
              <span>任务每 2 秒自动刷新</span>
              <el-button @click="loadQueueCommands">立即刷新</el-button>
            </div>
          </template>
          <el-table :data="commands" stripe>
            <el-table-column prop="id" label="任务 ID" width="90" />
            <el-table-column prop="command_type" label="类型" width="150" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" min-width="260">
              <template #default="{ row }">
                <el-progress :percentage="row.progress?.percent || 0" />
                <div class="queue-detail">
                  完成 {{ row.progress?.completed || 0 }} / {{ row.progress?.total || 0 }}
                  ，成功 {{ row.progress?.success || 0 }}
                  ，失败 {{ row.progress?.failed || 0 }}
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="result" label="结果" min-width="180" show-overflow-tooltip />
            <el-table-column prop="error" label="错误" min-width="180" show-overflow-tooltip />
          </el-table>
        </el-card>

        <section v-else-if="activePage === 'commands'">
          <el-card class="command-card">
            <template #header>添加搬运源</template>
            <div class="command-row">
              <el-input v-model="commandForm.sourceName" placeholder="自定义名称，例如：新闻源" />
              <el-input v-model="commandForm.source" placeholder="@用户名、频道链接或私有邀请链接" />
              <el-checkbox v-model="commandForm.join">允许加入</el-checkbox>
              <el-button type="primary" @click="queueAddSource">提交</el-button>
            </div>
          </el-card>
          <el-card class="command-card">
            <template #header>添加接收目标</template>
            <div class="command-row">
              <el-input v-model="commandForm.targetName" placeholder="自定义名称，例如：接收群" />
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

    <el-dialog v-model="syncDialog" title="立即搬运历史消息" width="480px">
      <el-form label-width="100px">
        <el-form-item label="搬运源"><strong>{{ syncForm.sourceName }}</strong></el-form-item>
        <el-form-item label="搬运数量"><el-input-number v-model="syncForm.limit" :min="1" :max="5000" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="syncDialog = false">取消</el-button>
        <el-button type="primary" @click="submitImmediateSync">开始搬运</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sourceDialog" title="添加搬运源" width="560px">
      <el-form label-width="110px">
        <el-form-item label="自定义名称"><el-input v-model="addSourceForm.name" placeholder="例如：新闻源" /></el-form-item>
        <el-form-item label="用户名/链接"><el-input v-model="addSourceForm.input" placeholder="@username、频道链接、消息链接或私有邀请链接" /></el-form-item>
        <el-form-item label="自动加入"><el-switch v-model="addSourceForm.join" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialog = false">取消</el-button>
        <el-button type="primary" @click="submitAddSource">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="targetDialog" title="添加接收目标" width="560px">
      <el-form label-width="110px">
        <el-form-item label="自定义名称"><el-input v-model="addTargetForm.name" placeholder="例如：接收群" /></el-form-item>
        <el-form-item label="用户名/链接"><el-input v-model="addTargetForm.input" placeholder="Telegram 频道或群组链接" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="targetDialog = false">取消</el-button>
        <el-button type="primary" @click="submitAddTarget">提交</el-button>
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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
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
  generateAdImage,
  getAdImageDefaults,
  getAdditionalSettings,
  getUploadAssets,
  sendManualPost,
  getAuditLogs,
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
  updateAdditionalSettings,
  updateAdImageDefaults,
  deleteUploadAssets,
  uploadAdditionalImage,
  updateRule,
} from './api'

const authenticated = ref(Boolean(localStorage.getItem('admin_session_token') || localStorage.getItem('admin_api_token')))
const userRole = ref(localStorage.getItem('admin_user_role') || '')
const loginForm = ref({ username: 'admin', password: '' })
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
let queueTimer = null
const auditLogs = ref([])
const loginHistory = ref([])
const webUsers = ref([])
const userDialog = ref(false)
const sourceDialog = ref(false)
const syncDialog = ref(false)
const syncForm = ref({ sourceId: null, sourceName: '', limit: 30 })
const targetDialog = ref(false)
const addSourceForm = ref({ name: '', input: '', join: false })
const addTargetForm = ref({ name: '', input: '' })
const userForm = ref({ username: '', password: '', role: 'viewer' })
const passwordForm = ref({ current: '', next: '', confirm: '' })
const additionalForm = ref({ enabled: false, text: '', image_paths: [], imagePathsText: '', image_caption: '' })
const manualForm = ref({ targetIds: [], imagePaths: [] })
const manualEditor = ref(null)
const adImageForm = ref({ text: '', width: 1080, height: 1080, outputFormat: 'static', background: null })
const adImagePreview = ref('')
const uploadAssets = ref([])
const selectedUploads = ref([])
const generatingAdImage = ref(false)
const uploadingManualImage = ref(false)
const uploadingImage = ref(false)
const commandForm = ref({ sourceName: '', source: '', targetName: '', target: '', join: false, syncSource: 'all', syncLimit: 100 })
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
    await loadAdditionalSettings()
    await loadAdImageDefaults()
    await loadUploadAssets()
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

async function loadQueueCommands() {
  if (!authenticated.value) return
  commands.value = await getControlCommands()
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
  await enqueueAddSource(commandForm.value.sourceName, commandForm.value.source, commandForm.value.join)
  ElMessage.success('添加源命令已进入队列')
  commandForm.value.source = ''
  commandForm.value.sourceName = ''
  await refreshAll()
}

async function queueAddTarget() {
  if (!commandForm.value.target) return ElMessage.warning('请输入目标链接')
  await enqueueAddTarget(commandForm.value.targetName, commandForm.value.target)
  ElMessage.success('添加目标命令已进入队列')
  commandForm.value.target = ''
  commandForm.value.targetName = ''
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

function editorCommand(command, value = null) {
  manualEditor.value?.focus()
  document.execCommand(command, false, value)
}

function insertEditorLink() {
  const url = window.prompt('请输入链接地址', 'https://')
  if (url) editorCommand('createLink', url)
}

function editorImageUrl(path) {
  if (path.startsWith('assets/uploads/')) {
    return `/uploads/${path.split('/').pop()}`
  }
  return path
}

function insertEditorImage(path) {
  const editor = manualEditor.value
  if (!editor) return
  editor.focus()
  const image = document.createElement('img')
  image.src = editorImageUrl(path)
  image.dataset.uploadPath = path
  image.className = 'editor-pasted-image'
  document.execCommand('insertHTML', false, image.outerHTML)
  manualForm.value.imagePaths.push(path)
}

async function uploadManualImage(options) {
  uploadingManualImage.value = true
  try {
    const result = await uploadAdditionalImage(options.file)
    insertEditorImage(result.path)
    ElMessage.success('配图已上传')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '图片上传失败')
  } finally {
    uploadingManualImage.value = false
  }
}

async function handleManualPaste(event) {
  const items = Array.from(event.clipboardData?.items || [])
  const imageItem = items.find((item) => item.type.startsWith('image/'))
  if (!imageItem) return
  event.preventDefault()
  const file = imageItem.getAsFile()
  if (!file) return
  uploadingManualImage.value = true
  try {
    const result = await uploadAdditionalImage(file)
    insertEditorImage(result.path)
    ElMessage.success('粘贴图片已上传')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '粘贴图片上传失败')
  } finally {
    uploadingManualImage.value = false
  }
}

function telegramEditorHtml() {
  if (!manualEditor.value) return ''
  const clone = manualEditor.value.cloneNode(true)
  clone.querySelectorAll('img[data-upload-path]').forEach((image) => image.remove())
  clone.querySelectorAll('*').forEach((element) => {
    const tag = element.tagName.toLowerCase()
    if (tag === 'a') {
      const href = element.getAttribute('href') || ''
      Array.from(element.attributes).forEach((attribute) => element.removeAttribute(attribute.name))
      if (href) element.setAttribute('href', href)
    } else if (['b', 'strong', 'i', 'em', 'u', 's', 'br'].includes(tag)) {
      Array.from(element.attributes).forEach((attribute) => element.removeAttribute(attribute.name))
    } else if (['div', 'p'].includes(tag)) {
      element.replaceWith(...Array.from(element.childNodes), document.createElement('br'))
    } else {
      element.replaceWith(...Array.from(element.childNodes))
    }
  })
  return clone.innerHTML.trim()
}

async function submitManualPost() {
  if (!manualForm.value.targetIds.length) return ElMessage.warning('请选择目标群组')
  const textHtml = telegramEditorHtml()
  if (!textHtml && !manualForm.value.imagePaths.length) return ElMessage.warning('请输入文字或粘贴图片')
  await sendManualPost({
    target_ids: manualForm.value.targetIds,
    text_html: textHtml,
    image_paths: manualForm.value.imagePaths,
  })
  ElMessage.success('帖子已加入发送队列')
  manualForm.value = { targetIds: [], imagePaths: [] }
  if (manualEditor.value) manualEditor.value.innerHTML = ''
  setTimeout(refreshAll, 1500)
}

async function loadUploadAssets() {
  if (!authenticated.value) return
  uploadAssets.value = await getUploadAssets()
}

function onUploadSelectionChange(rows) {
  selectedUploads.value = rows
}

function formatFileSize(size) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

async function deleteUploads(filenames) {
  if (!filenames.length) return
  await ElMessageBox.confirm(`确定删除 ${filenames.length} 个文件吗？`, '删除确认', { type: 'warning' })
  await deleteUploadAssets(filenames)
  ElMessage.success('文件已删除')
  await loadUploadAssets()
}

async function deleteSingleUpload(row) {
  await deleteUploads([row.filename])
}

async function deleteSelectedUploads() {
  await deleteUploads(selectedUploads.value.map((item) => item.filename))
}

async function loadAdImageDefaults() {
  if (!authenticated.value) return
  const data = await getAdImageDefaults()
  adImageForm.value.width = data.default_width
  adImageForm.value.height = data.default_height
}

async function saveAdImageDefaults() {
  await updateAdImageDefaults({
    default_width: adImageForm.value.width,
    default_height: adImageForm.value.height,
  })
  ElMessage.success('默认尺寸已保存')
}

function selectAdBackground(options) {
  adImageForm.value.background = options.file
}

async function generateAdImageAction() {
  if (!adImageForm.value.text.trim()) return ElMessage.warning('请输入广告文字')
  generatingAdImage.value = true
  try {
    const response = await generateAdImage({
      text: adImageForm.value.text,
      width: adImageForm.value.width,
      height: adImageForm.value.height,
      outputFormat: adImageForm.value.outputFormat,
      background: adImageForm.value.background,
    })
    if (adImagePreview.value) URL.revokeObjectURL(adImagePreview.value)
    adImagePreview.value = URL.createObjectURL(response.data)
  } catch (error) {
    ElMessage.error('广告图生成失败')
  } finally {
    generatingAdImage.value = false
  }
}

async function downloadAdImage() {
  const link = document.createElement('a')
  link.href = adImagePreview.value
  link.download = adImageForm.value.outputFormat === 'dynamic' ? 'ad.gif' : 'ad.png'
  link.click()
}

async function copyAdImage() {
  try {
    const response = await fetch(adImagePreview.value)
    const blob = await response.blob()
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })])
    ElMessage.success('图片已复制')
  } catch {
    await navigator.clipboard.writeText(adImagePreview.value)
    ElMessage.success('图片地址已复制')
  }
}

async function loadAdditionalSettings() {
  if (!authenticated.value) return
  const data = await getAdditionalSettings()
  additionalForm.value = {
    enabled: data.enabled,
    text: data.text,
    image_paths: data.image_paths || [],
    imagePathsText: (data.image_paths || []).join('\n'),
    image_caption: data.image_caption || '',
  }
}

async function uploadAdditionalImageFile(options) {
  uploadingImage.value = true
  try {
    const result = await uploadAdditionalImage(options.file)
    const paths = String(additionalForm.value.imagePathsText || '')
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean)
    paths.push(result.path)
    additionalForm.value.imagePathsText = paths.join('\n')
    additionalForm.value.image_paths = paths
    ElMessage.success('图片已上传，保存设置后生效')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '图片上传失败')
  } finally {
    uploadingImage.value = false
  }
}

async function saveAdditionalSettings() {
  const imagePaths = String(additionalForm.value.imagePathsText || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
  const result = await updateAdditionalSettings({
    enabled: additionalForm.value.enabled,
    text: additionalForm.value.text,
    image_paths: imagePaths,
    image_caption: additionalForm.value.image_caption,
  })
  additionalForm.value.image_paths = result.image_paths
  additionalForm.value.imagePathsText = result.image_paths.join('\n')
  ElMessage.success('附加内容设置已保存')
}

function openImmediateSync(row) {
  syncForm.value = {
    sourceId: row.id,
    sourceName: row.display_name || row.title || `源 ${row.id}`,
    limit: 30,
  }
  syncDialog.value = true
}

async function submitImmediateSync() {
  if (!syncForm.value.limit || syncForm.value.limit < 1) return ElMessage.warning('请输入搬运数量')
  await enqueueSync(syncForm.value.sourceId, syncForm.value.limit)
  ElMessage.success('搬运命令已提交，后台将按顺序处理')
  syncDialog.value = false
  activePage.value = 'queue'
  await loadQueueCommands()
  setTimeout(refreshAll, 1500)
}

async function submitAddSource() {
  if (!addSourceForm.value.input) return ElMessage.warning('请输入用户名或链接')
  await enqueueAddSource(addSourceForm.value.name, addSourceForm.value.input, addSourceForm.value.join)
  ElMessage.success('添加源命令已提交，后台将按顺序处理')
  sourceDialog.value = false
  addSourceForm.value = { name: '', input: '', join: false }
  setTimeout(refreshAll, 1500)
}

async function submitAddTarget() {
  if (!addTargetForm.value.input) return ElMessage.warning('请输入用户名或链接')
  await enqueueAddTarget(addTargetForm.value.name, addTargetForm.value.input)
  ElMessage.success('添加目标命令已提交，后台将按顺序处理')
  targetDialog.value = false
  addTargetForm.value = { name: '', input: '' }
  setTimeout(refreshAll, 1500)
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
  queueTimer = window.setInterval(() => {
    if (authenticated.value && (activePage.value === 'queue' || activePage.value === 'commands')) {
      loadQueueCommands()
    }
  }, 2000)
})

onUnmounted(() => {
  if (queueTimer) window.clearInterval(queueTimer)
})
</script>
