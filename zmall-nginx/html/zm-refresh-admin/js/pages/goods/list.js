// 商品列表页面组件
Vue.component('goods-list-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header">
                <h3>商品列表</h3>
                <el-button type="primary" size="small" icon="el-icon-plus" @click="handleAdd">添加商品</el-button>
            </div>
            <!-- 搜索栏 -->
            <div class="search-bar">
                <el-input v-model="search.name" placeholder="商品名称" size="small" clearable></el-input>
                <el-select v-model="search.status" placeholder="商品状态" size="small" clearable>
                    <el-option label="已上架" :value="1"></el-option>
                    <el-option label="已下架" :value="2"></el-option>
                    <el-option label="已删除" :value="3"></el-option>
                </el-select>
                <el-select v-model="search.itemType" placeholder="商品类型" size="small" clearable>
                    <el-option label="普通商品" :value="1"></el-option>
                    <el-option label="秒杀商品" :value="2"></el-option>
                </el-select>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1;loadList()">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <!-- 表格 -->
            <el-table :data="tableData" border stripe v-loading="loading" style="width:100%">
                <el-table-column prop="id" label="ID" width="70" align="center"></el-table-column>
                <el-table-column label="商品图片" width="90" align="center">
                    <template slot-scope="scope">
                        <el-image :src="getImageUrl(scope.row.image)" style="width:60px;height:60px;" fit="cover" v-if="scope.row.image"></el-image>
                        <span v-else>-</span>
                    </template>
                </el-table-column>
                <el-table-column prop="name" label="商品名称" min-width="180" show-overflow-tooltip></el-table-column>
                <el-table-column prop="category" label="分类" width="100" align="center"></el-table-column>
                <el-table-column label="价格" width="100" align="center">
                    <template slot-scope="scope">&yen;{{formatMoney(scope.row.price)}}</template>
                </el-table-column>
                <el-table-column prop="stock" label="库存" width="80" align="center"></el-table-column>
                <el-table-column label="状态" width="90" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.status===1?'success':scope.row.status===2?'info':'danger'" size="small">
                            {{scope.row.status===1?'已上架':scope.row.status===2?'已下架':'已删除'}}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="类型" width="100" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.itemType===2?'danger':''" size="small" effect="plain">
                            {{scope.row.itemType===2?'秒杀':'普通'}}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="220" align="center" fixed="right">
                    <template slot-scope="scope">
                        <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:center;">
                            <el-button size="mini" @click="handleEdit(scope.row)">编辑</el-button>
                            <el-button size="mini" :type="scope.row.status===1?'warning':'success'" @click="toggleStatus(scope.row)">
                                {{scope.row.status===1?'下架':'上架'}}
                            </el-button>
                            <el-button size="mini" :type="scope.row.itemType===2?'':'danger'" @click="handleSetSeckill(scope.row)">
                                {{scope.row.itemType===2?'秒杀设置':'设为秒杀'}}
                            </el-button>
                            <el-button size="mini" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                        </div>
                    </template>
                </el-table-column>
            </el-table>
            <!-- 分页 -->
            <div style="margin-top:16px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{total}} 条 / 共 {{totalPages}} 页，当前第 {{currentPage}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :pager-count="11" :total="total" :page-size="pageSize" :current-page.sync="currentPage" @current-change="loadList"></el-pagination>
            </div>
        </div>

        <!-- 添加/编辑弹窗 -->
        <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="650px" :close-on-click-modal="false">
            <el-form :model="form" :rules="formRules" ref="form" label-width="100px">
                <el-form-item label="商品名称" prop="name">
                    <el-input v-model="form.name" placeholder="请输入商品名称"></el-input>
                </el-form-item>
                <el-form-item label="商品分类" prop="category">
                    <el-select v-model="form.category" placeholder="请选择分类" style="width:100%">
                        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.name"></el-option>
                    </el-select>
                </el-form-item>
                <el-form-item label="品牌" prop="brand">
                    <el-input v-model="form.brand" placeholder="请输入品牌"></el-input>
                </el-form-item>
                <el-form-item label="价格" prop="price">
                    <el-input-number v-model="form.price" :min="0" :precision="2" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="库存" prop="stock">
                    <el-input-number v-model="form.stock" :min="0" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="商品图片">
                    <div>
                        <el-upload
                            class="image-uploader"
                            action="/api/items/admin/upload"
                            name="file"
                            :headers="uploadHeaders"
                            :show-file-list="false"
                            :on-success="handleUploadSuccess"
                            :on-error="handleUploadError"
                            :before-upload="beforeUpload"
                            accept="image/*">
                            <img v-if="form.image" :src="getImageUrl(form.image)" class="uploaded-image" style="max-width:200px;max-height:150px;display:block;">
                            <el-button v-else size="small" type="primary" icon="el-icon-upload2">上传图片</el-button>
                        </el-upload>
                        <div v-if="form.image" style="margin-top:8px;">
                            <el-button size="mini" type="danger" @click="form.image=''">删除图片</el-button>
                            <span style="font-size:12px;color:#909399;margin-left:8px;">{{form.image}}</span>
                        </div>
                    </div>
                </el-form-item>
                <el-form-item label="商品描述">
                    <el-input v-model="form.comment" type="textarea" :rows="3" placeholder="请输入商品描述"></el-input>
                </el-form-item>
                <el-form-item label="商品类型">
                    <el-radio-group v-model="form.itemType">
                        <el-radio :label="1">普通商品</el-radio>
                        <el-radio :label="2">秒杀商品</el-radio>
                    </el-radio-group>
                </el-form-item>
                <!-- 秒杀商品额外设置 -->
                <template v-if="form.itemType===2">
                    <el-divider content-position="left">秒杀商品设置</el-divider>
                    <el-form-item label="秒杀价格" prop="seckillPrice">
                        <el-input-number v-model="form.seckillPrice" :min="0.01" :precision="2" style="width:100%"></el-input-number>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">原价: &yen;{{formatMoney(form.price * 100)}}</div>
                    </el-form-item>
                    <el-form-item label="秒杀库存" prop="seckillStock">
                        <el-input-number v-model="form.seckillStock" :min="1" :max="form.stock" style="width:100%"></el-input-number>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">商品库存: {{form.stock}}（秒杀库存不能超过商品库存）</div>
                    </el-form-item>
                    <el-form-item label="每人限购" prop="seckillMaxPerUser">
                        <el-input-number v-model="form.seckillMaxPerUser" :min="1" style="width:100%"></el-input-number>
                    </el-form-item>
                    <el-form-item label="秒杀时间" prop="seckillBegin">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <el-date-picker v-model="form.seckillBegin" type="datetime" placeholder="开抢时间" style="flex:1" :picker-options="seckillBeginPickerOptions" default-time="10:00:00"></el-date-picker>
                            <span style="color:#909399;">至</span>
                            <el-date-picker v-model="form.seckillEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="seckillEndPickerOptions" default-time="22:00:00"></el-date-picker>
                        </div>
                    </el-form-item>
                </template>
            </el-form>
            <span slot="footer">
                <el-button @click="dialogVisible=false">取 消</el-button>
                <el-button type="primary" @click="submitForm" :loading="submitLoading">确 定</el-button>
            </span>
        </el-dialog>

        <!-- 设为秒杀弹窗 -->
        <el-dialog :title="itemSeckillForm.itemType===2?'秒杀设置':'设为秒杀商品'" :visible.sync="itemSeckillVisible" width="500px" :close-on-click-modal="false">
            <el-form :model="itemSeckillForm" :rules="itemSeckillRules" ref="itemSeckillForm" label-width="110px">
                <p style="margin:0 0 15px;color:#909399;font-size:13px;" v-if="itemSeckillForm.itemType!==2">将商品设为秒杀类型，需设置秒杀相关信息。商品基础信息可选择修改。</p>
                <el-form-item label="商品名称">
                    <el-input v-model="itemSeckillForm.name" placeholder="可修改"></el-input>
                </el-form-item>
                <el-form-item label="秒杀价格" prop="seckillPrice">
                    <el-input-number v-model="itemSeckillForm.seckillPrice" :min="0.01" :precision="2" style="width:100%"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">原价: &yen;{{formatMoney(itemSeckillForm.originalPrice)}}</div>
                </el-form-item>
                <el-form-item label="秒杀库存" prop="seckillStock">
                    <el-input-number v-model="itemSeckillForm.seckillStock" :min="1" style="width:100%"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">当前库存: {{itemSeckillForm.currentStock}}</div>
                </el-form-item>
                <el-form-item label="每人限购" prop="maxPerUser">
                    <el-input-number v-model="itemSeckillForm.maxPerUser" :min="1" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="秒杀时间" prop="rushBegin">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-date-picker v-model="itemSeckillForm.rushBegin" type="datetime" placeholder="开抢时间" style="flex:1" :picker-options="itemRushBeginPickerOptions" default-time="10:00:00"></el-date-picker>
                        <span style="color:#909399;">至</span>
                        <el-date-picker v-model="itemSeckillForm.rushEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="itemRushEndPickerOptions" default-time="22:00:00"></el-date-picker>
                    </div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="itemSeckillVisible=false">取 消</el-button>
                <el-button type="danger" v-if="itemSeckillForm.itemType===2" @click="cancelSeckill">取消秒杀</el-button>
                <el-button type="primary" @click="submitItemSeckill" :loading="itemSeckillLoading">确 定</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            loading: false,
            tableData: [],
            total: 0,
            currentPage: 1,
            pageSize: 10,
            search: { name: '', status: null, itemType: null },
            categories: [],
            dialogVisible: false,
            dialogTitle: '添加商品',
            submitLoading: false,
            form: { id: null, name: '', category: '', brand: '', price: 0, stock: 0, image: '', comment: '', itemType: 1 },
            formRules: {
                name: [{ required: true, message: '请输入商品名称', trigger: 'blur' }],
                category: [{ required: true, message: '请选择分类', trigger: 'change' }],
                price: [{ required: true, message: '请输入价格', trigger: 'blur' }],
                stock: [{ required: true, message: '请输入库存', trigger: 'blur' }],
                seckillPrice: [{ required: true, message: '请输入秒杀价格', trigger: 'blur' }],
                seckillStock: [{ required: true, message: '请输入秒杀库存', trigger: 'blur' }],
                seckillBegin: [{ required: true, message: '请选择秒杀时间', trigger: 'change' }]
            },
            // 秒杀设置弹窗
            itemSeckillVisible: false,
            itemSeckillLoading: false,
            itemSeckillForm: { id: null, name: '', itemType: 1, originalPrice: 0, currentStock: 0, seckillPrice: 0, seckillStock: 10, maxPerUser: 1, rushBegin: null, rushEnd: null },
            itemSeckillRules: {
                seckillPrice: [{ required: true, message: '请输入秒杀价格', trigger: 'blur' }],
                seckillStock: [{ required: true, message: '请输入秒杀库存', trigger: 'blur' }],
                maxPerUser: [{ required: true, message: '请输入限购数量', trigger: 'blur' }],
                rushBegin: [{ required: true, message: '请选择秒杀时间', trigger: 'change' }]
            },
            // 图片上传
            uploadHeaders: { 'authorization': 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') }
        };
    },
    computed: {
        totalPages() { return Math.ceil(this.total / this.pageSize) || 1; },
        // 添加/编辑弹窗秒杀时间选择器
        seckillBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        seckillEndPickerOptions() {
            const begin = this.form.seckillBegin ? new Date(this.form.seckillBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        },
        // 设为秒杀弹窗秒杀时间选择器
        itemRushBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        itemRushEndPickerOptions() {
            const begin = this.itemSeckillForm.rushBegin ? new Date(this.itemSeckillForm.rushBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        }
    },
    watch: {
        currentPage(val) {
            if (val > this.totalPages) {
                this.$nextTick(() => { this.currentPage = this.totalPages; });
            } else if (val < 1) {
                this.$nextTick(() => { this.currentPage = 1; });
            }
        }
    },
    mounted() {
        this.loadList();
        this.loadCategories();
    },
    methods: {
        formatMoney(val) { return ZM.formatMoney(val); },
        getImageUrl(path) {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            // 本地存储的相对路径，通过nginx访问
            return path;
        },
        beforeUpload(file) {
            const isImage = file.type.startsWith('image/');
            const isLt5M = file.size / 1024 / 1024 < 5;
            if (!isImage) {
                this.$message.error('只能上传图片文件!');
                return false;
            }
            if (!isLt5M) {
                this.$message.error('图片大小不能超过5MB!');
                return false;
            }
            return true;
        },
        handleUploadSuccess(res) {
            // 后端直接返回文件路径字符串
            if (typeof res === 'string' && res) {
                this.form.image = res;
                this.$message.success('图片上传成功');
            } else if (res && res.data) {
                this.form.image = res.data;
                this.$message.success('图片上传成功');
            } else {
                this.$message.error('图片上传失败');
            }
        },
        handleUploadError() {
            this.$message.error('图片上传失败，请重试');
        },
        loadList() {
            this.loading = true;
            const params = { page: this.currentPage, size: this.pageSize };
            if (this.search.name) params.name = this.search.name;
            if (this.search.status !== null && this.search.status !== '') params.status = this.search.status;
            if (this.search.itemType !== null && this.search.itemType !== '') params.itemType = this.search.itemType;
            ZM.http.get('/items/admin/page', { params }).then(res => {
                this.loading = false;
                let data = res;
                if (res && res.data && res.data.list) {
                    data = res.data;
                }
                if (data && data.list) {
                    this.tableData = data.list;
                    this.total = data.total || 0;
                } else if (Array.isArray(data)) {
                    this.tableData = data;
                    this.total = data.length;
                } else {
                    this.tableData = [];
                    this.total = 0;
                }
            }).catch(err => {
                this.loading = false;
                const status = err.response && err.response.status;
                if (status === 403) {
                    this.$message.error('无权限访问，请重新登录');
                    setTimeout(() => { ZM.clearLogin(); window.location.href = '/login.html'; }, 1500);
                } else {
                    this.$message.error('加载商品列表失败');
                }
            });
        },
        loadCategories() {
            ZM.http.get('/categories').then(res => {
                this.categories = Array.isArray(res) ? res : (res.list || []);
            }).catch(() => {});
        },
        resetSearch() {
            this.search = { name: '', status: null, itemType: null };
            this.currentPage = 1;
            this.loadList();
        },
        handleAdd() {
            this.dialogTitle = '添加商品';
            this.form = { id: null, name: '', category: '', brand: '', price: 0, stock: 0, image: '', comment: '', itemType: 1, seckillPrice: 0, seckillStock: 10, seckillMaxPerUser: 1, seckillBegin: null, seckillEnd: null };
            this.dialogVisible = true;
        },
        handleEdit(row) {
            this.dialogTitle = '编辑商品';
            this.form = { ...row, price: row.price / 100, seckillPrice: 0, seckillStock: 10, seckillMaxPerUser: 1, seckillBegin: null, seckillEnd: null };
            // 如果是秒杀商品，加载秒杀信息
            if (row.itemType === 2) {
                ZM.http.get('/seckill/admin/item/list').then(res => {
                    const list = Array.isArray(res) ? res : (res.records || []);
                    const existing = list.find(i => i.itemId === row.id);
                    if (existing) {
                        this.form.seckillPrice = existing.seckillPrice ? existing.seckillPrice / 100 : 0;
                        this.form.seckillStock = existing.seckillStock || 10;
                        this.form.seckillMaxPerUser = existing.maxPerUser || 1;
                        if (existing.rushBeginTime && existing.rushEndTime) {
                            this.form.seckillBegin = existing.rushBeginTime;
                            this.form.seckillEnd = existing.rushEndTime;
                        }
                    }
                }).catch(() => {});
            }
            this.dialogVisible = true;
        },
        submitForm() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                // 秒杀商品校验
                if (this.form.itemType === 2) {
                    if (!this.form.seckillPrice || this.form.seckillPrice <= 0) {
                        this.$message.warning('请输入秒杀价格');
                        return;
                    }
                    if (!this.form.seckillStock || this.form.seckillStock <= 0) {
                        this.$message.warning('请输入秒杀库存');
                        return;
                    }
                    if (this.form.seckillStock > this.form.stock) {
                        this.$message.warning('秒杀库存不能超过商品库存');
                        return;
                    }
                    if (this.form.seckillPrice > this.form.price) {
                        this.$message.warning('秒杀价格不能超过原价（¥' + this.formatMoney(Math.round(this.form.price * 100)) + '）');
                        return;
                    }
                    if (!this.form.seckillBegin || !this.form.seckillEnd) {
                        this.$message.warning('请选择秒杀时间');
                        return;
                    }
                    if (new Date(this.form.seckillBegin).getTime() <= Date.now() + 300000) {
                        this.$message.warning('开抢时间请选择5分钟之后');
                        return;
                    }
                }
                this.submitLoading = true;
                // 前端输入元，后端存储分
                const data = { ...this.form };
                data.price = Math.round(this.form.price * 100);
                const req = this.form.id
                    ? ZM.http.put('/items/admin', data)
                    : ZM.http.post('/items/admin', data);
                req.then(res => {
                    // 如果是秒杀商品，创建/更新秒杀记录
                    if (this.form.itemType === 2) {
                        const formatDateForApi = (val) => {
                            if (!val) return null;
                            if (typeof val === 'string') return val;
                            const d = new Date(val);
                            const pad = n => n < 10 ? '0' + n : n;
                            return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
                        };
                        const newItemId = this.form.id || res;
                        const seckillData = {
                            itemId: newItemId,
                            seckillPrice: Math.round(this.form.seckillPrice * 100),
                            seckillStock: this.form.seckillStock,
                            maxPerUser: this.form.seckillMaxPerUser || 1,
                            rushBeginTime: formatDateForApi(this.form.seckillBegin),
                            rushEndTime: formatDateForApi(this.form.seckillEnd)
                        };
                        ZM.http.post('/seckill/admin/item', seckillData).catch(err => {
                            console.error('秒杀信息保存失败', err);
                        });
                    }
                    this.submitLoading = false;
                    this.$message.success(this.form.id ? '修改成功' : '添加成功');
                    this.dialogVisible = false;
                    this.loadList();
                }).catch(err => {
                    this.submitLoading = false;
                    this.$message.error('操作失败');
                });
            });
        },
        toggleStatus(row) {
            const newStatus = row.status === 1 ? 2 : 1;
            const action = newStatus === 1 ? '上架' : '下架';
            this.$confirm('确定要' + action + '该商品吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/items/admin/status/' + row.id + '/' + newStatus).then(() => {
                    this.$message.success(action + '成功');
                    this.loadList();
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        },
        handleSetSeckill(row) {
            this.itemSeckillForm = {
                id: row.id,
                name: row.name,
                itemType: row.itemType || 1,
                originalPrice: row.price,
                currentStock: row.stock,
                seckillPrice: row.price ? row.price / 100 * 0.8 / 100 : 0,
                seckillStock: Math.min(10, row.stock || 10),
                maxPerUser: 1,
                rushBegin: null,
                rushEnd: null
            };
            // 如果已是秒杀商品，加载已有秒杀信息
            if (row.itemType === 2) {
                ZM.http.get('/seckill/admin/item/list').then(res => {
                    const list = Array.isArray(res) ? res : (res.records || []);
                    const existing = list.find(i => i.itemId === row.id);
                    if (existing) {
                        this.itemSeckillForm.seckillPrice = existing.seckillPrice ? existing.seckillPrice / 100 : 0;
                        this.itemSeckillForm.seckillStock = existing.seckillStock || 10;
                        this.itemSeckillForm.maxPerUser = existing.maxPerUser || 1;
                        if (existing.rushBeginTime && existing.rushEndTime) {
                            this.itemSeckillForm.rushBegin = existing.rushBeginTime;
                            this.itemSeckillForm.rushEnd = existing.rushEndTime;
                        }
                    }
                }).catch(() => {});
            }
            this.itemSeckillVisible = true;
        },
        submitItemSeckill() {
            this.$refs.itemSeckillForm.validate(valid => {
                if (!valid) return;
                if (!this.itemSeckillForm.rushBegin || !this.itemSeckillForm.rushEnd) {
                    this.$message.warning('请选择秒杀时间');
                    return;
                }
                if (new Date(this.itemSeckillForm.rushBegin).getTime() <= Date.now() + 300000) {
                    this.$message.warning('开抢时间请选择5分钟之后');
                    return;
                }
                if (this.itemSeckillForm.seckillPrice * 100 > this.itemSeckillForm.originalPrice) {
                    this.$message.warning('秒杀价格不能超过原价（¥' + this.formatMoney(this.itemSeckillForm.originalPrice) + '）');
                    return;
                }
                this.itemSeckillLoading = true;
                const formatDateForApi = (val) => {
                    if (!val) return null;
                    if (typeof val === 'string') return val;
                    const d = new Date(val);
                    const pad = n => n < 10 ? '0' + n : n;
                    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
                };
                // 1. 设置商品类型为秒杀
                const setItemType = this.itemSeckillForm.itemType !== 2
                    ? ZM.http.put('/items/admin/itemType/' + this.itemSeckillForm.id + '/2')
                    : Promise.resolve();
                setItemType.then(() => {
                    // 2. 创建/更新秒杀商品信息
                    const data = {
                        itemId: this.itemSeckillForm.id,
                        seckillStock: this.itemSeckillForm.seckillStock,
                        seckillPrice: Math.round(this.itemSeckillForm.seckillPrice * 100),
                        maxPerUser: this.itemSeckillForm.maxPerUser,
                        rushBeginTime: formatDateForApi(this.itemSeckillForm.rushBegin),
                        rushEndTime: formatDateForApi(this.itemSeckillForm.rushEnd)
                    };
                    const req = this.itemSeckillForm.itemType === 2
                        ? ZM.http.put('/seckill/admin/item', data)
                        : ZM.http.post('/seckill/admin/item', data);
                    return req;
                }).then(() => {
                    this.itemSeckillLoading = false;
                    this.$message.success('秒杀设置成功');
                    this.itemSeckillVisible = false;
                    this.loadList();
                }).catch(() => {
                    this.itemSeckillLoading = false;
                    this.$message.error('操作失败');
                });
            });
        },
        cancelSeckill() {
            this.$confirm('确定要取消秒杀吗？商品将恢复为普通商品', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/items/admin/itemType/' + this.itemSeckillForm.id + '/1').then(() => {
                    this.$message.success('已取消秒杀');
                    this.itemSeckillVisible = false;
                    this.loadList();
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        },
        handleDelete(row) {
            this.$confirm('确定要删除该商品吗？删除后不可恢复', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/items/admin/' + row.id).then(() => {
                    this.$message.success('删除成功');
                    this.loadList();
                }).catch(() => { this.$message.error('删除失败'); });
            }).catch(() => {});
        }
    }
});
