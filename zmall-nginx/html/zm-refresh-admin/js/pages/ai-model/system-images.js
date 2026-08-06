/* ============================================================
 * 系统模特图池管理页（v3.1 §15 + 后端 AiModelController）
 *
 * 接口：
 *   GET    /items/admin/ai-model/system-images            分页列表（gender/skinTone 筛选）
 *   POST   /items/admin/ai-model/system-images            multipart 上传新图
 *   PUT    /items/admin/ai-model/system-images/{id}       修改元信息（仅创建者）
 *   DELETE /items/admin/ai-model/system-images/{id}       软删（仅创建者）
 *
 * 权限：所有商家可查可上传；仅 uploaderUserId == 当前用户 可编辑/删除（后端用 mine 字段标识）
 * ============================================================ */
Vue.component('ai-model-system-images-page', {
  template: `
    <div>
      <div class="page-card">
        <div class="page-header">
          <h3>系统模特图池</h3>
          <div>
            <el-button type="text" icon="el-icon-back" @click="goGenerate">返回生成页</el-button>
            <el-button type="primary" size="small" icon="el-icon-plus" @click="openCreate">上传新模特图</el-button>
          </div>
        </div>

        <el-alert type="info" :closable="false" style="margin-bottom:16px;">
          <template slot="title">
            <strong>说明：</strong>全平台共用的模特图池。所有商家可上传；仅创建者可编辑/删除自己上传的图（含"我的上传"标记）。
            AI 模特任务评分 ≥3★ + saveToPool=true 时自动入池（source=1）。
          </template>
        </el-alert>

        <!-- 搜索栏 -->
        <div class="search-bar">
          <el-select v-model="search.gender" placeholder="性别" size="small" clearable style="width:120px">
            <el-option label="男" value="male"></el-option>
            <el-option label="女" value="female"></el-option>
          </el-select>
          <el-select v-model="search.skinTone" placeholder="肤色" size="small" clearable style="width:120px">
            <el-option label="白皙" value="fair"></el-option>
            <el-option label="小麦" value="wheat"></el-option>
            <el-option label="深色" value="dark"></el-option>
          </el-select>
          <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1;loadList()">搜索</el-button>
          <el-button size="small" @click="resetSearch">重置</el-button>
          <el-checkbox v-model="search.mineOnly" style="margin-left:8px;" @change="currentPage=1;loadList()">仅看我的上传</el-checkbox>
        </div>

        <!-- 列表 -->
        <div v-loading="loading" style="min-height:200px;">
          <div v-if="tableData.length === 0 && !loading" style="color:#999;text-align:center;padding:40px;">
            暂无模特图，点击右上角"上传新模特图"
          </div>
          <div class="model-grid">
            <div v-for="row in tableData" :key="row.id" class="model-card">
              <div class="model-image-wrap">
                <el-image :src="row.imageUrl" fit="cover" :preview-src-list="[row.imageUrl]" style="width:100%;height:240px;">
                  <div slot="error" class="no-image">加载失败</div>
                </el-image>
                <span v-if="row.isDefault" class="badge badge-default">默认</span>
                <span class="badge badge-source" :class="'source-' + row.source">{{ sourceText(row.source) }}</span>
                <span v-if="row.mine" class="badge badge-mine">我的</span>
                <span v-if="!row.isActive" class="badge badge-inactive">已隐藏</span>
              </div>
              <div class="model-info">
                <div class="info-row">
                  <span class="tag">{{ genderText(row.gender) }}</span>
                  <span class="tag">{{ skinToneText(row.skinTone) }}</span>
                  <span v-if="row.ageRange" class="tag">{{ row.ageRange }}</span>
                  <span v-if="row.bodyType" class="tag">{{ bodyTypeText(row.bodyType) }}</span>
                </div>
                <div class="info-row" v-if="row.height || row.weight">
                  <span v-if="row.height" class="meta">身高 {{ row.height }}cm</span>
                  <span v-if="row.weight" class="meta">体重 {{ row.weight }}kg</span>
                </div>
                <div class="info-row" v-if="row.styleTags && row.styleTags.length">
                  <span v-for="t in row.styleTags" :key="t" class="tag tag-style">{{ t }}</span>
                </div>
                <div v-if="row.note" class="note" :title="row.note">{{ row.note }}</div>
                <div class="footer">
                  <span class="meta">ID: {{ row.id }}</span>
                  <div class="ops">
                    <el-tooltip v-if="row.mine" :content="row.isActive ? '点击隐藏（隐藏后其他商家和 AI 随心搭都不可用）' : '点击展示（展示后全平台可用）'" placement="top">
                      <el-switch v-model="row.isActive" :active-value="1" :inactive-value="0"
                                 @change="handleVisibilityChange(row)" active-color="#13ce66" inactive-color="#ff4949">
                      </el-switch>
                    </el-tooltip>
                    <el-button size="mini" @click="openEdit(row)" :disabled="!row.mine">编辑</el-button>
                    <el-button size="mini" type="danger" @click="handleDelete(row)" :disabled="!row.mine">删除</el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div style="margin-top:16px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
          <span style="font-size:13px;color:#606266;">共 {{ total }} 条 / 共 {{ totalPages }} 页，当前第 {{ currentPage }} 页</span>
          <el-pagination background layout="prev, pager, next, jumper" :pager-count="11"
                         :total="total" :page-size="pageSize"
                         :current-page.sync="currentPage" @current-change="loadList">
          </el-pagination>
        </div>
      </div>

      <!-- 上传 / 编辑 对话框 -->
      <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="640px" :close-on-click-modal="false">
        <el-form :model="form" :rules="formRules" ref="form" label-width="100px">
          <el-form-item label="模特图" v-if="!isEdit">
            <el-upload
              ref="uploader"
              class="image-uploader"
              action="/api/items/admin/ai-model/system-images"
              name="file"
              :headers="uploadHeaders"
              :data="uploadData"
              :show-file-list="false"
              :on-success="handleUploadSuccess"
              :on-error="handleUploadError"
              :before-upload="beforeUpload"
              :auto-upload="false"
              :on-change="onFileChange"
              :file-list="fileList"
              accept="image/*">
              <img v-if="previewUrl" :src="previewUrl" class="uploaded-image" style="max-width:200px;max-height:240px;display:block;">
              <el-button v-else size="small" type="primary" icon="el-icon-upload2">选择图片</el-button>
            </el-upload>
            <div style="font-size:12px;color:#909399;margin-top:4px;">
              支持 JPG/PNG/WebP，建议 750×1000，单张 ≤ 5MB；上传后作为系统默认模特图全平台共享
            </div>
          </el-form-item>
          <el-form-item label="当前图" v-else>
            <el-image :src="form.imageUrl" fit="cover" style="width:120px;height:160px;border-radius:4px;"></el-image>
          </el-form-item>
          <el-form-item label="性别" prop="gender">
            <el-radio-group v-model="form.gender">
              <el-radio label="male">男</el-radio>
              <el-radio label="female">女</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="肤色" prop="skinTone">
            <el-radio-group v-model="form.skinTone">
              <el-radio label="fair">白皙</el-radio>
              <el-radio label="wheat">小麦</el-radio>
              <el-radio label="dark">深色</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="身高 (cm)">
            <el-input-number v-model="form.height" :min="140" :max="210" :step="1" style="width:160px"></el-input-number>
          </el-form-item>
          <el-form-item label="体重 (kg)">
            <el-input-number v-model="form.weight" :min="30" :max="150" :step="1" style="width:160px"></el-input-number>
          </el-form-item>
          <el-form-item label="年龄段">
            <el-select v-model="form.ageRange" placeholder="请选择" style="width:160px" clearable>
              <el-option label="18-25" value="18-25"></el-option>
              <el-option label="26-35" value="26-35"></el-option>
              <el-option label="36-45" value="36-45"></el-option>
              <el-option label="46+" value="46+"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="体型">
            <el-select v-model="form.bodyType" placeholder="请选择" style="width:160px" clearable>
              <el-option label="苗条 slim" value="slim"></el-option>
              <el-option label="标准 standard" value="standard"></el-option>
              <el-option label="曲线 curvy" value="curvy"></el-option>
              <el-option label="大码 plus" value="plus"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="风格标签">
            <el-select v-model="form.styleTags" multiple filterable allow-create
                       default-first-option placeholder="可选可输入" style="width:100%">
              <el-option label="通勤" value="通勤"></el-option>
              <el-option label="休闲" value="休闲"></el-option>
              <el-option label="约会" value="约会"></el-option>
              <el-option label="运动" value="运动"></el-option>
              <el-option label="商务" value="商务"></el-option>
              <el-option label="街头" value="街头"></el-option>
              <el-option label="复古" value="复古"></el-option>
              <el-option label="欧美" value="欧美"></el-option>
              <el-option label="亚洲" value="亚洲"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.note" type="textarea" :rows="2" maxlength="50" show-word-limit
                      placeholder="≤50 字，如：站立全身照、白底、干净背景"></el-input>
          </el-form-item>
        </el-form>
        <span slot="footer">
          <el-button @click="dialogVisible = false">取 消</el-button>
          <el-button v-if="!isEdit" type="primary" @click="submitCreate" :loading="submitLoading">上传并创建</el-button>
          <el-button v-else type="primary" @click="submitEdit" :loading="submitLoading">保 存</el-button>
        </span>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      loading: false,
      tableData: [],
      total: 0,
      totalPages: 1,
      currentPage: 1,
      pageSize: 12,
      search: { gender: '', skinTone: '', mineOnly: false },

      dialogVisible: false,
      isEdit: false,
      submitLoading: false,
      form: this.emptyForm(),
      formRules: {
        gender: [{ required: true, message: '请选择性别', trigger: 'change' }],
        skinTone: [{ required: true, message: '请选择肤色', trigger: 'change' }],
      },

      // 上传相关
      fileList: [],
      pendingFile: null,
      previewUrl: '',
    };
  },
  computed: {
    dialogTitle() { return this.isEdit ? '编辑模特图元信息' : '上传新模特图'; },
    uploadHeaders() {
      return { authorization: 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') };
    },
    uploadData() {
      // el-upload 的 data 字段：multipart 表单附加字段
      // 后端强制 isDefault=true（商家上传的均为系统默认模特图），前端无需传 isDefault
      const d = {
        gender: this.form.gender || '',
        skinTone: this.form.skinTone || '',
        height: this.form.height || '',
        weight: this.form.weight || '',
        ageRange: this.form.ageRange || '',
        bodyType: this.form.bodyType || '',
        note: this.form.note || '',
      };
      if (this.form.styleTags && this.form.styleTags.length) {
        // 后端接收 List<String> styleTags，多次同 key 提交
        d.styleTags = this.form.styleTags;
      }
      return d;
    },
  },
  mounted() {
    this.loadList();
  },
  methods: {
    emptyForm() {
      return {
        id: null, imageUrl: '',
        gender: '', skinTone: '',
        height: null, weight: null,
        ageRange: '', bodyType: '',
        styleTags: [], note: '',
      };
    },
    genderText(g) { return { male: '男', female: '女' }[g] || '-'; },
    skinToneText(s) { return { fair: '白皙', wheat: '小麦', dark: '深色' }[s] || '-'; },
    bodyTypeText(b) {
      return { slim: '苗条', standard: '标准', curvy: '曲线', plus: '大码' }[b] || '-';
    },
    sourceText(s) {
      const m = { 0: '商家上传', 1: 'AI任务入池', 2: '平台运营', 3: 'AI自动生成' };
      return m[s] !== undefined ? m[s] : '未知';
    },
    goGenerate() { this.$root.currentMenu = 'ai-model-generate'; },

    loadList() {
      this.loading = true;
      const params = { pageNo: this.currentPage, pageSize: this.pageSize };
      if (this.search.gender) params.gender = this.search.gender;
      if (this.search.skinTone) params.skinTone = this.search.skinTone;
      ZM.http.get('/items/admin/ai-model/system-images', { params }).then(res => {
        this.loading = false;
        let list = [], total = 0;
        if (res && res.list) { list = res.list; total = res.total || 0; }
        else if (Array.isArray(res)) { list = res; total = res.length; }
        // 客户端"仅看我的"过滤（后端可能未支持 mineOnly）
        if (this.search.mineOnly) {
          list = list.filter(it => it.mine);
          total = list.length;
        }
        this.tableData = list;
        this.total = total;
        this.totalPages = Math.max(1, Math.ceil(total / this.pageSize));
      }).catch(() => { this.loading = false; });
    },
    resetSearch() {
      this.search = { gender: '', skinTone: '', mineOnly: false };
      this.currentPage = 1;
      this.loadList();
    },

    // ===== 上传/新建 =====
    openCreate() {
      this.isEdit = false;
      this.form = this.emptyForm();
      this.pendingFile = null;
      // 释放上一个 blob URL 避免内存泄漏
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl);
      }
      this.previewUrl = '';
      this.fileList = [];
      this.dialogVisible = true;
      this.$nextTick(() => { if (this.$refs.form) this.$refs.form.clearValidate(); });
    },
    onFileChange(file) {
      // 单文件替换
      this.fileList = [file];
      this.pendingFile = file.raw;
      // auto-upload=false 模式下 file.url 可能为空，需用 createObjectURL 生成本地预览
      // 释放上一个 blob URL 避免内存泄漏（file.url 也是 blob: 形式，需要先释放旧的）
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl);
      }
      if (file.url) {
        this.previewUrl = file.url;
      } else if (file.raw) {
        this.previewUrl = URL.createObjectURL(file.raw);
      } else {
        this.previewUrl = '';
      }
    },
    beforeUpload(file) {
      const okType = ['image/jpeg', 'image/png', 'image/webp'].indexOf(file.type) >= 0;
      if (!okType) { this.$message.error('仅支持 JPG/PNG/WebP'); return false; }
      if (file.size > 5 * 1024 * 1024) { this.$message.error('图片大小不超过 5MB'); return false; }
      return true;
    },
    handleUploadSuccess(res) {
      this.submitLoading = false;
      if (!res) {
        this.$message.error('上传失败：服务端无响应');
        return;
      }
      this.$message.success('模特图上传成功');
      // 上传成功后释放本地预览的 blob URL
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl);
      }
      this.previewUrl = '';
      this.pendingFile = null;
      this.fileList = [];
      this.dialogVisible = false;
      this.loadList();
    },
    handleUploadError(err) {
      this.submitLoading = false;
      let msg = '上传失败';
      let status = null;
      try {
        if (err && err.response) {
          // axios 错误格式
          status = err.response.status;
          const data = err.response.data || {};
          if (data.msg || data.message) msg = data.msg || data.message;
        } else if (err && err.message) {
          // el-upload 错误格式（message 为 JSON 字符串）
          const data = JSON.parse(err.message);
          if (data && (data.msg || data.message)) msg = data.msg || data.message;
          if (data && data.status) status = data.status;
        }
      } catch (e) {}
      if (status === 403) msg = '无权上传';
      else if (status === 413) msg = '图片过大，请压缩后上传';
      this.$message.error(msg);
    },
    submitCreate() {
      if (!this.pendingFile) {
        this.$message.warning('请先选择图片');
        return;
      }
      this.$refs.form.validate(valid => {
        if (!valid) return;
        this.submitLoading = true;
        // 直接使用 manualUpload：el-upload 内部 FormData 对 styleTags 数组
        // 会调用 toString() 拼成逗号字符串，与后端 List<String> 不匹配；
        // manualUpload 手动遍历数组逐项 append，符合 multipart 多值规范
        this.manualUpload();
      });
    },
    manualUpload() {
      // 兜底：用 FormData + axios 直接上传
      const fd = new FormData();
      fd.append('file', this.pendingFile);
      Object.keys(this.uploadData).forEach(k => {
        const v = this.uploadData[k];
        if (Array.isArray(v)) v.forEach(it => fd.append(k, it));
        else if (v !== '' && v !== null && v !== undefined) fd.append(k, v);
      });
      axios.post('/api/items/admin/ai-model/system-images', fd, {
        headers: { authorization: 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') },
      }).then(res => {
        this.handleUploadSuccess(res.data);
      }).catch(err => {
        this.handleUploadError(err);
      });
    },

    // ===== 编辑 =====
    openEdit(row) {
      this.isEdit = true;
      // 切到编辑模式时，释放新建模式可能遗留的 blob URL
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl);
      }
      this.previewUrl = '';
      this.pendingFile = null;
      this.fileList = [];
      this.form = {
        id: row.id,
        imageUrl: row.imageUrl,
        gender: row.gender || '',
        skinTone: row.skinTone || '',
        height: row.height || null,
        weight: row.weight || null,
        ageRange: row.ageRange || '',
        bodyType: row.bodyType || '',
        styleTags: Array.isArray(row.styleTags) ? [...row.styleTags] : [],
        note: row.note || '',
      };
      this.dialogVisible = true;
      this.$nextTick(() => { if (this.$refs.form) this.$refs.form.clearValidate(); });
    },
    submitEdit() {
      this.$refs.form.validate(valid => {
        if (!valid) return;
        this.submitLoading = true;
        const body = {
          gender: this.form.gender,
          skinTone: this.form.skinTone,
          height: this.form.height,
          weight: this.form.weight,
          ageRange: this.form.ageRange,
          bodyType: this.form.bodyType,
          styleTags: this.form.styleTags,
          note: this.form.note,
        };
        ZM.http.put('/items/admin/ai-model/system-images/' + this.form.id, body).then(() => {
          this.submitLoading = false;
          this.$message.success('已保存');
          this.dialogVisible = false;
          this.loadList();
        }).catch(err => {
          this.submitLoading = false;
          const status = err.response && err.response.status;
          const data = err.response && err.response.data || {};
          if (status === 403) this.$message.error('仅创建者可修改');
          else if (status === 404) this.$message.error('模特图不存在或已删除');
          else this.$message.error(data.msg || data.message || '保存失败');
        });
      });
    },

    // ===== 展示/不展示切换（仅创建者可操作） =====
    // 调用专用 visibility 端点：PUT /system-images/{id}/visibility?isActive=X
    handleVisibilityChange(row) {
      const target = row.isActive ? '展示' : '隐藏';
      ZM.http.put('/items/admin/ai-model/system-images/' + row.id + '/visibility?isActive=' + row.isActive).then(() => {
        this.$message.success(`已${target}（ID ${row.id}）`);
      }).catch(err => {
        // 失败时回滚开关状态
        row.isActive = row.isActive ? 0 : 1;
        const status = err.response && err.response.status;
        const data = err.response && err.response.data || {};
        if (status === 403) this.$message.error('仅创建者可修改展示状态');
        else if (status === 404) this.$message.error('模特图不存在或已删除');
        else this.$message.error(data.msg || data.message || `${target}失败`);
      });
    },

    // ===== 删除（软删） =====
    handleDelete(row) {
      this.$confirm(`确认删除模特图 ID ${row.id}？删除后不可恢复`, '确认删除', {
        type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
      }).then(() => {
        ZM.http.delete('/items/admin/ai-model/system-images/' + row.id).then(() => {
          this.$message.success('已删除');
          if (this.tableData.length === 1 && this.currentPage > 1) this.currentPage--;
          this.loadList();
        }).catch(err => {
          const status = err.response && err.response.status;
          const data = err.response && err.response.data || {};
          if (status === 403) this.$message.error('仅创建者可删除');
          else if (status === 404) this.$message.error('模特图不存在或已删除');
          else this.$message.error(data.msg || data.message || '删除失败');
        });
      }).catch(() => {});
    },
  },
});
