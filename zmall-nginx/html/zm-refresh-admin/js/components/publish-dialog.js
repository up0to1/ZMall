/* ============================================================
 * AI 模特图发布对话框（v3.1 §15.3）
 *
 * 用法：
 *   <publish-dialog :show="showPublish"
 *                   :task-id="currentTaskId"
 *                   :image-url="finalImageUrl"
 *                   :items="itemOptions"
 *                   :star-rating="lastRating"
 *                   @close="showPublish = false"
 *                   @published="onPublished"
 *                   @reject="onReject">
 *   </publish-dialog>
 *
 * 接口：POST /items/admin/ai-model/publish
 * 入参：AiModelPublishDTO { taskId, itemId, imageUrl }
 * 返回：void（HTTP 200 即成功）
 * ============================================================ */
Vue.component('publish-dialog', {
  template: `
    <el-dialog title="📤 发布到商品主图" :visible.sync="dialogVisible" width="600px"
               :close-on-click-modal="false" :show-close="!submitting"
               @close="onClose" custom-class="publish-dialog">
      <div v-if="imageUrl" style="text-align:center;margin-bottom:16px;">
        <img :src="imageUrl" alt="AI 模特图" style="max-width:100%;max-height:240px;border-radius:8px;border:1px solid #eee;"/>
      </div>

      <el-form :model="form" :rules="rules" ref="publishForm" label-width="120px" size="small">
        <el-form-item label="发布到商品" prop="itemId">
          <el-select v-model="form.itemId" placeholder="选择一个商品" style="width:100%" filterable>
            <el-option v-for="it in items" :key="it.itemId"
                       :label="it.name + '（ID: ' + it.itemId + '）'"
                       :value="it.itemId">
              <span style="float:left">{{ it.name }}</span>
              <span style="float:right;color:#8492a6;font-size:12px;">{{ it.category || '-' }} · ID: {{ it.itemId }}</span>
            </el-option>
          </el-select>
          <div style="font-size:12px;color:#909399;margin-top:4px;">
            涉及单品（点击选一个发布，仅替换商品主图）
          </div>
        </el-form-item>
      </el-form>

      <el-alert type="info" :closable="false" style="margin-top:8px;">
        <template slot="title">
          ℹ️ 发布后将替换所选商品的第一张主图，可在商品管理中随时撤换。
          <span v-if="starRating >= 4" style="color:#e6a23c;margin-left:8px;">
            🎁 首次发布 + ≥4★ 评分 奖励 1 credit
          </span>
        </template>
      </el-alert>

      <span slot="footer">
        <el-button @click="onReject" :disabled="submitting">暂不发布</el-button>
        <el-button type="primary" @click="submit" :loading="submitting"
                   :disabled="!form.itemId || !imageUrl">选择发布</el-button>
      </span>
    </el-dialog>
  `,
  props: {
    show: { type: Boolean, default: false },
    taskId: { type: String, default: '' },
    imageUrl: { type: String, default: '' },
    items: { type: Array, default: () => [] },   // [{ itemId, name, category }]
    starRating: { type: Number, default: 0 },     // 评分（决定是否显示首次发布奖励提示）
  },
  data() {
    return {
      submitting: false,
      form: { itemId: null },
      rules: {
        itemId: [{ required: true, message: '请选择商品', trigger: 'change' }]
      },
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
      this.$refs.publishForm.validate(valid => {
        if (!valid) return;
        this.submitting = true;
        const body = {
          taskId: this.taskId,
          itemId: this.form.itemId,
          imageUrl: this.imageUrl,
        };
        ZM.http.post('/items/admin/ai-model/publish', body)
          .then(() => {
            this.submitting = false;
            this.$message.success('已发布到商品主图');
            this.$emit('published', { taskId: this.taskId, itemId: this.form.itemId });
            this.resetForm();
          })
          .catch(err => {
            this.submitting = false;
            const status = err.response && err.response.status;
            const data = err.response && err.response.data || {};
            if (status === 404) {
              this.$message.error('任务或商品不存在');
            } else if (status === 400) {
              this.$message.error(data.msg || data.detail || '图片 URL 或商品 ID 不合法');
            } else if (status === 409) {
              this.$message.warning('该商品已发布过此图');
            } else {
              this.$message.error(data.msg || data.detail || data.message || '发布失败');
            }
          });
      });
    },
    onReject() {
      if (this.submitting) return;
      this.$emit('reject');
      this.resetForm();
    },
    onClose() {
      if (this.submitting) return;
      this.resetForm();
      this.$emit('close');
    },
    resetForm() {
      this.form.itemId = null;
      if (this.$refs.publishForm) this.$refs.publishForm.clearValidate();
    },
  },
});
