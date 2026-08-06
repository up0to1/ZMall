/* ============================================================
 * AI 模特图任务列表页（v3.1 §15.1）
 *
 * 接口：
 *   GET /items/admin/ai-model/tasks?status=xxx  返回 List<AiTaskDTO>
 *   GET /items/admin/ai-model/task/{taskId}     单个任务详情
 *
 * 列表展示：任务 ID / 商品列表 / 状态 / 评分 / 发布 / 创建时间 / 操作
 * 操作：评分 / 发布 / 拒绝 / 查看大图
 * ============================================================ */
Vue.component('ai-model-tasks-page', {
  template: `
    <div>
      <div class="page-card">
        <div class="page-header">
          <h3>AI 模特图任务列表</h3>
          <el-button type="primary" size="small" icon="el-icon-plus" @click="goGenerate">新建生成</el-button>
        </div>

        <!-- v3.2：credits 余额条（与生成页一致，便于商家查看剩余配额） -->
        <el-alert :type="creditsBalance < 5 ? 'warning' : 'success'"
                  :closable="false" style="margin-bottom:16px;">
          <template slot="title">
            <span>Credits 余额：<strong>{{ creditsBalance }}</strong>（每次生成扣 5/12/18 credits，按生成模式：单图/多姿势/多换装）</span>
            <el-button type="text" style="margin-left:12px;"
                       @click="showRechargeDialog = true">💎 充值</el-button>
          </template>
        </el-alert>

        <!-- 筛选栏 -->
        <div class="search-bar">
          <el-select v-model="search.status" placeholder="任务状态" size="small" clearable style="width:160px">
            <el-option label="待处理 PENDING" value="PENDING"></el-option>
            <el-option label="生成中 PROCESSING" value="PROCESSING"></el-option>
            <el-option label="成功 SUCCESS" value="SUCCESS"></el-option>
            <el-option label="失败 FAILED" value="FAILED"></el-option>
            <el-option label="超时 TIMEOUT" value="TIMEOUT"></el-option>
          </el-select>
          <el-button type="primary" size="small" icon="el-icon-search" @click="loadList">搜索</el-button>
          <el-button size="small" @click="resetSearch">重置</el-button>
        </div>

        <el-table :data="tableData" border stripe v-loading="loading" style="width:100%">
          <el-table-column prop="taskId" label="任务 ID" width="180" show-overflow-tooltip></el-table-column>
          <el-table-column label="最终图" width="100" align="center">
            <template slot-scope="scope">
              <el-image v-if="getFinalUrl(scope.row)" :src="getFinalUrl(scope.row)"
                        style="width:60px;height:60px;" fit="cover"
                        :preview-src-list="scope.row.resultUrls || []">
              </el-image>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="涉及商品" min-width="180">
            <template slot-scope="scope">
              <span v-if="scope.row.itemIds && scope.row.itemIds.length">
                {{ scope.row.itemIds.join(', ') }}
                <span style="color:#909399;font-size:12px;">（{{ scope.row.itemIds.length }} 件）</span>
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110" align="center">
            <template slot-scope="scope">
              <el-tag :type="statusTagType(scope.row.status)" size="small">{{ statusText(scope.row.status) }}</el-tag>
              <div v-if="scope.row.status === 'PENDING' && scope.row.queuePosition > 0"
                   style="font-size:11px;color:#e6a23c;margin-top:2px;">
                前面 {{ scope.row.queuePosition }} 个
              </div>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100" align="center">
            <template slot-scope="scope">
              <span style="font-size:12px;color:#606266;">{{ computeDuration(scope.row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="评分" width="100" align="center">
            <template slot-scope="scope">
              <el-rate v-if="scope.row.starRating" :value="scope.row.starRating" disabled size="mini"
                       show-text :texts="['很差','不满意','一般','满意','很满意']">
              </el-rate>
              <span v-else style="color:#c0c4cc;">未评分</span>
            </template>
          </el-table-column>
          <el-table-column label="入池" width="70" align="center">
            <template slot-scope="scope">
              <el-tag v-if="scope.row.savedToPool === 1" type="success" size="mini">已入池</el-tag>
              <span v-else style="color:#c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="发布" width="100" align="center">
            <template slot-scope="scope">
              <span v-if="scope.row.publishedItemId" style="color:#67c23a;">→ {{ scope.row.publishedItemId }}</span>
              <span v-else style="color:#c0c4cc;">未发布</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="160" align="center">
            <template slot-scope="scope">{{ formatDate(scope.row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200" align="center" fixed="right">
            <template slot-scope="scope">
              <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:center;">
                <el-button v-if="canRate(scope.row)" size="mini" type="warning" @click="openRating(scope.row)">评分</el-button>
                <el-button v-if="canPublish(scope.row)" size="mini" type="primary" @click="openPublish(scope.row)">发布</el-button>
                <el-button v-if="canReject(scope.row)" size="mini" type="info" @click="openReject(scope.row)">拒绝</el-button>
                <el-button size="mini" @click="viewTask(scope.row)">详情</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="!loading && tableData.length === 0" style="text-align:center;color:#909399;padding:30px;">
          暂无任务记录
        </div>
      </div>

      <!-- 任务详情对话框 -->
      <el-dialog title="任务详情" :visible.sync="detailVisible" width="720px">
        <div v-if="currentTask">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="任务 ID">{{ currentTask.taskId }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="statusTagType(currentTask.status)" size="small">{{ statusText(currentTask.status) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="店铺 ID">{{ currentTask.shopId || '-' }}</el-descriptions-item>
            <el-descriptions-item label="涉及商品 ID">{{ (currentTask.itemIds || []).join(', ') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDate(currentTask.createdAt) }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ formatDate(currentTask.finishedAt) }}</el-descriptions-item>
            <el-descriptions-item label="评分" :span="2">
              <el-rate v-if="currentTask.starRating" :value="currentTask.starRating" disabled></el-rate>
              <span v-else style="color:#c0c4cc;">未评分</span>
              <span v-if="currentTask.ratingTags && currentTask.ratingTags.length" style="margin-left:12px;">
                <el-tag v-for="t in currentTask.ratingTags" :key="t" size="mini" style="margin-right:4px;">{{ t }}</el-tag>
              </span>
            </el-descriptions-item>
            <el-descriptions-item v-if="currentTask.ratingNote" label="评分备注" :span="2">{{ currentTask.ratingNote }}</el-descriptions-item>
            <el-descriptions-item v-if="currentTask.rejectReason" label="拒绝原因" :span="2">{{ currentTask.rejectReason }}</el-descriptions-item>
            <el-descriptions-item v-if="currentTask.errorMsg" label="错误信息" :span="2">
              <span style="color:#f56c6c;">{{ currentTask.errorMsg }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="发布到商品" :span="2">
              <span v-if="currentTask.publishedItemId" style="color:#67c23a;">已发布 → {{ currentTask.publishedItemId }}</span>
              <span v-else style="color:#c0c4cc;">未发布</span>
            </el-descriptions-item>
          </el-descriptions>
          <div v-if="currentTask.resultUrls && currentTask.resultUrls.length" style="margin-top:16px;">
            <div style="font-weight:bold;margin-bottom:8px;">生成图（{{ currentTask.resultUrls.length }} 张，最后一张为最终图）：</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;">
              <div v-for="(url, idx) in currentTask.resultUrls" :key="idx" style="position:relative;">
                <el-image :src="url" fit="cover" style="width:100%;height:160px;border-radius:4px;border:1px solid #eee;"
                          :preview-src-list="currentTask.resultUrls">
                </el-image>
                <div style="position:absolute;top:4px;left:4px;background:rgba(0,0,0,0.6);color:#fff;font-size:11px;padding:1px 6px;border-radius:2px;">
                  {{ idx === currentTask.resultUrls.length - 1 ? '最终图' : (currentTask.itemCategories[idx] || '#' + (idx + 1)) }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <span slot="footer">
          <el-button @click="detailVisible = false">关闭</el-button>
          <el-button v-if="currentTask && canRate(currentTask)" type="warning" @click="detailVisible = false; openRating(currentTask)">去评分</el-button>
          <el-button v-if="currentTask && canPublish(currentTask)" type="primary" @click="detailVisible = false; openPublish(currentTask)">去发布</el-button>
          <el-button v-if="currentTask && canReject(currentTask)" type="info" @click="detailVisible = false; openReject(currentTask)">反馈原因</el-button>
        </span>
      </el-dialog>

      <!-- 评分对话框 -->
      <rating-dialog :show="showRating"
                     :task-id="currentTask ? currentTask.taskId : ''"
                     :final-image-url="currentTaskFinalUrl"
                     @close="showRating = false"
                     @rated="onRated">
      </rating-dialog>

      <!-- 发布对话框 -->
      <publish-dialog :show="showPublish"
                      :task-id="currentTask ? currentTask.taskId : ''"
                      :image-url="currentTaskFinalUrl"
                      :items="currentTaskPublishOptions"
                      :star-rating="currentTask ? (currentTask.starRating || 0) : 0"
                      @close="showPublish = false"
                      @published="onPublished"
                      @reject="onPublishReject">
      </publish-dialog>

      <!-- 拒绝原因对话框 -->
      <reject-dialog :show="showReject"
                     :task-id="currentTask ? currentTask.taskId : ''"
                     :star-rating="currentTask ? (currentTask.starRating || 0) : 0"
                     @close="showReject = false"
                     @submitted="onRejectSubmitted">
      </reject-dialog>

      <!-- v3.2：Credits 充值对话框（后台原生，替代跳转前台） -->
      <recharge-dialog :show="showRechargeDialog"
                       :current-balance="creditsBalance"
                       :wallet-balance="walletBalance"
                       :first-gift-received="firstGiftReceived"
                       @close="showRechargeDialog = false"
                       @recharged="onRecharged">
      </recharge-dialog>
    </div>
  `,
  data() {
    return {
      loading: false,
      tableData: [],
      search: { status: '' },
      // 详情
      detailVisible: false,
      currentTask: null,
      // 对话框
      showRating: false,
      showPublish: false,
      showReject: false,
      // v3.2：credits 余额
      creditsBalance: 0,
      // v3.2：充值对话框（后台原生，替代跳转前台）
      showRechargeDialog: false,
      walletBalance: 0,            // 钱包余额（分）
      firstGiftReceived: false,
      // 异步任务实时刷新：WS 订阅 + 30s 兜底轮询
      ws: null,
      refreshTimer: null,
      nowTicker: null,
      now: Date.now(),
    };
  },
  computed: {
    currentTaskFinalUrl() {
      if (!this.currentTask || !this.currentTask.resultUrls || this.currentTask.resultUrls.length === 0) return '';
      return this.currentTask.resultUrls[this.currentTask.resultUrls.length - 1];
    },
    currentTaskPublishOptions() {
      // 任务列表没有商品 name/category 信息，仅返回 itemId 列表
      if (!this.currentTask || !this.currentTask.itemIds) return [];
      return this.currentTask.itemIds.map(id => ({ itemId: id, name: '商品 ' + id, category: '' }));
    },
  },
  mounted() {
    this.loadList();
    this.loadCredits();  // v3.2：加载 credits 余额
    this.startWsSubscription();
    // now ticker：每秒刷新，用于实时计算 PROCESSING 任务的耗时
    this.nowTicker = setInterval(() => { this.now = Date.now(); }, 1000);
  },
  beforeDestroy() {
    this.stopAutoRefresh();
    if (this.nowTicker) { clearInterval(this.nowTicker); this.nowTicker = null; }
    if (this.ws) { this.ws.close(); this.ws = null; }
  },
  methods: {
    formatDate(s) { return ZM.formatDate(s); },
    goGenerate() { this.$root.currentMenu = 'ai-model-generate'; },
    // v3.2：加载 credits 余额 + 钱包余额 + 首充标记（与生成页共用）
    loadCredits() {
      const userId = (ZM.getUser() || {}).userId || 0;
      if (!userId) return;
      ZM.http.get('/credits/balance/' + userId).then(res => {
        this.creditsBalance = (res && res.balance) || 0;
        this.firstGiftReceived = !!(res && res.firstGiftReceived);
        // v3.2：walletBalance 是真实 user.balance（分），由后端 queryBalanceInternal 查询填充
        this.walletBalance = (res && res.walletBalance) || 0;
      }).catch(() => {});
    },
    // v3.2：充值成功回调，刷新余额
    onRecharged() {
      this.loadCredits();
    },
    statusText(s) {
      const m = { PENDING: '待处理', PROCESSING: '生成中', SUCCESS: '成功', FAILED: '失败', TIMEOUT: '超时' };
      return m[s] || s || '-';
    },
    statusTagType(s) {
      const m = { PENDING: 'info', PROCESSING: 'warning', SUCCESS: 'success', FAILED: 'danger', TIMEOUT: 'danger' };
      return m[s] || '';
    },
    getFinalUrl(row) {
      if (!row || !row.resultUrls || row.resultUrls.length === 0) return '';
      return row.resultUrls[row.resultUrls.length - 1];
    },
    canRate(row) {
      // SUCCESS 状态且未评分
      return row && row.status === 'SUCCESS' && !row.starRating;
    },
    canPublish(row) {
      // SUCCESS 状态且未发布
      return row && row.status === 'SUCCESS' && !row.publishedItemId;
    },
    canReject(row) {
      // 仅 SUCCESS 且未发布、未评分的任务可填写拒绝原因
      if (!row) return false;
      if (row.status !== 'SUCCESS') return false;
      if (row.publishedItemId) return false;
      if (row.starRating) return false;
      return !row.rejectReason;
    },
    loadList() {
      this.loading = true;
      const params = {};
      if (this.search.status) params.status = this.search.status;
      ZM.http.get('/items/admin/ai-model/tasks', { params }).then(res => {
        this.loading = false;
        this.tableData = Array.isArray(res) ? res : (res && res.list ? res.list : []);
        // 根据是否有进行中任务启停自动刷新
        this.syncAutoRefresh();
      }).catch(() => { this.loading = false; });
    },
    // ===== 异步任务实时刷新：WS + 30s 兜底轮询 =====
    startWsSubscription() {
      const userId = (ZM.getUser() || {}).userId || 0;
      if (!userId) return;
      // taskId=null 表示订阅该用户所有任务消息
      this.ws = new AiModelWS(userId, null, {
        onMessage: (msg) => this.onWsMessage(msg),
        onClose: () => {
          // WS 断开时启动轮询兜底（如果有进行中任务）
          this.syncAutoRefresh();
        },
      });
      this.ws.connect();
    },
    onWsMessage(msg) {
      if (!msg || msg.type !== 'AI_MODEL') return;
      // 找到对应行，局部更新
      const idx = this.tableData.findIndex(r => r.taskId === msg.taskId);
      if (idx < 0) {
        // 不在当前列表（可能是新任务或被筛选过滤），触发整表刷新
        this.loadList();
        return;
      }
      const row = this.tableData[idx];
      row.status = msg.status || row.status;
      if (msg.resultUrls) row.resultUrls = msg.resultUrls;
      if (msg.itemCategories) row.itemCategories = msg.itemCategories;
      if (msg.itemIds) row.itemIds = msg.itemIds;
      if (msg.starRating !== undefined) row.starRating = msg.starRating;
      // 任务进入终态时清理排队位置
      if (msg.status === 'SUCCESS' || msg.status === 'FAILED' || msg.status === 'TIMEOUT') {
        row.queuePosition = null;
        row.finishedAt = new Date().toISOString();
      }
      // 触发 Vue 响应式更新
      this.$set(this.tableData, idx, Object.assign({}, row));
      // 终态时弹出通知
      if (msg.status === 'SUCCESS') {
        this.$notify({ title: '生成完成', message: `任务 ${msg.taskId.substring(0, 8)}... 已完成`, type: 'success', duration: 4000 });
      } else if (msg.status === 'FAILED' || msg.status === 'TIMEOUT') {
        this.$notify({ title: '生成失败', message: `任务 ${msg.taskId.substring(0, 8)}... ${msg.status === 'TIMEOUT' ? '超时' : '失败'}`, type: 'error', duration: 4000 });
      }
      this.syncAutoRefresh();
    },
    // 有 PENDING/PROCESSING 任务时启动 30s 兜底轮询，无则停止
    syncAutoRefresh() {
      const hasActive = this.tableData.some(r => r.status === 'PENDING' || r.status === 'PROCESSING');
      if (hasActive && !this.refreshTimer) {
        this.refreshTimer = setInterval(() => { this.loadList(); }, 30000);
      } else if (!hasActive && this.refreshTimer) {
        clearInterval(this.refreshTimer);
        this.refreshTimer = null;
      }
    },
    stopAutoRefresh() {
      if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    },
    // 计算耗时：PENDING/PROCESSING 用 now-createdAt，终态用 finishedAt-createdAt
    computeDuration(row) {
      if (!row || !row.createdAt) return '-';
      const start = new Date(row.createdAt).getTime();
      const end = (row.status === 'PENDING' || row.status === 'PROCESSING' || !row.finishedAt)
        ? this.now
        : new Date(row.finishedAt).getTime();
      const ms = end - start;
      if (ms < 0 || isNaN(ms)) return '-';
      if (ms < 60000) return Math.floor(ms / 1000) + 's';
      if (ms < 3600000) return Math.floor(ms / 60000) + 'm' + Math.floor((ms % 60000) / 1000) + 's';
      return Math.floor(ms / 3600000) + 'h' + Math.floor((ms % 3600000) / 60000) + 'm';
    },
    resetSearch() {
      this.search = { status: '' };
      this.loadList();
    },
    viewTask(row) {
      this.currentTask = row;
      this.detailVisible = true;
    },
    openRating(row) {
      this.currentTask = row;
      this.showRating = true;
    },
    openPublish(row) {
      this.currentTask = row;
      this.showPublish = true;
    },
    openReject(row) {
      this.currentTask = row;
      this.showReject = true;
    },
    // 对话框回调
    onRated(res) {
      this.showRating = false;
      if (this.currentTask) {
        this.currentTask.starRating = res.starRating;
        this.currentTask.savedToPool = res.savedToPool;
        this.currentTask.ratingTags = res.ratingTags;
        this.currentTask.ratingNote = res.ratingNote;
      }
      // 评分完成 → 自动弹发布
      if (this.currentTask && !this.currentTask.publishedItemId) {
        this.$nextTick(() => { this.showPublish = true; });
      }
    },
    onPublished(res) {
      this.showPublish = false;
      if (this.currentTask) this.currentTask.publishedItemId = res.itemId;
      this.$notify({
        title: '发布成功',
        message: `模特图已替换商品 ${res.itemId} 的主图`,
        type: 'success', duration: 3000,
      });
    },
    onPublishReject() {
      this.showPublish = false;
      this.$nextTick(() => { this.showReject = true; });
    },
    onRejectSubmitted(res) {
      this.showReject = false;
      if (this.currentTask && res && !res.action) {
        this.currentTask.rejectReason = res.rejectReason || '';
      }
      if (res && res.action === 'regenerate') {
        this.goGenerate();
      }
    },
  },
});
