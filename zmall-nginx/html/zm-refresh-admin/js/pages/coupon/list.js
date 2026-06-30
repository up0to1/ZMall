// 优惠券列表页面组件
Vue.component('coupon-list-page', {
    template: `
    <div>
        <!-- 优惠券统计卡片 -->
        <div style="display:flex;gap:15px;margin-bottom:20px;">
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e54346;">{{couponStats.totalIssued || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">发行总量</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#409eff;">{{couponStats.totalReceived || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">已领取</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#67c23a;">{{couponStats.totalUsed || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">已使用</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e6a23c;">{{(couponStats.receiveRate || 0).toFixed(1)}}%</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">领取率</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#f56c6c;">{{(couponStats.useRate || 0).toFixed(1)}}%</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">使用率</div>
            </div>
        </div>

        <div class="page-card">
            <div class="page-header">
                <h3>优惠券管理</h3>
                <el-button type="primary" size="small" icon="el-icon-plus" @click="handleAdd">添加优惠券</el-button>
            </div>
            <!-- 搜索栏 -->
            <div class="search-bar">
                <el-select v-model="search.status" placeholder="状态" size="small" clearable>
                    <el-option label="已上架" :value="1"></el-option>
                    <el-option label="已下架" :value="2"></el-option>
                </el-select>
                <el-select v-model="search.couponType" placeholder="类型" size="small" clearable>
                    <el-option label="普通优惠券" :value="1"></el-option>
                    <el-option label="秒杀优惠券" :value="2"></el-option>
                </el-select>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <!-- 表格 -->
            <el-table :data="pagedData" border stripe v-loading="loading" style="width:100%">
                <el-table-column prop="id" label="ID" width="70" align="center"></el-table-column>
                <el-table-column prop="name" label="优惠券名称" min-width="140" show-overflow-tooltip></el-table-column>
                <el-table-column label="类型" width="90" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.couponType===2?'danger':''" size="small" effect="plain">
                            {{scope.row.couponType===2?'秒杀':'普通'}}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="优惠方式" width="130" align="center">
                    <template slot-scope="scope">
                        <span v-if="scope.row.type===1">满{{formatMoney(scope.row.thresholdAmount)}}减{{formatMoney(scope.row.discountValue)}}</span>
                        <span v-else-if="scope.row.type===2">{{(scope.row.discountValue/10).toFixed(1)}}折<span v-if="scope.row.purchasePrice>0" style="color:#e54346;"> ￥{{formatMoney(scope.row.purchasePrice)}}</span></span>
                        <span v-else>{{scope.row.typeText || '-'}}</span>
                    </template>
                </el-table-column>
                <el-table-column label="适用范围" width="100" align="center">
                    <template slot-scope="scope">
                        <span>{{scope.row.scopeType===1?'全部':'部分商品'}}</span>
                    </template>
                </el-table-column>
                <el-table-column prop="totalCount" label="发行量" width="70" align="center"></el-table-column>
                <el-table-column label="秒杀信息" width="160" align="center" v-if="search.couponType===2">
                    <template slot-scope="scope">
                        <template v-if="scope.row.couponType===2">
                            <div style="font-size:12px;">库存:{{scope.row.seckillStock||'-'}} | 限领:1</div>
                            <div style="font-size:12px;color:#909399;">{{(scope.row.rushBeginTime||'').substring(5,16)}} ~ {{(scope.row.rushEndTime||'').substring(5,16)}}</div>
                        </template>
                        <span v-else>-</span>
                    </template>
                </el-table-column>
                <el-table-column label="状态" width="80" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.status===1?'success':'info'" size="small">
                            {{scope.row.status===1?'上架':'下架'}}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="260" align="center" fixed="right">
                    <template slot-scope="scope">
                        <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:center;">
                            <el-button size="mini" @click="handleEdit(scope.row)">编辑</el-button>
                            <el-button size="mini" :type="scope.row.status===1?'warning':'success'" @click="toggleStatus(scope.row)">
                                {{scope.row.status===1?'下架':'上架'}}
                            </el-button>
                            <el-button size="mini" :type="scope.row.couponType===2?'':'danger'" @click="handleSetSeckill(scope.row)">
                                {{scope.row.couponType===2?'秒杀设置':'设为秒杀'}}
                            </el-button>
                            <el-button size="mini" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                        </div>
                    </template>
                </el-table-column>
            </el-table>
            <!-- 分页 -->
            <div style="margin-top:16px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>

        <!-- 添加/编辑弹窗 -->
        <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="700px" :close-on-click-modal="false" top="5vh">
            <el-form :model="form" :rules="formRules" ref="form" label-width="110px">
                <el-form-item label="优惠券名称" prop="name">
                    <el-input v-model="form.name" placeholder="请输入优惠券名称"></el-input>
                </el-form-item>
                <el-form-item label="优惠类型" prop="discountType">
                    <el-radio-group v-model="form.discountType">
                        <el-radio :label="1">满减</el-radio>
                        <el-radio :label="2">折扣</el-radio>
                    </el-radio-group>
                </el-form-item>
                <el-form-item label="使用门槛" prop="threshold" v-if="form.discountType===1">
                    <el-input-number v-model="form.threshold" :min="0" :precision="2" style="width:100%" placeholder="满X元可用"></el-input-number>
                </el-form-item>
                <el-form-item label="购买价格" prop="purchasePrice" v-if="form.discountType===2">
                    <el-input-number v-model="form.purchasePrice" :min="0.01" :precision="2" style="width:100%" placeholder="优惠券购买价格"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">折扣券需购买后使用</div>
                </el-form-item>
                <el-form-item label="优惠额度" prop="discountValue">
                    <el-input-number v-model="form.discountValue" :min="0" :precision="2" style="width:100%" :placeholder="form.discountType===1?'减免金额':'折扣(如8.5)'"></el-input-number>
                </el-form-item>
                <el-form-item label="发行总量" prop="totalNum">
                    <el-input-number v-model="form.totalNum" :min="1" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="每人限领" prop="userLimit" v-if="form.couponType!==2">
                    <el-input-number v-model="form.userLimit" :min="1" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="有效期类型">
                    <el-radio-group v-model="form.termType">
                        <el-radio :label="1">固定时间</el-radio>
                        <el-radio :label="2">领后N天</el-radio>
                    </el-radio-group>
                </el-form-item>
                <el-form-item label="有效期" v-if="form.termType===1">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-date-picker v-model="form.termBegin" type="datetime" placeholder="开始时间" style="flex:1" :picker-options="beginPickerOptions" default-time="00:00:00"></el-date-picker>
                        <span style="color:#909399;">至</span>
                        <el-date-picker v-model="form.termEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="termEndPickerOptions" default-time="23:59:59"></el-date-picker>
                    </div>
                </el-form-item>
                <el-form-item label="有效天数" v-if="form.termType===2">
                    <el-input-number v-model="form.termDays" :min="1" style="width:100%"></el-input-number>
                </el-form-item>
                <el-form-item label="适用范围">
                    <el-radio-group v-model="form.scopeType">
                        <el-radio :label="1">全部商品</el-radio>
                        <el-radio :label="2">指定商品</el-radio>
                    </el-radio-group>
                </el-form-item>
                <el-form-item label="选择商品" v-if="form.scopeType===2">
                    <div style="margin-bottom:8px;">
                        <el-input v-model="itemSearchKey" placeholder="搜索商品名称" size="small" style="width:200px;margin-right:8px;" clearable @clear="filterItems"></el-input>
                        <el-button size="small" @click="filterItems">搜索</el-button>
                        <el-checkbox v-model="selectAllItems" @change="toggleSelectAll" style="margin-left:12px;">全选</el-checkbox>
                    </div>
                    <el-checkbox-group v-model="form.selectedItemIds" style="max-height:200px;overflow-y:auto;border:1px solid #dcdfe6;border-radius:4px;padding:8px;">
                        <el-checkbox v-for="item in filteredItemList" :key="item.id" :label="item.id" style="display:block;margin:4px 0;">
                            {{item.name}} (ID:{{item.id}})
                        </el-checkbox>
                    </el-checkbox-group>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">已选 {{form.selectedItemIds.length}} 件商品</div>
                </el-form-item>
                <el-form-item label="优惠券类型">
                    <el-radio-group v-model="form.couponType">
                        <el-radio :label="1">普通优惠券</el-radio>
                        <el-radio :label="2">秒杀优惠券</el-radio>
                    </el-radio-group>
                </el-form-item>
                <!-- 秒杀优惠券额外设置 -->
                <template v-if="form.couponType===2">
                    <el-divider content-position="left">秒杀优惠券设置</el-divider>
                    <el-form-item label="秒杀库存" prop="seckillStock">
                        <el-input-number v-model="form.seckillStock" :min="1" :max="form.totalNum" style="width:100%"></el-input-number>
                        <div style="font-size:12px;color:#909399;margin-top:4px;" v-if="form.totalNum">发行总量: {{form.totalNum}}（秒杀库存不能超过发行总量）</div>
                    </el-form-item>
                    <el-form-item label="秒杀限领">
                        <el-input-number v-model="form.seckillMaxPerUser" :min="1" :max="1" :disabled="true" style="width:100%"></el-input-number>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">秒杀优惠券每人限领1张，不可修改</div>
                    </el-form-item>
                    <el-form-item label="秒杀时间">
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
        <el-dialog title="设为秒杀优惠券" :visible.sync="seckillDialogVisible" width="580px" :close-on-click-modal="false">
            <el-form :model="seckillForm" :rules="seckillFormRules" ref="seckillForm" label-width="110px">
                <p style="margin:0 0 15px;color:#909399;font-size:13px;">将优惠券设为秒杀类型，需设置秒杀相关信息。普通优惠券信息可选择修改。</p>
                <el-form-item label="优惠券名称">
                    <el-input v-model="seckillForm.name" placeholder="可修改"></el-input>
                </el-form-item>
                <el-form-item label="秒杀库存" prop="seckillStock">
                    <el-input-number v-model="seckillForm.seckillStock" :min="1" :max="seckillForm.totalCount" style="width:100%"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;" v-if="seckillForm.totalCount">发行总量: {{seckillForm.totalCount}}（秒杀库存不能超过发行总量）</div>
                </el-form-item>
                <el-form-item label="秒杀限领">
                    <el-input-number v-model="seckillForm.maxPerUser" :min="1" :max="1" :disabled="true" style="width:100%"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">秒杀优惠券每人限领1张，不可修改</div>
                </el-form-item>
                <el-form-item label="秒杀时间">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-date-picker v-model="seckillForm.rushBegin" type="datetime" placeholder="开抢时间" style="flex:1" :picker-options="sRushBeginPickerOptions" default-time="10:00:00"></el-date-picker>
                        <span style="color:#909399;">至</span>
                        <el-date-picker v-model="seckillForm.rushEnd" type="datetime" placeholder="结束时间" style="flex:1" :picker-options="sRushEndPickerOptions" default-time="22:00:00"></el-date-picker>
                    </div>
                </el-form-item>
                <el-form-item label="有效期">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <el-date-picker v-model="seckillForm.termBegin" type="datetime" placeholder="有效期开始" style="flex:1" :picker-options="sTermBeginPickerOptions" default-time="00:00:00"></el-date-picker>
                        <span style="color:#909399;">至</span>
                        <el-date-picker v-model="seckillForm.termEnd" type="datetime" placeholder="有效期结束" style="flex:1" :picker-options="sTermEndPickerOptions" default-time="23:59:59"></el-date-picker>
                    </div>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">选填，不修改则保留原有效期</div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="seckillDialogVisible=false">取 消</el-button>
                <el-button type="primary" @click="submitSeckill" :loading="seckillSubmitLoading">确 定</el-button>
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
            search: { status: null, couponType: null },
            dialogVisible: false,
            dialogTitle: '添加优惠券',
            submitLoading: false,
            form: this.getDefaultForm(),
            allItemList: [],
            filteredItemList: [],
            itemSearchKey: '',
            selectAllItems: false,
            couponStats: { totalIssued: 0, totalReceived: 0, totalUsed: 0, receiveRate: 0, useRate: 0 },
            formRules: {
                name: [{ required: true, message: '请输入优惠券名称', trigger: 'blur' }],
                discountType: [{ required: true, message: '请选择优惠类型', trigger: 'change' }],
                threshold: [{ required: true, message: '请输入使用门槛', trigger: 'blur' }],
                discountValue: [{ required: true, message: '请输入优惠额度', trigger: 'blur' }],
                totalNum: [{ required: true, message: '请输入发行总量', trigger: 'blur' }],
                userLimit: [{ required: true, message: '请输入限领数量', trigger: 'blur' }]
            },
            // 设为秒杀弹窗
            seckillDialogVisible: false,
            seckillSubmitLoading: false,
            seckillForm: { id: null, name: '', seckillStock: 10, maxPerUser: 1, rushBegin: null, rushEnd: null, termBegin: null, termEnd: null },
            seckillFormRules: {
                seckillStock: [{ required: true, message: '请输入秒杀库存', trigger: 'blur' }]
            }
        };
    },
    computed: {
        filteredData() {
            let list = this.tableData;
            if (this.search.status !== null && this.search.status !== '') {
                list = list.filter(item => item.status === this.search.status);
            }
            if (this.search.couponType !== null && this.search.couponType !== '') {
                list = list.filter(item => item.couponType === this.search.couponType);
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
        // ===== 添加/编辑弹窗的日期选择器 =====
        beginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        termEndPickerOptions() {
            const begin = this.form.termBegin ? new Date(this.form.termBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        },
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
        // ===== 设为秒杀弹窗的日期选择器 =====
        sRushBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        sRushEndPickerOptions() {
            const begin = this.seckillForm.rushBegin ? new Date(this.seckillForm.rushBegin) : null;
            return {
                disabledDate: time => {
                    if (begin) return time.getTime() < begin.getTime();
                    return time.getTime() < Date.now() - 86400000;
                }
            };
        },
        // ===== 设为秒杀弹窗的有效期日期选择器 =====
        sTermBeginPickerOptions() {
            return { disabledDate: time => time.getTime() < Date.now() - 86400000 };
        },
        sTermEndPickerOptions() {
            const begin = this.seckillForm.termBegin ? new Date(this.seckillForm.termBegin) : null;
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
        this.loadStats();
        this.loadAllItems();
    },
    methods: {
        formatMoney(val) { return ZM.formatMoney(val); },
        loadStats() {
            ZM.http.get('/coupons/admin/stats').then(res => {
                if (res) {
                    this.couponStats = {
                        totalIssued: res.totalIssued || 0,
                        totalReceived: res.totalReceived || 0,
                        totalUsed: res.totalUsed || 0,
                        receiveRate: res.receiveRate || 0,
                        useRate: res.useRate || 0
                    };
                }
            }).catch(() => {});
        },
        loadAllItems() {
            ZM.http.get('/items/admin/page', { params: { page: 1, size: 1000 } }).then(res => {
                let data = res;
                if (res && res.data && res.data.list) data = res.data;
                this.allItemList = data && data.list ? data.list : (Array.isArray(data) ? data : []);
                this.filteredItemList = [...this.allItemList];
            }).catch(() => {});
        },
        filterItems() {
            const key = (this.itemSearchKey || '').toLowerCase();
            if (!key) {
                this.filteredItemList = [...this.allItemList];
            } else {
                this.filteredItemList = this.allItemList.filter(i => (i.name || '').toLowerCase().includes(key));
            }
        },
        toggleSelectAll(val) {
            if (val) {
                this.form.selectedItemIds = this.filteredItemList.map(i => i.id);
            } else {
                this.form.selectedItemIds = [];
            }
        },
        getDefaultForm() {
            const now = new Date();
            now.setMinutes(now.getMinutes() + 10, 0, 0);
            const later = new Date(now.getTime() + 24 * 60 * 60 * 1000);
            return {
                id: null, name: '', discountType: 1, threshold: 100, discountValue: 10,
                purchasePrice: null,
                totalNum: 100, userLimit: 1, termType: 1, termBegin: now, termEnd: later, termDays: 7,
                couponType: 1, status: 1, scopeType: 1, selectedItemIds: [],
                seckillStock: 10, seckillMaxPerUser: 1, seckillBegin: null, seckillEnd: null
            };
        },
        loadList() {
            this.loading = true;
            ZM.http.get('/coupons/admin/page', { params: { page: 1, size: 99999 } }).then(res => {
                this.loading = false;
                let data = res;
                if (res && res.data && res.data.list) data = res.data;
                if (data && data.list) {
                    this.tableData = data.list;
                    this.total = data.total || 0;
                } else if (Array.isArray(res)) {
                    this.tableData = res;
                    this.total = res.length;
                } else {
                    this.tableData = [];
                    this.total = 0;
                }
            }).catch(() => { this.loading = false; });
        },
        resetSearch() {
            this.search = { status: null, couponType: null };
            this.currentPage = 1;
        },
        handleAdd() {
            this.dialogTitle = '添加优惠券';
            this.form = this.getDefaultForm();
            this.itemSearchKey = '';
            this.selectAllItems = false;
            this.dialogVisible = true;
        },
        handleEdit(row) {
            this.dialogTitle = '编辑优惠券';
            this.form = {
                id: row.id,
                name: row.name,
                discountType: row.type,
                threshold: row.thresholdAmount ? row.thresholdAmount / 100 : 0,
                discountValue: row.type === 1 ? (row.discountValue ? row.discountValue / 100 : 0) : (row.discountValue ? row.discountValue / 10 : 0),
                purchasePrice: row.purchasePrice ? row.purchasePrice / 100 : null,
                totalNum: row.totalCount,
                userLimit: row.perUserLimit,
                termType: row.validDays ? 2 : 1,
                termBegin: row.beginTime || null,
                termEnd: row.endTime || null,
                termDays: row.validDays || 7,
                couponType: row.couponType || 1,
                status: row.status,
                scopeType: row.scopeType || 1,
                selectedItemIds: row.itemIds || [],
                seckillStock: row.seckillStock || 10,
                seckillBegin: row.rushBeginTime || null,
                seckillEnd: row.rushEndTime || null
            };
            this.itemSearchKey = '';
            this.selectAllItems = false;
            this.dialogVisible = true;
        },
        submitForm() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                // 有效期起始时间校验（日期级约束由picker-options控制，精确时间由后端校验）
                if (this.form.termType === 1 && this.form.termBegin) {
                    if (new Date(this.form.termBegin).getTime() <= Date.now() + 300000) {
                        this.$message.warning('优惠开始时间请选择5分钟之后');
                        return;
                    }
                }
                // 秒杀券校验
                if (this.form.couponType === 2) {
                    if (!this.form.seckillStock || this.form.seckillStock <= 0) {
                        this.$message.warning('请设置秒杀库存');
                        return;
                    }
                    if (this.form.seckillStock > this.form.totalNum) {
                        this.$message.warning('秒杀库存不能超过发行总量');
                        return;
                    }
                    if (!this.form.seckillBegin || !this.form.seckillEnd) {
                        this.$message.warning('请设置秒杀时间');
                        return;
                    }
                }
                // 折扣券校验购买价格
                if (this.form.discountType === 2) {
                    if (!this.form.purchasePrice || this.form.purchasePrice <= 0) {
                        this.$message.warning('请设置购买价格');
                        return;
                    }
                }
                // 部分商品校验
                if (this.form.scopeType === 2 && this.form.selectedItemIds.length === 0) {
                    this.$message.warning('请选择适用商品');
                    return;
                }
                this.submitLoading = true;
                const data = {
                    name: this.form.name,
                    type: this.form.discountType,
                    thresholdAmount: this.form.discountType === 1 ? Math.round(this.form.threshold * 100) : 0,
                    purchasePrice: this.form.discountType === 2 ? Math.round(this.form.purchasePrice * 100) : 0,
                    discountValue: this.form.discountType === 1
                        ? Math.round(this.form.discountValue * 100)
                        : Math.round(this.form.discountValue * 10),
                    totalCount: this.form.totalNum,
                    perUserLimit: this.form.userLimit,
                    couponType: this.form.couponType,
                    status: this.form.status || 1,
                    scopeType: this.form.scopeType,
                    itemIds: this.form.scopeType === 2 ? this.form.selectedItemIds : null
                };
                if (this.form.termType === 1 && this.form.termBegin && this.form.termEnd) {
                    data.beginTime = this.formatDateForApi(this.form.termBegin);
                    data.endTime = this.formatDateForApi(this.form.termEnd);
                } else if (this.form.termType === 2) {
                    data.validDays = this.form.termDays;
                }
                // 秒杀信息
                if (this.form.couponType === 2) {
                    // 校验：开抢时间须在5分钟之后
                    if (this.form.seckillBegin && new Date(this.form.seckillBegin).getTime() <= Date.now() + 300000) {
                        this.$message.warning('开抢时间请选择5分钟之后');
                        this.submitLoading = false;
                        return;
                    }
                    data.seckillStock = this.form.seckillStock;
                    data.maxPerUser = 1;
                    if (this.form.seckillBegin && this.form.seckillEnd) {
                        data.rushBeginTime = this.formatDateForApi(this.form.seckillBegin);
                        data.rushEndTime = this.formatDateForApi(this.form.seckillEnd);
                    }
                }
                const req = this.form.id
                    ? ZM.http.put('/coupons/admin/' + this.form.id, data)
                    : ZM.http.post('/coupons/admin', data);
                req.then(() => {
                    this.submitLoading = false;
                    this.$message.success(this.form.id ? '修改成功' : '添加成功');
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
        toggleStatus(row) {
            const newStatus = row.status === 1 ? 2 : 1;
            const action = newStatus === 1 ? '上架' : '下架';
            this.$confirm('确定要' + action + '该优惠券吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/coupons/admin/' + row.id + '/status/' + newStatus).then(() => {
                    this.$message.success(action + '成功');
                    this.loadList();
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        },
        handleSetSeckill(row) {
            if (row.couponType === 2) {
                this.seckillForm = {
                    id: row.id,
                    name: row.name,
                    totalCount: row.totalCount,
                    seckillStock: row.seckillStock || 10,
                    maxPerUser: 1,
                    rushBegin: row.rushBeginTime || null,
                    rushEnd: row.rushEndTime || null,
                    termBegin: row.beginTime || null,
                    termEnd: row.endTime || null
                };
            } else {
                this.seckillForm = {
                    id: row.id,
                    name: row.name,
                    totalCount: row.totalCount,
                    seckillStock: 10,
                    maxPerUser: 1,
                    rushBegin: null,
                    rushEnd: null,
                    termBegin: row.beginTime || null,
                    termEnd: row.endTime || null
                };
            }
            this.seckillDialogVisible = true;
        },
        submitSeckill() {
            this.$refs.seckillForm.validate(valid => {
                if (!valid) return;
                if (!this.seckillForm.rushBegin || !this.seckillForm.rushEnd) {
                    this.$message.warning('请选择秒杀时间');
                    return;
                }
                if (new Date(this.seckillForm.rushBegin).getTime() <= Date.now() + 300000) {
                    this.$message.warning('开抢时间请选择5分钟之后');
                    return;
                }
                if (this.seckillForm.totalCount && this.seckillForm.seckillStock > this.seckillForm.totalCount) {
                    this.$message.warning('秒杀库存不能超过发行总量(' + this.seckillForm.totalCount + ')');
                    return;
                }
                // 校验秒杀时间在有效期内
                if (this.seckillForm.termBegin && new Date(this.seckillForm.rushBegin).getTime() < new Date(this.seckillForm.termBegin).getTime()) {
                    this.$message.warning('开抢时间不能早于有效期开始时间');
                    return;
                }
                if (this.seckillForm.termEnd && new Date(this.seckillForm.rushEnd).getTime() > new Date(this.seckillForm.termEnd).getTime()) {
                    this.$message.warning('秒杀结束时间不能晚于有效期结束时间');
                    return;
                }
                this.seckillSubmitLoading = true;
                const data = {
                    couponType: 2,
                    seckillStock: this.seckillForm.seckillStock,
                    maxPerUser: 1,
                    rushBeginTime: this.formatDateForApi(this.seckillForm.rushBegin),
                    rushEndTime: this.formatDateForApi(this.seckillForm.rushEnd)
                };
                if (this.seckillForm.name) data.name = this.seckillForm.name;
                if (this.seckillForm.termBegin) data.beginTime = this.formatDateForApi(this.seckillForm.termBegin);
                if (this.seckillForm.termEnd) data.endTime = this.formatDateForApi(this.seckillForm.termEnd);
                ZM.http.put('/coupons/admin/' + this.seckillForm.id + '/seckill', data).then(() => {
                    this.seckillSubmitLoading = false;
                    this.$message.success('秒杀设置成功');
                    this.seckillDialogVisible = false;
                    this.loadList();
                }).catch(() => {
                    this.seckillSubmitLoading = false;
                    this.$message.error('操作失败');
                });
            });
        },
        handleDelete(row) {
            this.$confirm('确定要删除该优惠券吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/coupons/admin/' + row.id).then(() => {
                    this.$message.success('删除成功');
                    this.loadList();
                }).catch(() => { this.$message.error('删除失败'); });
            }).catch(() => {});
        }
    }
});
