// 秒杀优惠券管理页面组件
Vue.component('seckill-coupon-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;">
                <h3>秒杀优惠券管理</h3>
                <div style="display:flex;gap:8px;">
                    <el-button type="warning" size="small" icon="el-icon-lightning" @click="openBatchPreheat">批量预热</el-button>
                    <el-button type="primary" size="small" icon="el-icon-plus" @click="openBatchSetSeckill">批量设置秒杀</el-button>
                </div>
            </div>
            <!-- 搜索栏 -->
            <div class="search-bar" style="margin-bottom:15px;">
                <el-input v-model="searchKeyword" placeholder="搜索优惠券名称或ID" size="small" style="width:220px;" clearable prefix-icon="el-icon-search"></el-input>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="searchKeyword='';currentPage=1">重置</el-button>
            </div>
            <!-- 状态Tab -->
            <el-tabs v-model="activeStatus" @tab-click="handleStatusChange">
                <el-tab-pane label="准备开抢" name="upcoming">
                    <span slot="label">准备开抢 <el-badge :value="statusCount.upcoming" type="info" v-if="statusCount.upcoming>0" style="margin-left:4px;"></el-badge></span>
                </el-tab-pane>
                <el-tab-pane label="正在抢购" name="ongoing">
                    <span slot="label">正在抢购 <el-badge :value="statusCount.ongoing" type="danger" v-if="statusCount.ongoing>0" style="margin-left:4px;"></el-badge></span>
                </el-tab-pane>
                <el-tab-pane label="抢购结束" name="ended">
                    <span slot="label">抢购结束 <el-badge :value="statusCount.ended" type="success" v-if="statusCount.ended>0" style="margin-left:4px;"></el-badge></span>
                </el-tab-pane>
            </el-tabs>
            <!-- 表格 -->
            <el-table :data="pagedData" border stripe v-loading="loading" style="width:100%">
                <el-table-column prop="couponId" label="优惠券ID" width="100" align="center"></el-table-column>
                <el-table-column prop="couponName" label="优惠券名称" min-width="180" show-overflow-tooltip></el-table-column>
                <el-table-column label="优惠方式" width="140" align="center">
                    <template slot-scope="scope">
                        <span v-if="scope.row.type===1">满减{{scope.row.discountValue}}</span>
                        <span v-else-if="scope.row.type===2">{{(scope.row.discountValue/10).toFixed(1)}}折</span>
                        <span v-else>{{scope.row.discountValue}}</span>
                    </template>
                </el-table-column>
                <el-table-column prop="seckillStock" label="秒杀库存" width="100" align="center">
                    <template slot-scope="scope">
                        <span :style="{color: scope.row.seckillStock <= 10 ? '#e54346' : ''}">{{scope.row.seckillStock}}</span>
                    </template>
                </el-table-column>
                <el-table-column label="秒杀时间" width="180" align="center">
                    <template slot-scope="scope">
                        <div v-if="scope.row.rushBeginTime">{{(scope.row.rushBeginTime||'').substring(0,16)}}</div>
                        <div v-if="scope.row.rushEndTime">至 {{(scope.row.rushEndTime||'').substring(0,16)}}</div>
                        <span v-if="!scope.row.rushBeginTime && !scope.row.rushEndTime">未设置</span>
                    </template>
                </el-table-column>
                <el-table-column label="状态" width="100" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="getStatusType(scope.row)" size="small">{{getStatusText(scope.row)}}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="预热状态" width="100" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.preheatStatus===1?'success':'info'" size="small">
                            {{scope.row.preheatStatus===1?'已预热':'未预热'}}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="220" align="center" fixed="right">
                    <template slot-scope="scope">
                        <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:center;">
                            <el-button size="mini" @click="handleEdit(scope.row)">编辑</el-button>
                            <el-button size="mini" type="success" @click="handlePreheat(scope.row)">预热</el-button>
                            <el-button size="mini" type="info" @click="handleClearPreheat(scope.row)">清除预热</el-button>
                            <el-button size="mini" type="warning" @click="handleConvertToNormal(scope.row)">转普通</el-button>
                        </div>
                    </template>
                </el-table-column>
            </el-table>
            <div style="margin-top:15px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>

        <!-- 批量预热对话框 -->
        <el-dialog title="批量预热秒杀优惠券" :visible.sync="batchVisible" width="700px" :close-on-click-modal="false">
            <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <el-input v-model="batchSearchKey" placeholder="搜索优惠券名称或ID" size="small" style="width:220px;" clearable @input="filterBatchCoupons" prefix-icon="el-icon-search"></el-input>
                    <el-button size="small" type="text" @click="selectAllCoupons">选择全部({{tableData.length}})</el-button>
                </div>
                <div>
                    <el-checkbox v-model="batchSelectAll" @change="toggleBatchSelectAll" :indeterminate="batchSelectedIds.length>0 && batchSelectedIds.length<filteredBatchList.length">全选当前列表</el-checkbox>
                    <span v-if="batchSelectedIds.length" style="margin-left:12px;font-size:13px;color:#409eff;">已选 {{batchSelectedIds.length}} 个优惠券</span>
                </div>
            </div>
            <el-checkbox-group v-model="batchSelectedIds" @change="handleBatchSelectChange">
                <div style="max-height:350px;overflow-y:auto;border:1px solid #eee;border-radius:4px;padding:8px;">
                    <div v-for="item in filteredBatchList" :key="item.couponId" style="display:flex;align-items:center;padding:6px 4px;border-bottom:1px solid #f5f5f5;">
                        <el-checkbox :label="item.couponId" style="margin-right:8px;">&nbsp;</el-checkbox>
                        <span style="font-size:13px;width:70px;color:#666;">ID:{{item.couponId}}</span>
                        <span style="font-size:13px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{item.couponName}}</span>
                        <el-tag :type="getStatusType(item)" size="mini" style="margin-left:8px;">{{getStatusText(item)}}</el-tag>
                        <el-tag :type="item.preheatStatus===1?'success':'info'" size="mini" style="margin-left:4px;">{{item.preheatStatus===1?'已预热':'未预热'}}</el-tag>
                    </div>
                    <div v-if="!filteredBatchList.length" style="text-align:center;color:#999;padding:20px;">暂无匹配的秒杀优惠券</div>
                </div>
            </el-checkbox-group>
            <span slot="footer">
                <el-button @click="batchVisible=false">取消</el-button>
                <el-button type="warning" @click="doBatchPreheat" :loading="batchLoading" :disabled="batchSelectedIds.length===0">批量预热 ({{batchSelectedIds.length}})</el-button>
            </span>
        </el-dialog>

        <!-- 添加/编辑弹窗 -->
        <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="550px" :close-on-click-modal="false">
            <el-form :model="form" :rules="formRules" ref="form" label-width="120px">
                <el-form-item label="优惠券ID" prop="couponId">
                    <el-input v-model="form.couponId" style="width:100%" :disabled="!!form.id"></el-input>
                </el-form-item>
                <el-form-item label="秒杀库存" prop="stock">
                    <el-input-number v-model="form.stock" :min="1" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="秒杀时间">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-date-picker v-model="form.seckillBegin" type="datetime" placeholder="开抢时间" style="flex:1" :picker-options="rushBeginPickerOptions" default-time="10:00:00"></el-date-picker>
                        <span style="color:#909399;">至</span>
                        <el-date-picker v-model="form.seckillEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="rushEndPickerOptions" default-time="22:00:00"></el-date-picker>
                    </div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="dialogVisible=false">取 消</el-button>
                <el-button type="primary" @click="submitForm" :loading="submitLoading">确 定</el-button>
            </span>
        </el-dialog>

        <!-- 批量设置秒杀优惠券弹窗 -->
        <el-dialog title="批量设置秒杀优惠券" :visible.sync="setSeckillVisible" width="750px" :close-on-click-modal="false">
            <!-- 步骤一：选择普通优惠券 -->
            <div v-if="setSeckillStep===1">
                <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-input v-model="setSeckillSearchKey" placeholder="搜索优惠券名称或ID" size="small" style="width:220px;" clearable @input="filterSetSeckillCoupons" prefix-icon="el-icon-search"></el-input>
                        <el-button size="small" type="text" @click="selectAllNormalCoupons">选择全部({{normalCouponList.length}})</el-button>
                    </div>
                    <div>
                        <el-checkbox v-model="setSeckillSelectAll" @change="toggleSetSeckillSelectAll" :indeterminate="setSeckillSelectedIds.length>0 && setSeckillSelectedIds<filteredNormalCouponList.length">全选当前列表</el-checkbox>
                        <span v-if="setSeckillSelectedIds.length" style="margin-left:12px;font-size:13px;color:#409eff;">已选 {{setSeckillSelectedIds.length}} 个优惠券</span>
                    </div>
                </div>
                <el-checkbox-group v-model="setSeckillSelectedIds" @change="handleSetSeckillSelectChange">
                    <div style="max-height:350px;overflow-y:auto;border:1px solid #eee;border-radius:4px;padding:8px;">
                        <div v-for="item in filteredNormalCouponList" :key="item.id" style="display:flex;align-items:center;padding:6px 4px;border-bottom:1px solid #f5f5f5;">
                            <el-checkbox :label="item.id" style="margin-right:8px;">&nbsp;</el-checkbox>
                            <span style="font-size:13px;width:70px;color:#666;">ID:{{item.id}}</span>
                            <span style="font-size:13px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{item.name}}</span>
                            <span style="font-size:12px;color:#999;margin-left:8px;">库存:{{item.stock}}</span>
                        </div>
                        <div v-if="normalCouponListLoading" style="text-align:center;color:#999;padding:20px;">加载中...</div>
                        <div v-else-if="!filteredNormalCouponList.length" style="text-align:center;color:#999;padding:20px;">暂无可选的普通优惠券</div>
                    </div>
                </el-checkbox-group>
            </div>
            <!-- 步骤二：填写秒杀信息 -->
            <div v-if="setSeckillStep===2">
                <el-alert :title="'已选择 ' + setSeckillSelectedIds.length + ' 个优惠券'" type="info" :closable="false" style="margin-bottom:16px;"></el-alert>
                <el-form :model="setSeckillForm" :rules="setSeckillFormRules" ref="setSeckillForm" label-width="120px">
                    <el-form-item label="秒杀库存" prop="seckillStock">
                        <el-input-number v-model="setSeckillForm.seckillStock" :min="1" style="width:100%"></el-input-number>
                    </el-form-item>
                    <el-form-item label="秒杀限领">
                        <el-input-number v-model="setSeckillForm.maxPerUser" :min="1" :max="1" :disabled="true" style="width:100%"></el-input-number>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">秒杀优惠券每人限领1张，不可修改</div>
                    </el-form-item>
                    <el-form-item label="秒杀时间">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <el-date-picker v-model="setSeckillForm.rushBegin" type="datetime" placeholder="开抢时间" style="flex:1" :picker-options="sRushBeginPickerOptions" default-time="10:00:00"></el-date-picker>
                            <span style="color:#909399;">至</span>
                            <el-date-picker v-model="setSeckillForm.rushEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="sRushEndPickerOptions" default-time="22:00:00"></el-date-picker>
                        </div>
                    </el-form-item>
                </el-form>
            </div>
            <span slot="footer">
                <el-button @click="setSeckillStep===2 ? (setSeckillStep=1) : (setSeckillVisible=false)">{{setSeckillStep===1?'取消':'上一步'}}</el-button>
                <el-button v-if="setSeckillStep===1" type="primary" @click="goSetSeckillStep2" :disabled="setSeckillSelectedIds.length===0">下一步</el-button>
                <el-button v-if="setSeckillStep===2" type="primary" @click="doBatchSetSeckill" :loading="setSeckillLoading">确认设置</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            loading: false,
            tableData: [],
            total: 0,
            activeStatus: 'upcoming',
            statusCount: { upcoming: 0, ongoing: 0, ended: 0 },
            searchKeyword: '',
            currentPage: 1,
            pageSize: 10,
            dialogVisible: false,
            dialogTitle: '添加秒杀优惠券',
            submitLoading: false,
            form: { id: null, couponId: null, stock: 10, seckillBegin: null, seckillEnd: null },
            formRules: {
                couponId: [{ required: true, message: '请输入优惠券ID', trigger: 'blur' }],
                stock: [{ required: true, message: '请输入秒杀库存', trigger: 'blur' }]
            },
            // 批量预热
            batchVisible: false,
            batchLoading: false,
            batchSearchKey: '',
            batchSelectAll: false,
            batchSelectedIds: [],
            batchCouponList: [],
            filteredBatchList: [],
            // 批量设置秒杀
            setSeckillVisible: false,
            setSeckillStep: 1,
            setSeckillSearchKey: '',
            setSeckillSelectAll: false,
            setSeckillSelectedIds: [],
            setSeckillLoading: false,
            normalCouponList: [],
            normalCouponListLoading: false,
            filteredNormalCouponList: [],
            setSeckillForm: { seckillStock: 10, maxPerUser: 1, rushBegin: null, rushEnd: null },
            setSeckillFormRules: {
                seckillStock: [{ required: true, message: '请输入秒杀库存', trigger: 'blur' }]
            }
        };
    },
    computed: {
        filteredData() {
            let list = this.tableData.filter(item => this.getCouponStatus(item) === this.activeStatus);
            const key = (this.searchKeyword || '').toLowerCase().trim();
            if (key) {
                list = list.filter(item =>
                    (item.couponName || '').toLowerCase().includes(key) || String(item.couponId).includes(key)
                );
            }
            return list;
        },
        filteredTotal() {
            return this.filteredData.length;
        },
        pagedData() {
            const start = (this.currentPage - 1) * this.pageSize;
            return this.filteredData.slice(start, start + this.pageSize);
        },
        // 编辑弹窗日期选择器
        rushBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        rushEndPickerOptions() {
            const begin = this.form.seckillBegin ? new Date(this.form.seckillBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        },
        // 批量设置秒杀弹窗日期选择器
        sRushBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        sRushEndPickerOptions() {
            const begin = this.setSeckillForm.rushBegin ? new Date(this.setSeckillForm.rushBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        }
    },
    mounted() {
        this.loadList();
    },
    methods: {
        getCouponStatus(item) {
            const now = new Date().getTime();
            const begin = item.rushBeginTime ? new Date(item.rushBeginTime).getTime() : 0;
            const end = item.rushEndTime ? new Date(item.rushEndTime).getTime() : 0;
            if (!begin || !end) return 'upcoming';
            if (now < begin) return 'upcoming';
            if (now >= begin && now <= end) return 'ongoing';
            return 'ended';
        },
        getStatusType(item) {
            const s = this.getCouponStatus(item);
            return s === 'ongoing' ? 'danger' : s === 'ended' ? 'info' : 'warning';
        },
        getStatusText(item) {
            const s = this.getCouponStatus(item);
            return s === 'ongoing' ? '正在抢购' : s === 'ended' ? '抢购结束' : '准备开抢';
        },
        handleStatusChange() { this.currentPage = 1; },
        updateStatusCount() {
            this.statusCount = { upcoming: 0, ongoing: 0, ended: 0 };
            this.tableData.forEach(item => {
                const s = this.getCouponStatus(item);
                this.statusCount[s]++;
            });
        },
        loadList() {
            this.loading = true;
            ZM.http.get('/seckill/admin/coupon/list').then(res => {
                this.loading = false;
                if (Array.isArray(res)) {
                    this.tableData = res;
                    this.total = res.length;
                } else if (res && res.records) {
                    this.tableData = res.records;
                    this.total = res.total || 0;
                }
                this.updateStatusCount();
            }).catch(() => { this.loading = false; });
        },
        handleAdd() {
            this.dialogTitle = '添加秒杀优惠券';
            this.form = { id: null, couponId: null, stock: 10, seckillBegin: null, seckillEnd: null };
            this.dialogVisible = true;
        },
        handleEdit(row) {
            this.dialogTitle = '编辑秒杀优惠券';
            this.form = {
                id: row.couponId,
                couponId: row.couponId,
                stock: row.seckillStock,
                seckillBegin: row.rushBeginTime || null,
                seckillEnd: row.rushEndTime || null
            };
            this.dialogVisible = true;
        },
        submitForm() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                if (this.form.seckillBegin && new Date(this.form.seckillBegin).getTime() <= Date.now() + 300000) {
                    this.$message.warning('开抢时间请选择5分钟之后');
                    return;
                }
                this.submitLoading = true;
                const data = {
                    couponId: this.form.couponId,
                    seckillStock: this.form.stock
                };
                if (this.form.seckillBegin && this.form.seckillEnd) {
                    data.rushBeginTime = this.formatDateForApi(this.form.seckillBegin);
                    data.rushEndTime = this.formatDateForApi(this.form.seckillEnd);
                }
                // 编辑和新建都调用 POST /seckill/admin/coupon
                // createSeckillCoupon 方法支持 exist 更新（exist != null 时 updateById）
                let req = ZM.http.post('/seckill/admin/coupon', data);
                req.then(() => {
                    this.submitLoading = false;
                    this.$message.success('操作成功');
                    this.dialogVisible = false;
                    this.loadList();
                }).catch(() => {
                    this.submitLoading = false;
                    this.$message.error('操作失败');
                });
            });
        },
        formatDateForApi(val) {
            if (!val) return null;
            if (typeof val === 'string') return val;
            const d = new Date(val);
            const pad = n => n < 10 ? '0' + n : n;
            return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
        },
        handlePreheat(row) {
            this.$confirm('确定要预热该秒杀优惠券的库存吗？', '提示', { type: 'info' }).then(() => {
                ZM.http.post('/seckill/admin/coupon/preheat/' + row.couponId).then(() => {
                    this.$message.success('预热成功');
                    this.loadList();
                }).catch(() => { this.$message.error('预热失败'); });
            }).catch(() => {});
        },
        handleClearPreheat(row) {
            this.$confirm('确定要清除该秒杀优惠券的预热库存吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/seckill/admin/coupon/preheat/' + row.couponId).then(() => {
                    this.$message.success('清除成功');
                    this.loadList();
                }).catch(() => { this.$message.error('清除失败'); });
            }).catch(() => {});
        },
        // 批量预热
        openBatchPreheat() {
            this.batchSearchKey = '';
            this.batchSelectAll = false;
            this.batchSelectedIds = [];
            // 重新加载列表以获取最新预热状态
            ZM.http.get('/seckill/admin/coupon/list').then(res => {
                const list = Array.isArray(res) ? res : (res && res.records) ? res.records : [];
                this.batchCouponList = list;
                this.filteredBatchList = [...list];
            });
            this.batchVisible = true;
        },
        selectAllCoupons() {
            this.batchSelectedIds = this.batchCouponList.map(i => i.couponId);
        },
        filterBatchCoupons() {
            const key = (this.batchSearchKey || '').toLowerCase();
            if (!key) {
                this.filteredBatchList = [...this.batchCouponList];
            } else {
                this.filteredBatchList = this.batchCouponList.filter(item =>
                    (item.couponName || '').toLowerCase().includes(key) || String(item.couponId).includes(key)
                );
            }
        },
        toggleBatchSelectAll(val) {
            if (val) {
                this.batchSelectedIds = [...new Set([...this.batchSelectedIds, ...this.filteredBatchList.map(i => i.couponId)])];
            } else {
                this.batchSelectedIds = this.batchSelectedIds.filter(id => !this.filteredBatchList.find(i => i.couponId === id));
            }
        },
        handleBatchSelectChange(val) {
            this.batchSelectAll = val.length === this.filteredBatchList.length;
        },
        doBatchPreheat() {
            if (this.batchSelectedIds.length === 0) {
                this.$message.warning('请选择要预热的优惠券');
                return;
            }
            this.batchLoading = true;
            ZM.http.post('/seckill/admin/coupon/preheat/batch', this.batchSelectedIds).then(() => {
                this.batchLoading = false;
                this.$message.success('批量预热成功');
                this.batchVisible = false;
                this.loadList();
            }).catch(() => {
                this.batchLoading = false;
                this.$message.error('批量预热失败');
            });
        },
        // 批量设置秒杀
        openBatchSetSeckill() {
            this.setSeckillStep = 1;
            this.setSeckillSearchKey = '';
            this.setSeckillSelectAll = false;
            this.setSeckillSelectedIds = [];
            this.setSeckillForm = { seckillStock: 10, maxPerUser: 1, rushBegin: null, rushEnd: null };
            this.loadNormalCoupons();
            this.setSeckillVisible = true;
        },
        loadNormalCoupons() {
            this.normalCouponListLoading = true;
            ZM.http.get('/coupons/admin/page', { params: { page: 1, size: 1000, couponType: 1 } }).then(res => {
                this.normalCouponListLoading = false;
                let data = res;
                if (res && res.data && res.data.list) data = res.data;
                this.normalCouponList = data && data.list ? data.list : (Array.isArray(data) ? data : []);
                this.filteredNormalCouponList = [...this.normalCouponList];
            }).catch(() => { this.normalCouponListLoading = false; });
        },
        filterSetSeckillCoupons() {
            const key = (this.setSeckillSearchKey || '').toLowerCase();
            if (!key) {
                this.filteredNormalCouponList = [...this.normalCouponList];
            } else {
                this.filteredNormalCouponList = this.normalCouponList.filter(item =>
                    (item.name || '').toLowerCase().includes(key) || String(item.id).includes(key)
                );
            }
        },
        selectAllNormalCoupons() {
            this.setSeckillSelectedIds = this.normalCouponList.map(i => i.id);
        },
        toggleSetSeckillSelectAll(val) {
            if (val) {
                this.setSeckillSelectedIds = [...new Set([...this.setSeckillSelectedIds, ...this.filteredNormalCouponList.map(i => i.id)])];
            } else {
                this.setSeckillSelectedIds = this.setSeckillSelectedIds.filter(id => !this.filteredNormalCouponList.find(i => i.id === id));
            }
        },
        handleSetSeckillSelectChange(val) {
            this.setSeckillSelectAll = val.length === this.filteredNormalCouponList.length;
        },
        goSetSeckillStep2() {
            if (this.setSeckillSelectedIds.length === 0) {
                this.$message.warning('请选择优惠券');
                return;
            }
            this.setSeckillStep = 2;
        },
        doBatchSetSeckill() {
            this.$refs.setSeckillForm.validate(valid => {
                if (!valid) return;
                if (!this.setSeckillForm.rushBegin || !this.setSeckillForm.rushEnd) {
                    this.$message.warning('请选择秒杀时间');
                    return;
                }
                if (new Date(this.setSeckillForm.rushBegin).getTime() <= Date.now() + 300000) {
                    this.$message.warning('开抢时间请选择5分钟之后');
                    return;
                }
                this.setSeckillLoading = true;
                const data = {
                    couponIds: this.setSeckillSelectedIds,
                    seckillStock: this.setSeckillForm.seckillStock,
                    maxPerUser: 1,
                    rushBeginTime: this.formatDateForApi(this.setSeckillForm.rushBegin),
                    rushEndTime: this.formatDateForApi(this.setSeckillForm.rushEnd)
                };
                ZM.http.post('/seckill/admin/coupon/batch', data).then(() => {
                    this.setSeckillLoading = false;
                    this.$message.success('批量设置秒杀成功');
                    this.setSeckillVisible = false;
                    this.loadList();
                }).catch(() => {
                    this.setSeckillLoading = false;
                    this.$message.error('批量设置秒杀失败');
                });
            });
        },
        handleConvertToNormal(row) {
            this.$confirm('确定将该秒杀优惠券转为普通优惠券吗？转普通后将清除秒杀配置和预热数据。', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/seckill/admin/coupon/convert/' + row.couponId).then(() => {
                    this.$message.success('已转为普通优惠券');
                    this.loadList();
                    // 跳转到优惠券编辑页面
                    if (typeof ZM !== 'undefined' && ZM.nav) {
                        ZM.nav.openPage('coupon-edit', { id: row.couponId });
                    }
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        }
    }
});
