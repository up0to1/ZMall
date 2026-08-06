/* ============================================================
 * AI 模特图生成页（v3.1 §15.1）
 *
 * 流程：
 *   1. 选商品（1-4 件，本店铺商品）
 *   2. 选系统模特图（从 system-images 接口筛选拉取）
 *   3. 提交生成（POST /items/admin/ai-model/generate）
 *   4. WS / 轮询接收结果
 *   5. 自动弹评分对话框（评分后弹发布）
 *
 * 接口：
 *   POST /items/admin/ai-model/generate  入参 AiModelGenerateDTO { itemIds, modelImageId }
 *   GET  /items/admin/ai-model/system-images  返回 PageDTO<SystemModelImageDTO>
 *   GET  /items/admin/page  本店铺商品分页（沿用 goods/list.js 接口）
 * ============================================================ */
Vue.component('ai-model-generate-page', {
  template: `
    <div>
      <div class="page-card">
        <div class="page-header">
          <h3>AI 模特图生成</h3>
          <el-button type="text" icon="el-icon-tickets" @click="goTasks">查看任务列表</el-button>
        </div>

        <!-- v3.2：credits 余额条（与 AI 随心搭共享 user_id 配额池） -->
        <el-alert :type="creditsBalance < requiredCredits ? 'warning' : 'success'"
                  :closable="false" style="margin-bottom:16px;">
          <template slot="title">
            <span>Credits 余额：<strong>{{ creditsBalance }}</strong>（当前模式需扣 <strong>{{ requiredCredits }}</strong> credits）</span>
            <el-button type="text" style="margin-left:12px;"
                       @click="showRechargeDialog = true">💎 充值</el-button>
          </template>
        </el-alert>

        <el-alert type="info" :closable="false" style="margin-bottom:16px;">
          <template slot="title">
            <strong>使用流程：</strong>选模式 → 选商品（最多 {{ maxItems }} 件）→ 选系统模特图 → 提交生成 → 评分 → 发布到商品主图
          </template>
        </el-alert>

        <!-- v5：生成模式选择 -->
        <el-card shadow="never" style="margin-bottom:16px;">
          <div slot="header">
            <span>生成模式</span>
            <span style="color:#909399;font-size:12px;margin-left:8px;">v5 多图模式</span>
          </div>
          <el-radio-group v-model="generationMode" @change="handleModeChange" size="small">
            <el-radio-button label="single">单图模式</el-radio-button>
            <el-radio-button label="multi_pose">多姿势模式（同脸同妆造同服装）</el-radio-button>
            <el-radio-button label="multi_outfit">多换装模式（同脸同妆造不同服装）</el-radio-button>
          </el-radio-group>
          <div style="margin-top:12px;font-size:12px;color:#606266;line-height:1.6;">
            <span v-if="generationMode === 'single'">
              <strong>单图模式：</strong>1 件下装 + 1 件上装搭配，生成 1 张模特图，扣 5 credits（约 30-90s）
            </span>
            <span v-else-if="generationMode === 'multi_pose'">
              <strong>多姿势模式：</strong>1 套服装搭配，1 次链式 VTON 生成基准图 + {{ poseCount }} 次 O1 图生图生成不同姿势变体，扣 {{ requiredCredits }} credits
            </span>
            <span v-else-if="generationMode === 'multi_outfit'">
              <strong>多换装模式：</strong>允许 2 件下装 + 1 件上装，LLM 智能推荐 1-4 套搭配组合并行生成，扣 {{ requiredCredits }} credits
            </span>
          </div>
          <div v-if="generationMode === 'multi_pose'" style="margin-top:12px;display:flex;align-items:center;">
            <span style="font-size:13px;margin-right:8px;">姿势数量：</span>
            <el-input-number v-model="poseCount" :min="2" :max="4" :step="1" size="small"
                             @change="handlePoseCountChange"></el-input-number>
            <span style="font-size:12px;color:#909399;margin-left:8px;">推荐 3 个姿势（如：正面站立/坐姿/侧身）</span>
          </div>
        </el-card>

        <!-- 步骤 1：选商品 -->
        <el-card shadow="never" style="margin-bottom:16px;">
          <div slot="header">
            <span>① 选择商品（{{ selectedItemIds.length }}/{{ maxItems }}）{{ categoryHint }}</span>
            <el-button style="float:right" type="primary" size="mini" icon="el-icon-plus"
                       @click="openItemPicker">添加商品</el-button>
          </div>
          <div v-if="selectedItems.length === 0" style="color:#999;text-align:center;padding:20px;">
            暂未选择商品，点击右上角"添加商品"
          </div>
          <el-table v-else :data="selectedItems" border size="small">
            <el-table-column label="图片" width="120" align="center">
              <template slot-scope="scope">
                <el-image v-if="scope.row.image" :src="scope.row.image"
                          style="width:96px;height:96px;border-radius:4px;"
                          fit="cover" :preview-src-list="[scope.row.image]"></el-image>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="id" label="ID" width="70" align="center"></el-table-column>
            <el-table-column prop="name" label="商品名称" min-width="180" show-overflow-tooltip></el-table-column>
            <el-table-column prop="category" label="分类" width="100" align="center"></el-table-column>
            <el-table-column label="价格" width="100" align="center">
              <template slot-scope="scope">&yen;{{ formatMoney(scope.row.price) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template slot-scope="scope">
                <el-button size="mini" type="danger" @click="removeItem(scope.row.id)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 步骤 2：选模特图 -->
        <el-card shadow="never" style="margin-bottom:16px;">
          <div slot="header">
            <span>② 选择系统模特图 <span v-if="selectedModel" style="color:#67c23a;font-size:13px;">✓ 已选 ID: {{ selectedModel.id }}</span></span>
            <el-button style="float:right" type="text" @click="goSystemImages">管理模特图池 →</el-button>
          </div>
          <div class="search-bar" style="margin-bottom:12px;">
            <el-select v-model="modelFilter.gender" placeholder="性别" size="small" clearable style="width:120px">
              <el-option label="男" value="male"></el-option>
              <el-option label="女" value="female"></el-option>
            </el-select>
            <el-select v-model="modelFilter.skinTone" placeholder="肤色" size="small" clearable style="width:120px">
              <el-option label="白皙" value="fair"></el-option>
              <el-option label="小麦" value="wheat"></el-option>
              <el-option label="深色" value="dark"></el-option>
            </el-select>
            <el-button type="primary" size="small" icon="el-icon-search" @click="loadModels">筛选</el-button>
            <el-button size="small" @click="resetModelFilter">重置</el-button>
          </div>
          <div v-loading="modelLoading" style="min-height:120px;">
            <div v-if="models.length === 0 && !modelLoading" style="color:#999;text-align:center;padding:20px;">
              暂无模特图，请先到"管理模特图池"上传
            </div>
            <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;">
              <div v-for="m in models" :key="m.id"
                   class="model-pick-card" :class="{active: selectedModel && selectedModel.id === m.id}"
                   @click="selectModel(m)">
                <img :src="m.imageUrl" :alt="'模特图 ' + m.id" v-if="m.imageUrl"/>
                <div v-else class="no-image">无图</div>
                <div class="model-meta">
                  <span class="tag">{{ genderText(m.gender) }}</span>
                  <span class="tag">{{ skinToneText(m.skinTone) }}</span>
                  <span v-if="m.isDefault" class="tag tag-warn">默认</span>
                </div>
              </div>
            </div>
            <div v-if="models.length > 0" style="margin-top:12px;text-align:right;">
              <el-pagination background layout="prev, pager, next" :total="modelTotal"
                             :page-size="modelPageSize" :current-page.sync="modelCurrentPage"
                             @current-change="loadModels" small>
              </el-pagination>
            </div>
          </div>
        </el-card>

        <!-- 步骤 3：提交 -->
        <el-card shadow="never">
          <div style="text-align:center;padding:16px;">
            <el-button type="primary" size="medium" icon="el-icon-magic-stick"
                       :disabled="!canSubmit" :loading="submitting"
                       @click="submitGenerate" style="padding:12px 48px;font-size:16px;">
              {{ submitting ? '提交中...' : '生成 AI 模特图' }}
            </el-button>
            <div style="font-size:12px;color:#909399;margin-top:8px;">
              需选 1-4 件商品 + 1 张模特图；提交后任务在后台生成，可继续操作其他事项
            </div>
          </div>
        </el-card>

        <!-- 结果展示 + 评分/发布入口 -->
        <el-card v-if="result || failed" shadow="never" style="margin-top:16px;">
          <div slot="header">
            <span>生成结果</span>
            <span v-if="result" style="color:#67c23a;margin-left:8px;font-size:13px;">✓ 任务 {{ result.taskId }}</span>
            <span v-if="failed" style="color:#f56c6c;margin-left:8px;font-size:13px;">✗ 失败</span>
          </div>
          <div v-if="failed" style="text-align:center;color:#f56c6c;padding:20px;">
            <div style="font-size:48px;">⚠</div>
            <p>{{ errorMsg }}</p>
            <el-button type="primary" @click="resetResult">重新生成</el-button>
          </div>
          <div v-else-if="result">
            <!-- v5 多姿势模式：按姿势分组展示 -->
            <div v-if="generationMode === 'multi_pose' && result.poseResults && result.poseResults.length">
              <div v-for="(pose, idx) in result.poseResults" :key="'pose-'+idx"
                   style="margin-bottom:20px;padding:12px;background:#fafafa;border-radius:6px;">
                <div style="display:flex;align-items:center;margin-bottom:8px;">
                  <strong style="font-size:14px;color:#303133;">姿势 {{ idx + 1 }}</strong>
                  <span v-if="pose.pose_name" style="margin-left:8px;font-size:13px;color:#606266;">{{ pose.pose_name }}</span>
                  <span v-if="pose.intent_cn" style="margin-left:8px;font-size:12px;color:#909399;">{{ pose.intent_cn }}</span>
                  <span v-if="pose.overall_score" style="margin-left:auto;color:#67c23a;font-size:12px;">
                    评分: {{ (pose.overall_score * 100).toFixed(1) }}%
                  </span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;">
                  <div v-for="(url, uIdx) in (pose.result_urls || [])" :key="'pose-'+idx+'-'+uIdx" class="result-image-card">
                    <img :src="url" :alt="'姿势 ' + (idx + 1) + ' 图 ' + (uIdx + 1)"/>
                    <div class="result-badge" :class="{final: uIdx === (pose.result_urls || []).length - 1}">
                      {{ uIdx === (pose.result_urls || []).length - 1 ? '最终图' : ((pose.item_categories || [])[uIdx] || '中间图') }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- v5 多换装模式：按场景分组展示 -->
            <div v-else-if="generationMode === 'multi_outfit' && result.sceneResults && result.sceneResults.length">
              <div v-for="(scene, idx) in result.sceneResults" :key="'scene-'+idx"
                   style="margin-bottom:20px;padding:12px;background:#fafafa;border-radius:6px;">
                <div style="display:flex;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
                  <strong style="font-size:14px;color:#303133;">场景 {{ idx + 1 }}</strong>
                  <span v-if="scene.decision_reason_cn" style="margin-left:8px;font-size:13px;color:#606266;">
                    {{ scene.decision_reason_cn }}
                  </span>
                  <span v-if="scene.overall_score" style="margin-left:auto;color:#67c23a;font-size:12px;">
                    评分: {{ (scene.overall_score * 100).toFixed(1) }}%
                  </span>
                </div>
                <div v-if="scene.combination && scene.combination.length" style="font-size:12px;color:#909399;margin-bottom:8px;">
                  商品 ID：{{ scene.combination.join(', ') }}
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;">
                  <div v-for="(url, uIdx) in (scene.result_urls || [])" :key="'scene-'+idx+'-'+uIdx" class="result-image-card">
                    <img :src="url" :alt="'场景 ' + (idx + 1) + ' 图 ' + (uIdx + 1)"/>
                    <div class="result-badge" :class="{final: uIdx === (scene.result_urls || []).length - 1}">
                      {{ uIdx === (scene.result_urls || []).length - 1 ? '最终图' : ((scene.item_categories || [])[uIdx] || '中间图') }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- 默认（单图模式）：平铺展示所有图 -->
            <div v-else>
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:16px;">
                <div v-for="(url, idx) in result.resultUrls" :key="idx" class="result-image-card">
                  <img :src="url" :alt="'图 ' + (idx + 1)"/>
                  <div class="result-badge" :class="{final: idx === result.resultUrls.length - 1}">
                    {{ idx === result.resultUrls.length - 1 ? '最终图' : (result.itemCategories[idx] || '中间图 ' + (idx + 1)) }}
                  </div>
                </div>
              </div>
            </div>
            <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
              <el-button type="warning" @click="showRatingDialog = true" :disabled="!canRate">
                {{ result.starRating ? ('已评分 ' + result.starRating + '★') : '🎨 评分' }}
              </el-button>
              <el-button type="primary" @click="showPublishDialog = true" :disabled="!canPublish">
                {{ result.publishedItemId ? '✓ 已发布' : '📤 发布到商品' }}
              </el-button>
              <el-button v-if="!result.publishedItemId && !result.rejectReason" type="info" @click="showRejectDialog = true">
                📝 反馈原因
              </el-button>
              <el-button @click="resetResult">重新生成</el-button>
            </div>
            <div style="margin-top:12px;font-size:12px;color:#909399;text-align:center;">
              涉及商品 ID：{{ (result.itemIds || []).join(', ') || '-' }}
            </div>
          </div>
        </el-card>
      </div>

      <!-- 商品选择模态框 -->
      <el-dialog title="选择商品" :visible.sync="itemPickerVisible" width="800px">
        <div class="search-bar">
          <el-input v-model="itemSearch.name" placeholder="商品名称" size="small" clearable></el-input>
          <el-button type="primary" size="small" icon="el-icon-search" @click="itemCurrentPage=1;loadItems()">搜索</el-button>
        </div>
        <el-table :data="itemTableData" border size="small" v-loading="itemLoading"
                  @selection-change="onItemSelectionChange" ref="itemTable">
          <el-table-column type="selection" width="50" :selectable="canSelectItem"></el-table-column>
          <el-table-column prop="id" label="ID" width="70" align="center"></el-table-column>
          <el-table-column label="图片" width="120" align="center">
            <template slot-scope="scope">
              <el-image v-if="scope.row.image" :src="scope.row.image"
                        style="width:88px;height:88px;border-radius:4px;"
                        fit="cover" :preview-src-list="[scope.row.image]"></el-image>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="商品名称" min-width="180" show-overflow-tooltip></el-table-column>
          <el-table-column prop="category" label="分类" width="100" align="center"></el-table-column>
          <el-table-column label="价格" width="100" align="center">
            <template slot-scope="scope">&yen;{{ formatMoney(scope.row.price) }}</template>
          </el-table-column>
        </el-table>
        <div style="margin-top:12px;text-align:right;">
          <el-pagination background layout="prev, pager, next" :total="itemTotal"
                         :page-size="itemPageSize" :current-page.sync="itemCurrentPage"
                         @current-change="loadItems" small>
          </el-pagination>
        </div>
        <span slot="footer">
          <el-button @click="itemPickerVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmItemPicker">确认（{{ tempSelectedItems.length }}/{{ maxItems }}）</el-button>
        </span>
      </el-dialog>

      <!-- 评分对话框 -->
      <rating-dialog :show="showRatingDialog"
                     :task-id="result ? result.taskId : ''"
                     :final-image-url="finalImageUrl"
                     @close="showRatingDialog = false"
                     @rated="onRated">
      </rating-dialog>

      <!-- 发布对话框 -->
      <publish-dialog :show="showPublishDialog"
                      :task-id="result ? result.taskId : ''"
                      :image-url="finalImageUrl"
                      :items="publishItemOptions"
                      :star-rating="result ? (result.starRating || 0) : 0"
                      @close="showPublishDialog = false"
                      @published="onPublished"
                      @reject="onPublishReject">
      </publish-dialog>

      <!-- 拒绝原因对话框 -->
      <reject-dialog :show="showRejectDialog"
                     :task-id="result ? result.taskId : ''"
                     :star-rating="result ? (result.starRating || 0) : 0"
                     @close="showRejectDialog = false"
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
      // 商品选择
      selectedItems: [],           // 已选商品（含完整信息）
      selectedItemIds: [],         // 已选商品 ID 数组
      itemPickerVisible: false,
      itemTableData: [],
      itemLoading: false,
      itemTotal: 0,
      itemCurrentPage: 1,
      itemPageSize: 10,
      itemSearch: { name: '' },
      tempSelectedItems: [],       // 模态框内临时选择

      // 模特图选择
      models: [],
      modelLoading: false,
      modelTotal: 0,
      modelCurrentPage: 1,
      modelPageSize: 10,
      modelFilter: { gender: '', skinTone: '' },
      selectedModel: null,

      // 提交生成
      submitting: false,
      result: null,
      failed: false,
      errorMsg: '',

      // 评分/发布/拒绝对话框
      showRatingDialog: false,
      showPublishDialog: false,
      showRejectDialog: false,

      // v3.2：credits 余额（与 AI 随心搭共享 user_id 配额池，shopId=userId）
      creditsBalance: 0,
      // v3.2：充值对话框（后台原生，替代跳转前台）
      showRechargeDialog: false,
      walletBalance: 0,            // 钱包余额（分）
      firstGiftReceived: false,

      // v5：多图模式
      generationMode: 'single',    // single / multi_outfit / multi_pose
      poseCount: 3,                // 多姿势模式的姿势数量（2-4）
    };
  },
  computed: {
    userId() { return (ZM.getUser() || {}).userId || 0; },
    // v5：根据模式动态计算最大商品数
    // - single / multi_pose：最多 3 件（1 件下装 + 1 件上装 + 1 件帽子，或 1 件全身套装 + 1 件帽子）
    // - multi_outfit：最多 4 件（允许 2 件下装 + 1 件上装 + 1 件帽子）
    maxItems() {
      return this.generationMode === 'multi_outfit' ? 4 : 3;
    },
    // v5：根据模式计算所需 credits
    // - single：5 credits（链式 VTON）
    // - multi_pose：3 + poses * 3 credits（1 次 VTON + N 次 O1 图生图）
    // - multi_outfit：18 credits（多套组合并行 VTON + 独立评估）
    requiredCredits() {
      if (this.generationMode === 'multi_pose') {
        return 3 + this.poseCount * 3;
      } else if (this.generationMode === 'multi_outfit') {
        return 18;
      }
      return 5;
    },
    // v5：商品分类限制提示
    categoryHint() {
      if (this.generationMode === 'multi_outfit') {
        return ' · 多换装：上衣≤2，下装≤2，全身套装≤1，帽子≤1（LLM 智能推荐多套搭配）';
      } else if (this.generationMode === 'multi_pose') {
        return ' · 多姿势：1 套服装（1 件下装 + 1 件上装，或 1 件全身套装）';
      }
      return ' · 单图：1 件下装 + 1 件上装（或 1 件全身套装）';
    },
    canSubmit() {
      if (this.submitting) return false;
      if (this.selectedItemIds.length === 0 || this.selectedItemIds.length > this.maxItems) return false;
      if (this.creditsBalance < this.requiredCredits) return false;  // v5：按模式所需 credits 校验
      return !!this.selectedModel;
    },
    finalImageUrl() {
      if (!this.result || !this.result.resultUrls || this.result.resultUrls.length === 0) return '';
      return this.result.resultUrls[this.result.resultUrls.length - 1];
    },
    canRate() {
      return this.result && this.result.status === 'SUCCESS' && !this.result.starRating;
    },
    canPublish() {
      return this.result && this.result.status === 'SUCCESS' && !this.result.publishedItemId;
    },
    publishItemOptions() {
      if (!this.result || !this.result.itemIds) return [];
      // 把已选商品的 id+name+category 映射出来供发布选择
      return this.selectedItems
        .filter(it => this.result.itemIds.indexOf(it.id) >= 0)
        .map(it => ({ itemId: it.id, name: it.name, category: it.category }));
    },
  },
  mounted() {
    this.loadModels();
    this.loadCredits();  // v3.2：加载 credits 余额
  },
  methods: {
    formatMoney(val) { return ZM.formatMoney(val); },
    genderText(g) {
      const m = { male: '男', female: '女' };
      return m[g] || '-';
    },
    skinToneText(s) {
      const m = { fair: '白皙', wheat: '小麦', dark: '深色' };
      return m[s] || '-';
    },
    goTasks() { this.$root.currentMenu = 'ai-model-tasks'; },
    goSystemImages() { this.$root.currentMenu = 'ai-model-system-images'; },
    // v3.2：加载 credits 余额 + 钱包余额 + 首充标记
    // （商家维度 shopId=userId，与 AI 随心搭共享配额池）
    loadCredits() {
      const userId = this.userId;
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

    // ===== 商品选择 =====
    openItemPicker() {
      this.itemPickerVisible = true;
      this.itemCurrentPage = 1;
      this.loadItems();
    },
    loadItems() {
      this.itemLoading = true;
      // onlyMine=true 强制只查当前商家自己的商品（AI 模特生成只能选本店铺商品）
      const params = { page: this.itemCurrentPage, size: this.itemPageSize, status: 1, onlyMine: true };
      if (this.itemSearch.name) params.name = this.itemSearch.name;
      ZM.http.get('/items/admin/page', { params }).then(res => {
        this.itemLoading = false;
        // ZM.http 拦截器已 res => res.data，res 即响应体
        if (res && res.list) {
          this.itemTableData = res.list;
          this.itemTotal = res.total || 0;
        } else if (Array.isArray(res)) {
          this.itemTableData = res;
          this.itemTotal = res.length;
        }
        // 还原已选中状态
        this.$nextTick(() => {
          if (this.$refs.itemTable) {
            this.itemTableData.forEach(row => {
              if (this.selectedItemIds.indexOf(row.id) >= 0) {
                this.$refs.itemTable.toggleRowSelection(row, true);
              }
            });
          }
        });
      }).catch(() => { this.itemLoading = false; });
    },
    canSelectItem(row) {
      // 已选 + 当前行的总数不超过当前模式上限（maxItems：single/multi_pose=3，multi_outfit=4）
      if (this.tempSelectedItems.indexOf(row.id) >= 0) return true;
      return this.tempSelectedItems.length < this.maxItems;
    },
    onItemSelectionChange(rows) {
      this.tempSelectedItems = rows.map(r => r.id);
    },
    confirmItemPicker() {
      // 把选中的行数据同步到 selectedItems
      const selectedRows = this.itemTableData.filter(r => this.tempSelectedItems.indexOf(r.id) >= 0);
      this.selectedItems = selectedRows.map(r => ({
        id: r.id, name: r.name, image: r.image, category: r.category, price: r.price,
      }));
      this.selectedItemIds = this.selectedItems.map(r => r.id);
      this.itemPickerVisible = false;
    },
    removeItem(id) {
      this.selectedItems = this.selectedItems.filter(it => it.id !== id);
      this.selectedItemIds = this.selectedItems.map(it => it.id);
    },

    // ===== 模特图选择 =====
    loadModels() {
      this.modelLoading = true;
      const params = { pageNo: this.modelCurrentPage, pageSize: this.modelPageSize };
      if (this.modelFilter.gender) params.gender = this.modelFilter.gender;
      if (this.modelFilter.skinTone) params.skinTone = this.modelFilter.skinTone;
      ZM.http.get('/items/admin/ai-model/system-images', { params }).then(res => {
        this.modelLoading = false;
        if (res && res.list) {
          this.models = res.list;
          this.modelTotal = res.total || 0;
        } else if (Array.isArray(res)) {
          this.models = res;
          this.modelTotal = res.length;
        }
      }).catch(() => { this.modelLoading = false; });
    },
    resetModelFilter() {
      this.modelFilter = { gender: '', skinTone: '' };
      this.modelCurrentPage = 1;
      this.loadModels();
    },
    selectModel(m) { this.selectedModel = m; },

    // v5：切换生成模式时，校验已选商品数量是否超过新模式上限
    // 例如从 multi_outfit（最多 4 件）切换到 single（最多 3 件），需移除多选的商品
    handleModeChange(newMode) {
      const newMax = newMode === 'multi_outfit' ? 4 : 3;
      if (this.selectedItems.length > newMax) {
        this.$message.warning(`已切换到 "${this.modeLabel(newMode)}" 模式，最多可选 ${newMax} 件商品，已自动移除多余商品`);
        this.selectedItems = this.selectedItems.slice(0, newMax);
        this.selectedItemIds = this.selectedItems.map(it => it.id);
      }
      // 切换模式时清空之前的结果展示（不同模式结果结构不同）
      if (this.result || this.failed) {
        this.resetResult();
      }
    },
    handlePoseCountChange() {
      // 姿势数量变化不影响已选商品，仅触发 credits 重新计算（computed 自动响应）
    },
    modeLabel(mode) {
      const m = { single: '单图', multi_pose: '多姿势', multi_outfit: '多换装' };
      return m[mode] || mode;
    },

    // ===== 提交生成（异步模式：提交即返回，不阻塞页面） =====
    submitGenerate() {
      if (!this.canSubmit) return;
      // v5：本地预检 credits 余额（按模式所需 credits）
      if (this.creditsBalance < this.requiredCredits) {
        this.$message.warning(`Credits 余额不足，当前模式需 ${this.requiredCredits} credits，请先充值`);
        this.showRechargeDialog = true;
        return;
      }
      this.submitting = true;
      this.result = null;
      this.failed = false;

      const body = {
        itemIds: this.selectedItemIds,
        modelImageId: this.selectedModel.id,
        generationMode: this.generationMode,
      };
      // v5：多姿势模式需传 poseCount
      if (this.generationMode === 'multi_pose') {
        body.poseCount = this.poseCount;
      }
      ZM.http.post('/items/admin/ai-model/generate', body).then(res => {
        this.submitting = false;
        const taskId = res && res.taskId;
        if (!taskId) {
          this.$message.error('生成任务创建失败');
          return;
        }
        const queuePos = res.queuePosition;
        const hint = (queuePos && queuePos > 0)
          ? `任务已提交，排队中（前面还有 ${queuePos} 个任务）`
          : '任务已提交，后台生成中';
        this.$notify({
          title: '提交成功',
          message: hint + `，taskId=${taskId.substring(0, 8)}...`,
          type: 'success',
          duration: 4000,
        });
        // 询问是否前往任务列表查看进度
        this.$confirm(`${hint}。<br><br>是否立即前往任务列表查看进度？`, '任务已提交', {
          confirmButtonText: '前往任务列表',
          cancelButtonText: '留在此页继续',
          type: 'success',
          dangerouslyUseHTMLString: true,
        }).then(() => {
          this.goTasks();
        }).catch(() => {
          // 留在生成页，重置选商品和模特图方便继续提交下一个
          this.resetSelections();
        });
      }).catch(err => {
        this.submitting = false;
        const status = err.response && err.response.status;
        const data = err.response && err.response.data || {};
        if (status === 400) {
          // v5：多图模式的品类校验失败可能也走 400
          this.$message.error(data.msg || data.detail || '商品数量、品类组合或模特图 ID 不合法');
        } else if (status === 403) {
          // v3.2：区分权限失败和 credits 不足
          const msg = data.msg || data.detail || '';
          if (msg.indexOf('credits') >= 0 || msg.indexOf('余额') >= 0) {
            this.$message.error('Credits 余额不足，请先充值');
            this.loadCredits();  // 刷新本地余额
            this.showRechargeDialog = true;  // 弹出充值对话框
          } else {
            this.$message.error(msg || '无权操作这些商品（必须本店铺商品）');
          }
        } else {
          this.$message.error(data.msg || data.detail || data.message || '提交失败');
        }
      });
    },
    // 提交成功后留在生成页时，重置选商品和模特图，方便继续提交下一个任务
    resetSelections() {
      this.selectedItems = [];
      this.selectedModel = null;
    },
    resetResult() {
      this.result = null;
      this.failed = false;
      this.errorMsg = '';
    },

    // ===== 评分/发布/拒绝回调 =====
    onRated(res) {
      if (this.result) {
        this.result.starRating = res.starRating;
        this.result.savedToPool = res.savedToPool;
      }
      this.showRatingDialog = false;
      // 评分完成后自动弹发布对话框
      if (this.result && !this.result.publishedItemId) {
        this.$nextTick(() => { this.showPublishDialog = true; });
      }
    },
    onPublished(res) {
      if (this.result) this.result.publishedItemId = res.itemId;
      this.showPublishDialog = false;
      this.$notify({
        title: '发布成功',
        message: `模特图已替换商品 ${res.itemId} 的主图`,
        type: 'success', duration: 3000,
      });
    },
    onPublishReject() {
      // "暂不发布" → 切到拒绝原因对话框
      this.showPublishDialog = false;
      this.$nextTick(() => { this.showRejectDialog = true; });
    },
    onRejectSubmitted(res) {
      this.showRejectDialog = false;
      // 致歉引导跳转动作（res.action 由 reject-dialog 致歉对话框按钮触发）
      if (res && res.action) {
        if (res.action === 'regenerate') {
          this.resetResult();
          this.selectedItems = [];
          this.selectedItemIds = [];
          this.selectedModel = null;
        } else if (res.action === 'system-pool') {
          this.goSystemImages();
        } else if (res.action === 'upload-model') {
          this.goSystemImages();
        } else if (res.action === 'customer-service') {
          this.$message.info('客服功能开发中，请联系 platform-support@zmall.com');
        }
        return;
      }
      // 普通提交：同步本地 rejectReason，避免按钮仍显示导致重复提交（后端 409）
      if (this.result && res && !res.action) {
        this.result.rejectReason = res.rejectReason || this.result.rejectReason;
      }
    },
  },
});
