/* ============================================================
 * AI 模特图评分对话框（v3.1 §15.2）
 *
 * 用法：
 *   <rating-dialog :show="showRating"
 *                  :task-id="currentTaskId"
 *                  :final-image-url="finalImageUrl"
 *                  @close="showRating = false"
 *                  @rated="onRated">
 *   </rating-dialog>
 *
 * 接口：POST /items/admin/ai-model/rating
 * 入参：AiModelRatingDTO { taskId, starRating, ratingTags, ratingNote, saveToPool }
 * 返回：AiModelImageFeedbackDTO { awardedCredits, savedToPool, ... }
 * ============================================================ */
Vue.component('rating-dialog', {
  template: `
    <el-dialog title="🎨 AI 模特图评分" :visible.sync="dialogVisible" width="540px"
               :close-on-click-modal="false" :show-close="!submitting"
               @close="onClose" custom-class="rating-dialog">
      <div v-if="finalImageUrl" style="text-align:center;margin-bottom:16px;">
        <img :src="finalImageUrl" alt="AI 模特图" style="max-width:100%;max-height:300px;border-radius:8px;border:1px solid #eee;"/>
      </div>
      <div v-else style="text-align:center;color:#999;padding:20px 0;">
        暂无模特图预览
      </div>

      <el-form :model="form" :rules="rules" ref="ratingForm" label-width="120px" size="small">
        <el-form-item label="整体满意度" prop="starRating">
          <el-rate v-model="form.starRating" :texts="['很差','不满意','一般','满意','很满意']"
                   show-text :colors="['#f56c6c','#e54346','#67c23a']">
          </el-rate>
        </el-form-item>
        <el-form-item label="评分标签">
          <el-select v-model="form.ratingTags" multiple placeholder="可选" style="width:100%">
            <el-option v-for="t in tagOptions" :key="t" :label="t" :value="t"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.ratingNote" type="textarea" :rows="3"
                    placeholder="补充说明（≤256 字）" maxlength="256" show-word-limit>
          </el-input>
        </el-form-item>
        <el-form-item label="入系统模特图池" prop="saveToPool">
          <el-checkbox v-model="form.saveToPool">
            同意将此模特图入系统池
          </el-checkbox>
          <div style="font-size:12px;color:#909399;line-height:1.5;">
            评分 ≥3★ + 勾选 → 自动入系统池（全平台商家可复用）<br/>
            评分 &lt;3★ 或未勾选 → 仅记录反馈<br/>
            <span style="color:#e6a23c;">🎁 评分 ≥4★ + 入池 + 首次发布 奖励 1 credit（每日上限 5 次）</span>
          </div>
        </el-form-item>
      </el-form>

      <span slot="footer">
        <el-button @click="onClose" :disabled="submitting">稍后评分</el-button>
        <el-button type="primary" @click="submit" :loading="submitting">提交评分</el-button>
      </span>
    </el-dialog>
  `,
  props: {
    show: { type: Boolean, default: false },
    taskId: { type: String, default: '' },
    finalImageUrl: { type: String, default: '' },
  },
  data() {
    return {
      submitting: false,
      form: {
        starRating: 0,
        ratingTags: [],
        ratingNote: '',
        saveToPool: true,
      },
      rules: {
        starRating: [
          { required: true, message: '请选择评分', trigger: 'change' },
          { type: 'number', min: 1, max: 5, message: '评分 1-5 星', trigger: 'change' }
        ],
      },
      tagOptions: [
        '姿态自然', '服装还原好', '光影协调', '风格匹配',
        '模特气质佳', '整体专业', '质感好', '比例协调'
      ],
    };
  },
  computed: {
    dialogVisible: {
      get() { return this.show; },
      set(val) { if (!val) this.onClose(); }
    }
  },
  methods: {
    submit() {
      this.$refs.ratingForm.validate(valid => {
        if (!valid) return;
        if (this.form.starRating < 1 || this.form.starRating > 5) {
          this.$message.warning('请选择 1-5 星评分');
          return;
        }
        this.submitting = true;
        const body = {
          taskId: this.taskId,
          starRating: this.form.starRating,
          ratingTags: this.form.ratingTags.length ? this.form.ratingTags : null,
          ratingNote: this.form.ratingNote.trim() || null,
          saveToPool: !!this.form.saveToPool,
        };
        ZM.http.post('/items/admin/ai-model/rating', body)
          .then(res => {
            this.submitting = false;
            // 入池提示
            if (res && res.savedToPool === 1) {
              this.$message.success(`评分 ${res.starRating}★，模特图已入系统池，全平台可复用`);
            } else {
              this.$message.success(`评分 ${res.starRating}★，已记录反馈`);
            }
            // 激励奖励提示
            if (res && res.awardedCredits > 0) {
              setTimeout(() => {
                this.$notify({
                  title: '🎁 评分激励',
                  message: `奖励 ${res.awardedCredits} credit`,
                  type: 'success', duration: 3000,
                });
              }, 800);
            }
            this.$emit('rated', res);
            this.resetForm();
          })
          .catch(err => {
            this.submitting = false;
            const status = err.response && err.response.status;
            const data = err.response && err.response.data || {};
            if (status === 409) {
              this.$message.warning('该任务已评分，无法重复评分');
            } else if (status === 404) {
              this.$message.error('任务不存在或已过期');
            } else {
              this.$message.error(data.msg || data.detail || data.message || '评分失败');
            }
          });
      });
    },
    onClose() {
      if (this.submitting) return;
      this.resetForm();
      this.$emit('close');
    },
    resetForm() {
      this.form.starRating = 0;
      this.form.ratingTags = [];
      this.form.ratingNote = '';
      this.form.saveToPool = true;
      if (this.$refs.ratingForm) this.$refs.ratingForm.clearValidate();
    },
  },
});
