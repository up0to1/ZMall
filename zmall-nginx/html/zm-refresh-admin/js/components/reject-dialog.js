/* ============================================================
 * AI 模特图拒绝原因对话框 + ≤2★ 致歉引导（v3.1 §15.4 + §15.5）
 *
 * 用法：
 *   <reject-dialog :show="showReject"
 *                  :task-id="currentTaskId"
 *                  :star-rating="lastRating"
 *                  @close="showReject = false"
 *                  @submitted="onRejectSubmitted">
 *   </reject-dialog>
 *
 * 接口：POST /items/admin/ai-model/reject
 * 入参：AiModelRejectDTO { taskId, rejectReason }
 * 返回：AiModelImageFeedbackDTO { awardedCredits, ... }
 *
 * 触发致歉引导条件：starRating ≤ 2 且 拒绝原因已提交
 * ============================================================ */
Vue.component('reject-dialog', {
  template: `
    <div>
      <!-- 拒绝原因对话框 -->
      <el-dialog title="🤔 暂不发布原因" :visible.sync="dialogVisible" width="540px"
                 :close-on-click-modal="false" :show-close="!submitting"
                 @close="onClose" custom-class="reject-dialog">
        <el-form :model="form" :rules="rules" ref="rejectForm" label-width="120px" size="small">
          <el-form-item label="拒绝原因" prop="rejectReason">
            <el-input v-model="form.rejectReason" type="textarea" :rows="5"
                      placeholder="请告诉我们暂不发布的原因，帮助我们持续优化 AI 模特图"
                      maxlength="512" show-word-limit>
            </el-input>
          </el-form-item>
        </el-form>
        <el-alert type="warning" :closable="false" style="margin-top:8px;">
          <template slot="title">
            🎁 详细反馈奖励：拒绝原因 ≥20 字 奖励 1 credit（每日上限 3 次）
            <span v-if="form.rejectReason.length >= 20" style="color:#67c23a;margin-left:8px;">
              ✓ 已达奖励门槛
            </span>
          </template>
        </el-alert>
        <span slot="footer">
          <el-button @click="onClose" :disabled="submitting">取消</el-button>
          <el-button type="primary" @click="submit" :loading="submitting">提交原因</el-button>
        </span>
      </el-dialog>

      <!-- ≤2★ 致歉引导对话框 -->
      <el-dialog title="😔 很抱歉" :visible.sync="apologyVisible" width="540px"
                 :close-on-click-modal="false" :show-close="true"
                 custom-class="apology-dialog">
        <div style="line-height:1.8;color:#555;">
          <p>很抱歉这次的 AI 模特图没能让你满意。</p>
          <p>我们已记录你的反馈<span v-if="lastStarRating > 0">（评分 {{ lastStarRating }}★<span v-if="lastRejectReason">，原因：{{ lastRejectReason.slice(0, 30) }}{{ lastRejectReason.length > 30 ? '...' : '' }}</span>）</span>，会持续优化 AI 生成效果。</p>
          <p style="margin-top:16px;font-weight:bold;color:#333;">你可以：</p>
          <div style="margin-top:8px;">
            <p>① <el-button type="text" @click="goRegenerate">重新选品生成 →</el-button></p>
            <p>② <el-button type="text" @click="goSystemPool">从系统模特图池选其他模特图 →</el-button></p>
            <p>　 <el-button type="text" @click="goUploadModel">自己上传新的模特图 →</el-button></p>
            <p>③ <el-button type="text" @click="goCustomerService">联系客服反馈具体问题 →</el-button></p>
          </div>
        </div>
        <span slot="footer">
          <el-button @click="apologyVisible = false">稍后再说</el-button>
          <el-button type="primary" @click="goRegenerate">重新选品</el-button>
        </span>
      </el-dialog>
    </div>
  `,
  props: {
    show: { type: Boolean, default: false },
    taskId: { type: String, default: '' },
    starRating: { type: Number, default: 0 },  // 之前的评分，用于判断是否触发致歉
  },
  data() {
    return {
      submitting: false,
      form: { rejectReason: '' },
      rules: {
        rejectReason: [
          { required: true, message: '请输入拒绝原因', trigger: 'blur' },
          { max: 512, message: '拒绝原因最长 512 字', trigger: 'blur' }
        ]
      },
      apologyVisible: false,
      lastStarRating: 0,
      lastRejectReason: '',
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
      this.$refs.rejectForm.validate(valid => {
        if (!valid) return;
        this.submitting = true;
        const body = { taskId: this.taskId, rejectReason: this.form.rejectReason.trim() };
        ZM.http.post('/items/admin/ai-model/reject', body)
          .then(res => {
            this.submitting = false;
            // 反馈激励提示
            if (res && res.awardedCredits > 0) {
              this.$notify({
                title: '🎁 反馈奖励',
                message: `奖励 ${res.awardedCredits} credit（感谢详细反馈）`,
                type: 'success', duration: 3000,
              });
            } else {
              this.$message.success('已记录你的反馈，谢谢');
            }
            // 缓存评分和原因用于致歉对话框显示
            this.lastStarRating = this.starRating;
            this.lastRejectReason = this.form.rejectReason;
            this.$emit('submitted', res);
            this.resetForm();
            // 触发致歉引导：评分 ≤2★
            if (this.starRating > 0 && this.starRating <= 2) {
              this.dialogVisible = false;
              this.$nextTick(() => { this.apologyVisible = true; });
            } else {
              this.dialogVisible = false;
            }
          })
          .catch(err => {
            this.submitting = false;
            const status = err.response && err.response.status;
            const data = err.response && err.response.data || {};
            if (status === 409) {
              this.$message.warning('该任务已提交过拒绝原因');
            } else if (status === 404) {
              this.$message.error('任务不存在或已过期');
            } else {
              this.$message.error(data.msg || data.detail || data.message || '提交失败');
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
      this.form.rejectReason = '';
      if (this.$refs.rejectForm) this.$refs.rejectForm.clearValidate();
    },
    // 致歉引导 3 个跳转
    goRegenerate() {
      this.apologyVisible = false;
      this.$emit('submitted', { action: 'regenerate' });
    },
    goSystemPool() {
      this.apologyVisible = false;
      this.$emit('submitted', { action: 'system-pool' });
    },
    goUploadModel() {
      this.apologyVisible = false;
      this.$emit('submitted', { action: 'upload-model' });
    },
    goCustomerService() {
      this.apologyVisible = false;
      this.$emit('submitted', { action: 'customer-service' });
    },
  },
});
