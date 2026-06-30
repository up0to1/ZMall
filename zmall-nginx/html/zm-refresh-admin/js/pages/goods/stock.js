// 库存管理页面组件
Vue.component('goods-stock-page', {
    template: `
    <div>
        <!-- 低库存预警 -->
        <div class="page-card" style="margin-bottom:20px;">
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;">
                <h3><i class="el-icon-warning" style="color:#e54346;"></i> 低库存预警</h3>
                <div>
                    <span style="font-size:13px;color:#909399;margin-right:10px;">预警阈值</span>
                    <el-input-number v-model="threshold" :min="1" :max="1000" size="small" style="width:120px;"></el-input-number>
                    <el-button type="danger" size="small" @click="loadLowStock" style="margin-left:10px;">查询</el-button>
                </div>
            </div>
            <el-table :data="lowStockItems" v-loading="lowLoading" size="small" style="width:100%;">
                <el-table-column prop="id" label="商品ID" width="120"></el-table-column>
                <el-table-column prop="name" label="商品名称" min-width="200" show-overflow-tooltip></el-table-column>
                <el-table-column prop="category" label="分类" width="100"></el-table-column>
                <el-table-column prop="stock" label="当前库存" width="100">
                    <template slot-scope="scope">
                        <span style="color:#e54346;font-weight:bold;">{{scope.row.stock}}</span>
                    </template>
                </el-table-column>
                <el-table-column prop="sold" label="销量" width="80"></el-table-column>
                <el-table-column label="操作" width="200">
                    <template slot-scope="scope">
                        <el-button type="text" size="small" @click="openAdjust(scope.row)">补货</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div v-if="!lowLoading && lowStockItems.length===0" style="text-align:center;padding:20px;color:#67c23a;">
                <i class="el-icon-success"></i> 暂无低库存商品
            </div>
        </div>

        <!-- 库存列表 -->
        <div class="page-card">
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;">
                <h3>库存管理</h3>
                <el-input v-model="keyword" placeholder="搜索商品名称" size="small" style="width:220px;" clearable prefix-icon="el-icon-search" @clear="currentPage=1;loadStock()" @keyup.enter.native="currentPage=1;loadStock()">
                </el-input>
            </div>
            <el-table :data="stockList" v-loading="stockLoading" size="small" style="width:100%;">
                <el-table-column prop="id" label="商品ID" width="120"></el-table-column>
                <el-table-column prop="name" label="商品名称" min-width="200" show-overflow-tooltip></el-table-column>
                <el-table-column prop="category" label="分类" width="100"></el-table-column>
                <el-table-column prop="price" label="价格(分)" width="100"></el-table-column>
                <el-table-column prop="stock" label="库存" width="100">
                    <template slot-scope="scope">
                        <span :style="{color: scope.row.stock <= threshold ? '#e54346' : '#67c23a', fontWeight:'bold'}">{{scope.row.stock}}</span>
                    </template>
                </el-table-column>
                <el-table-column prop="sold" label="销量" width="80"></el-table-column>
                <el-table-column label="商品状态" width="100">
                    <template slot-scope="scope">
                        <el-tag :type="scope.row.status===1?'success':'info'" size="mini">{{scope.row.status===1?'上架':'下架'}}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="200">
                    <template slot-scope="scope">
                        <el-button type="text" size="small" @click="openAdjust(scope.row)">调整库存</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div style="margin-top:15px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{stockTotal}} 条 / 共 {{stockTotalPages}} 页，当前第 {{currentPage}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :pager-count="11" :total="stockTotal" :page-size="pageSize" :current-page.sync="currentPage" @current-change="loadStock"></el-pagination>
            </div>
        </div>

        <!-- 库存调整对话框 -->
        <el-dialog title="调整库存" :visible.sync="adjustVisible" width="450px">
            <div v-if="adjustItem" style="margin-bottom:15px;">
                <p><strong>商品：</strong>{{adjustItem.name}}</p>
                <p><strong>当前库存：</strong>{{adjustItem.stock}}</p>
            </div>
            <el-form label-width="100px">
                <el-form-item label="设置库存">
                    <el-input-number v-model="targetStock" :min="0" :step="10" style="width:200px;"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:5px;">设置为0则商品在前端显示为暂时缺货</div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="adjustVisible=false">取消</el-button>
                <el-button type="primary" @click="doAdjust" :loading="adjustLoading">确认</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            threshold: 10,
            lowStockItems: [],
            lowLoading: false,
            stockList: [],
            stockLoading: false,
            stockTotal: 0,
            currentPage: 1,
            pageSize: 10,
            keyword: '',
            adjustVisible: false,
            adjustItem: null,
            targetStock: 0,
            adjustLoading: false
        };
    },
    computed: {
        stockTotalPages() { return Math.ceil(this.stockTotal / this.pageSize) || 1; }
    },
    watch: {
        currentPage(val) {
            if (val > this.stockTotalPages) {
                this.$nextTick(() => { this.currentPage = this.stockTotalPages; });
            } else if (val < 1) {
                this.$nextTick(() => { this.currentPage = 1; });
            }
        }
    },
    mounted() {
        this.loadLowStock();
        this.loadStock();
    },
    methods: {
        loadLowStock() {
            this.lowLoading = true;
            ZM.http.get('/items/admin/stock/low', { params: { threshold: this.threshold } }).then(res => {
                console.log('[低库存] 响应:', JSON.stringify(res));
                let data = res;
                if (res && res.data && Array.isArray(res.data)) data = res.data;
                this.lowStockItems = Array.isArray(data) ? data : (data && data.list ? data.list : []);
                this.lowLoading = false;
            }).catch(err => {
                this.lowLoading = false;
                console.error('[低库存] 请求失败:', err);
                const status = err.response && err.response.status;
                if (status === 403) {
                    this.$message.error('无权限访问，请重新登录');
                    setTimeout(() => { ZM.clearLogin(); window.location.href = '/login.html'; }, 1500);
                }
            });
        },
        loadStock() {
            this.stockLoading = true;
            const params = { page: this.currentPage, size: this.pageSize };
            if (this.keyword) params.keyword = this.keyword;
            ZM.http.get('/items/admin/stock/page', {
                params: params
            }).then(res => {
                let data = res;
                if (res && res.data && res.data.list) data = res.data;
                this.stockList = data && data.list ? data.list : (Array.isArray(data) ? data : []);
                this.stockTotal = data && data.total ? data.total : 0;
                this.stockLoading = false;
            }).catch(err => {
                this.stockLoading = false;
                const status = err.response && err.response.status;
                if (status === 403) {
                    this.$message.error('无权限访问，请重新登录');
                    setTimeout(() => { ZM.clearLogin(); window.location.href = '/login.html'; }, 1500);
                }
            });
        },
        openAdjust(item) {
            this.adjustItem = item;
            this.targetStock = item.stock;
            this.adjustVisible = true;
        },
        doAdjust() {
            if (this.targetStock < 0) {
                this.$message.warning('库存不能为负数');
                return;
            }
            if (this.targetStock === this.adjustItem.stock) {
                this.$message.warning('库存未变化');
                return;
            }
            this.adjustLoading = true;
            ZM.http.put('/items/admin/stock/adjust/' + this.adjustItem.id + '?targetStock=' + this.targetStock).then(() => {
                this.adjustLoading = false;
                this.$message.success('库存设置成功');
                this.adjustVisible = false;
                this.loadStock();
                this.loadLowStock();
            }).catch(() => {
                this.adjustLoading = false;
                this.$message.error('库存设置失败');
            });
        }
    }
});
