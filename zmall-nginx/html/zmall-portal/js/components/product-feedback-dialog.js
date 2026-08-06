/* ============================================================
 * ProductFeedbackDialog 商品驱动模式多轮反馈对话框（v3.2）
 *
 * 用法：
 *   <product-feedback-dialog :show="showFeedbackDialog"
 *                            :task-id="taskId"
 *                            :outfits="outfits"
 *                            :round="round"
 *                            :max-rounds="3"
 *                            :preset-outfit-index="presetOutfitIndex"
 *                            :preset-item-index="presetItemIndex"
 *                            @close="closeFeedback"
 *                            @submitted="onFeedbackSubmitted">
 *   </product-feedback-dialog>
 *
 * 对应后端接口：POST /api/v1/outfit/feedback
 * 不扣 credits，同会话最多 3 轮（首轮 + 2 轮反馈）
 *
 * 与风格驱动 feedback-dialog 的差异：
 *   - 不支持 wantStyleTags（商品驱动无 style_tags 概念）
 *   - 不支持 note ReAct（不触发 Tool calling）
 *   - 主商品 isMain=True 不显示"换这个"按钮（不可替换）
 *
 * 反馈字段：
 *   - feedback: 必填，1-200 字自然语言
 *   - outfitIndex: 可选 0-2，点哪换哪时传
 *   - itemIndex: 可选 0-5，点哪换哪时传
 *   - dislikeColors: 可选，多选累积
 *   - dislikeItemIds: 可选，本轮不喜欢的商品 ID
 * ============================================================ */
Vue.component('product-feedback-dialog', {
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
      submitting: false,
      colorOptions: [
        { value: '黑色', label: '黑色' }, { value: '白色', label: '白色' },
        { value: '红色', label: '红色' }, { value: '蓝色', label: '蓝色' },
        { value: '灰色', label: '灰色' }, { value: '卡其', label: '卡其' },
        { value: '绿色', label: '绿色' }, { value: '黄色', label: '黄色' },
        { value: '粉色', label: '粉色' }, { value: '紫色', label: '紫色' },
      ],
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
        this.dislikeItemIds = [];
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
    // 点击 outfits 中的某个互补单品"换这个"（主商品 isMain=True 不显示此按钮）
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
        };
        await axios.post('/v1/outfit/feedback', body, { timeout: 60000 });
        // 通知父组件：反馈已提交，新一轮任务 taskId 不变（同会话内）
        this.$emit('submitted', { taskId: this.taskId });
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
      try {
        const prefs = util.store.get('outfit_product_prefs') || {};
        prefs.dislikeColors = [...this.dislikeColors];
        util.store.set('outfit_product_prefs', prefs);
      } catch (e) {}
    },
    loadDislikeColors() {
      try {
        const prefs = util.store.get('outfit_product_prefs');
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
            💡 反馈不扣 credits，同会话内最多 {{ maxRounds }} 轮（当前第 {{ round }} 轮，剩余 {{ remainingRounds }} 轮）
          </p>
          <p v-if="pickHint" style="background:#fef0f0;padding:8px 12px;border-radius:4px;font-size:13px;color:#e54346;">
            🎯 {{ pickHint }}
            <button class="btn-link" @click="clearPick" style="margin-left:8px;">取消定点</button>
          </p>
          <p v-if="round === 1" style="background:#e3f2fd;padding:8px 12px;border-radius:4px;font-size:13px;color:#1976d2;">
            🔒 主商品不可替换，仅调整互补商品
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
          <label class="form-label">单品操作 <span class="ai-text-muted">（🔄 换这个 / 👎 不喜欢，下次别推）</span></label>
          <div v-for="(o, oIdx) in outfits" :key="oIdx" style="margin-bottom:8px;padding:8px;background:#fafafa;border-radius:4px;">
            <div style="font-size:13px;color:#666;margin-bottom:4px;">搭配 {{ oIdx + 1 }}</div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <span v-for="(it, iIdx) in o.items" :key="iIdx"
                    style="display:inline-flex;align-items:center;gap:2px;">
                <!-- 主商品 isMain=True 不可替换，只显示标记 -->
                <span v-if="it.isMain" class="chip" style="padding:4px 10px;font-size:12px;background:#ffebee;color:#c62828;">
                  {{ it.name }} 🔒
                </span>
                <template v-else>
                  <button class="chip" style="padding:4px 10px;font-size:12px;"
                          @click="pickItem(oIdx, iIdx)">{{ it.name }} 🔄</button>
                  <button v-if="it.itemId"
                          class="chip" style="padding:4px 6px;font-size:12px;"
                          :class="{active: dislikeItemIds.indexOf(it.itemId) >= 0}"
                          @click="toggleDislikeItem(it.itemId)">👎</button>
                </template>
              </span>
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
