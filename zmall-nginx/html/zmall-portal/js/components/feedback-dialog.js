/* ============================================================
 * FeedbackDialog 多轮反馈对话框组件（v3.1 P2）
 *
 * 用法：
 *   <feedback-dialog :show="showFeedbackDialog"
 *                   :task-id="taskId"
 *                   :outfits="outfits"
 *                   :round="currentRound"
 *                   :max-rounds="3"
 *                   @close="showFeedbackDialog = false"
 *                   @submitted="onFeedbackSubmitted">
 *   </feedback-dialog>
 *
 * 对应后端接口：POST /api/v1/outfit/agent/feedback
 * 每轮扣 credits，同会话最多 3 轮（首轮 + 2 轮反馈）
 *
 * 反馈字段：
 *   - feedback: 必填，1-200 字自然语言
 *   - outfitIndex: 可选 0-2，点哪换哪时传
 *   - itemIndex: 可选 0-5，点哪换哪时传
 *   - dislikeColors: 可选，多选累积
 *   - wantStyleTags: 可选，多选追加
 *   - note: 可选 ≤200 字，P2 ReAct
 * ============================================================ */
Vue.component('feedback-dialog', {
  props: {
    show: { type: Boolean, default: false },
    taskId: { type: String, default: '' },
    outfits: { type: Array, default: () => [] },
    round: { type: Number, default: 1 },         // 当前轮次（1 = 首轮）
    maxRounds: { type: Number, default: 3 },
    // 点哪换哪预填：从外部点击单品"换这个"按钮触发时传入
    presetOutfitIndex: { type: Number, default: null },
    presetItemIndex: { type: Number, default: null },
  },
  data() {
    return {
      feedback: '',
      outfitIndex: null,        // null = 不指定，整体调整
      itemIndex: null,
      dislikeColors: [],
      dislikeItemIds: [],       // 本轮不喜欢的商品 ID（仅本轮生效）
      retryVtonItemIds: [],     // 本轮不还原的商品 ID（商品OK，VTON效果差，需重新换装）
      wantStyleTags: [],
      note: '',
      submitting: false,
      colorOptions: [
        { value: '黑色', label: '黑色' }, { value: '白色', label: '白色' },
        { value: '红色', label: '红色' }, { value: '蓝色', label: '蓝色' },
        { value: '灰色', label: '灰色' }, { value: '卡其', label: '卡其' },
        { value: '绿色', label: '绿色' }, { value: '黄色', label: '黄色' },
        { value: '粉色', label: '粉色' }, { value: '紫色', label: '紫色' },
      ],
      styleOptions: ['通勤', '休闲', '约会', '运动', '商务', '街头', '复古', '欧美', '亚洲', '清新'],
    };
  },
  computed: {
    canSubmit() {
      if (this.submitting) return false;
      if (this.round >= this.maxRounds) return false;
      return this.feedback.trim().length > 0;
    },
    remainingRounds() {
      return this.maxRounds - this.round;
    },
    // 是否为"点哪换哪"模式
    isPickMode() {
      return this.outfitIndex !== null && this.itemIndex !== null;
    },
    pickHint() {
      if (!this.isPickMode) return '';
      const o = this.outfits[this.outfitIndex];
      if (!o || !o.items) return '';
      const it = o.items[this.itemIndex];
      if (!it) return '';
      return `已选：搭配 ${this.outfitIndex + 1} 的「${it.name}」`;
    },
  },
  watch: {
    show(val) {
      if (val) {
        // 重置内部状态（保留 dislikeColors 跨轮累积由外部管理）
        this.feedback = '';
        this.note = '';
        this.wantStyleTags = [];
        this.dislikeItemIds = [];
        this.retryVtonItemIds = [];
        // 应用预填
        if (this.presetOutfitIndex !== null) {
          this.outfitIndex = this.presetOutfitIndex;
          this.itemIndex = this.presetItemIndex;
        } else {
          this.outfitIndex = null;
          this.itemIndex = null;
        }
      }
    },
  },
  methods: {
    toggleColor(c) {
      const i = this.dislikeColors.indexOf(c);
      if (i >= 0) this.dislikeColors.splice(i, 1);
      else this.dislikeColors.push(c);
    },
    toggleStyle(s) {
      const i = this.wantStyleTags.indexOf(s);
      if (i >= 0) this.wantStyleTags.splice(i, 1);
      else this.wantStyleTags.push(s);
    },
    // 点击 outfits 中的某个单品"换这个"
    pickItem(oIdx, iIdx) {
      this.outfitIndex = oIdx;
      this.itemIndex = iIdx;
    },
    clearPick() {
      this.outfitIndex = null;
      this.itemIndex = null;
    },
    toggleDislikeItem(itemId) {
      const i = this.dislikeItemIds.indexOf(itemId);
      if (i >= 0) this.dislikeItemIds.splice(i, 1);
      else this.dislikeItemIds.push(itemId);
    },
    toggleRetryVtonItem(itemId) {
      const i = this.retryVtonItemIds.indexOf(itemId);
      if (i >= 0) this.retryVtonItemIds.splice(i, 1);
      else this.retryVtonItemIds.push(itemId);
    },
    async submit() {
      if (!this.canSubmit) return;
      this.submitting = true;
      try {
        const body = {
          taskId: this.taskId,
          feedback: this.feedback.trim(),
          outfitIndex: this.outfitIndex !== null ? this.outfitIndex : null,
          itemIndex: this.itemIndex !== null ? this.itemIndex : null,
          dislikeColors: this.dislikeColors.length ? this.dislikeColors : null,
          dislikeItemIds: this.dislikeItemIds.length ? this.dislikeItemIds : null,
          retryVtonItemIds: this.retryVtonItemIds.length ? this.retryVtonItemIds : null,
          wantStyleTags: this.wantStyleTags.length ? this.wantStyleTags : null,
          note: this.note.trim() || null,
        };
        const res = await axios.post('/v1/outfit/agent/feedback', body, { timeout: 60000 });

        // 反馈提交成功后，把当前搭配标记为"不满意"写入 DB（accepted=0, action=rejected）
        // 这样搭配历史中会保留这条不满意记录，且不影响新一轮 VTON 生成
        try {
          const outfit = (this.outfits && this.outfits[0]) || {};
          const outfitIdx = this.outfitIndex !== null ? this.outfitIndex : 0;
          const markedOutfit = (this.outfits && this.outfits[outfitIdx]) || outfit;
          await axios.post('/items/outfit/records', {
            taskId: this.taskId,
            outfitIndex: outfitIdx,
            outfitJson: JSON.stringify(markedOutfit),
            vtonResultUrl: markedOutfit.resultUrl || '',
            acceptedAction: 'rejected',
            accepted: 0,
          });
        } catch (e) {
          // DB 标记失败不阻断反馈流程（主流程已成功）
          console.warn('[feedback] 标记不满意到 DB 失败:', e);
        }

        // 通知父组件：反馈已提交，新一轮任务 taskId 不变（同会话内）
        this.$emit('submitted', { taskId: this.taskId, msg: res.msg });
        // 累积不喜欢颜色到 localStorage（跨轮次）
        this.persistDislikeColors();
        this.$emit('close');
      } catch (err) {
        const status = err.response && err.response.status;
        const data = err.response && err.response.data || {};
        if (status === 403) {
          util.toast(data.detail || data.msg || '反馈轮次已达上限', 'warning');
        } else if (status === 404) {
          util.toast(data.detail || '任务已过期', 'error');
        } else if (status === 409) {
          util.toast(data.detail || '任务已完结，无法反馈', 'warning');
        } else if (status === 429) {
          util.toast(data.detail || '上一条反馈还在处理中', 'warning');
        } else {
          util.toast(data.msg || data.detail || '反馈提交失败', 'error');
        }
      } finally {
        this.submitting = false;
      }
    },
    persistDislikeColors() {
      // P2 修复：用当前 dislikeColors 直接覆盖 prefs.dislikeColors（本轮状态即最新偏好），取消勾选才能生效
      try {
        const prefs = util.store.get('outfit_user_prefs') || {};
        prefs.dislikeColors = [...this.dislikeColors];
        util.store.set('outfit_user_prefs', prefs);
      } catch (e) {}
    },
    loadDislikeColors() {
      // 进入对话框时从 localStorage 回显之前累积的不喜欢颜色
      try {
        const prefs = util.store.get('outfit_user_prefs');
        if (prefs && prefs.dislikeColors) {
          this.dislikeColors = [...prefs.dislikeColors];
        }
      } catch (e) {}
    },
  },
  template: `
    <div class="modal-mask" v-if="show" @click.self="$emit('close')">
      <div class="modal-box" style="max-width:640px;">
        <h3>🤔 多轮反馈调整</h3>
        <div class="modal-info">
          <p style="background:#fff8e1;padding:8px 12px;border-radius:4px;font-size:13px;color:#666;">
            💡 每轮反馈需扣 credits，同会话内最多 {{ maxRounds }} 轮（当前第 {{ round }} 轮，剩余 {{ remainingRounds }} 轮）<br>
            📸 当前效果图已永久保存到搭配历史，重新生成不会覆盖原图。
          </p>
          <p v-if="pickHint" style="background:#fef0f0;padding:8px 12px;border-radius:4px;font-size:13px;color:#e54346;">
            🎯 {{ pickHint }}
            <button class="btn-link" @click="clearPick" style="margin-left:8px;">取消定点</button>
          </p>
        </div>

        <!-- 自然语言反馈 -->
        <div class="form-group">
          <label class="form-label">反馈内容 <span class="required">*</span></label>
          <textarea v-model="feedback" class="form-textarea" maxlength="200"
                    placeholder="如：不喜欢蓝色，希望换休闲风；或描述具体调整想法..."></textarea>
          <div class="form-hint">{{ feedback.length }} / 200 字</div>
        </div>

        <!-- 点哪换哪 + 不喜欢某件 -->
        <div class="form-group" v-if="outfits.length > 0 && outfitIndex === null">
          <label class="form-label">单品操作 <span class="ai-text-muted">（对比商品原图与效果图，选择反馈类型）</span></label>
          <div v-for="(o, oIdx) in outfits" :key="oIdx" style="margin-bottom:12px;padding:8px;background:#fafafa;border-radius:4px;">
            <div style="font-size:13px;color:#666;margin-bottom:8px;">搭配 {{ oIdx + 1 }}</div>
            <div v-for="(it, iIdx) in o.items" :key="iIdx"
                 style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #eee;">
              <!-- 商品原图缩略图 -->
              <img v-if="it.image" :src="it.image" :alt="it.name"
                   style="width:40px;height:40px;object-fit:cover;border-radius:4px;border:1px solid #ddd;cursor:zoom-in;"
                   @click="$emit('preview-photo', it.image)"/>
              <div v-else style="width:40px;height:40px;background:#f0f0f0;display:flex;align-items:center;justify-content:center;border-radius:4px;color:#999;font-size:10px;">无图</div>
              <!-- 商品名称 + 类目 -->
              <div style="flex:1;min-width:0;">
                <div style="font-size:13px;color:#333;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ it.name }}</div>
                <div style="font-size:11px;color:#999;">{{ it.category || '-' }} · {{ it.color || '-' }}</div>
              </div>
              <!-- 三个反馈按钮 -->
              <div style="display:flex;gap:4px;flex-shrink:0;">
                <button class="chip" style="padding:3px 8px;font-size:11px;"
                        @click="pickItem(oIdx, iIdx)" title="换一件类似的商品">🔄 换</button>
                <button v-if="it.itemId"
                        class="chip" style="padding:3px 8px;font-size:11px;"
                        :class="{active: retryVtonItemIds.indexOf(it.itemId) >= 0}"
                        @click="toggleRetryVtonItem(it.itemId)" title="商品没问题，但AI生成效果差，重新换装">🔁 不还原</button>
                <button v-if="it.itemId"
                        class="chip" style="padding:3px 8px;font-size:11px;"
                        :class="{active: dislikeItemIds.indexOf(it.itemId) >= 0}"
                        @click="toggleDislikeItem(it.itemId)" title="不喜欢这件商品，以后别推">👎 不喜欢</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 不喜欢的颜色（跨轮累积） -->
        <div class="form-group">
          <label class="form-label">不喜欢的颜色 <span class="ai-text-muted">（多选，跨轮累积）</span></label>
          <div class="chip-group">
            <span v-for="c in colorOptions" :key="c.value"
                  class="chip" :class="{active: dislikeColors.indexOf(c.value) >= 0}"
                  @click="toggleColor(c.value)">{{ c.label }}</span>
          </div>
        </div>

        <!-- 想要追加的风格 -->
        <div class="form-group">
          <label class="form-label">想要追加的风格 <span class="ai-text-muted">（多选，本轮生效）</span></label>
          <div class="chip-group">
            <span v-for="s in styleOptions" :key="s"
                  class="chip" :class="{active: wantStyleTags.indexOf(s) >= 0}"
                  @click="toggleStyle(s)">{{ s }}</span>
          </div>
        </div>

        <!-- 自然语言备注（P2 ReAct） -->
        <div class="form-group">
          <label class="form-label">补充备注 <span class="ai-text-muted">（选填，≤200 字，触发 ReAct 工具调用）</span></label>
          <textarea v-model="note" class="form-textarea" maxlength="200"
                    placeholder="如：希望显瘦、避免亮色、参考某品牌风格..."></textarea>
        </div>

        <div class="modal-actions">
          <button class="btn-cancel" @click="$emit('close')">取消</button>
          <button class="btn-confirm" :disabled="!canSubmit" @click="submit">
            {{ submitting ? '提交中...' : '提交反馈' }}
          </button>
        </div>
      </div>
    </div>
  `,
  mounted() {
    this.loadDislikeColors();
  },
});
