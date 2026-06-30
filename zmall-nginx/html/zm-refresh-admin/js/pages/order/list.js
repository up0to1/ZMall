// 订单列表页面组件
Vue.component('order-list-page', {
    template: `
    <div>
        <!-- 订单统计卡片 -->
        <div class="stat-cards" style="margin-bottom:16px;">
            <div class="stat-card">
                <div class="stat-icon red"><i class="el-icon-s-order"></i></div>
                <div class="stat-info">
                    <div class="stat-label">今日新单</div>
                    <div class="stat-value">{{orderStats.todayNew || 0}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon orange"><i class="el-icon-time"></i></div>
                <div class="stat-info">
                    <div class="stat-label">待发货</div>
                    <div class="stat-value">{{orderStats.pendingShip || 0}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon blue"><i class="el-icon-truck"></i></div>
                <div class="stat-info">
                    <div class="stat-label">已发货</div>
                    <div class="stat-value">{{orderStats.shipped || 0}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green"><i class="el-icon-circle-check"></i></div>
                <div class="stat-info">
                    <div class="stat-label">退货审核中</div>
                    <div class="stat-value">{{orderStats.refunding || 0}}</div>
                </div>
            </div>
        </div>

        <div class="page-card">
            <div class="page-header">
                <h3>订单列表</h3>
            </div>
            <!-- 搜索栏 -->
            <div class="search-bar">
                <el-input v-model="search.orderId" placeholder="订单号" size="small" clearable></el-input>
                <el-select v-model="search.status" placeholder="订单状态" size="small" clearable>
                    <el-option label="待付款" :value="1"></el-option>
                    <el-option label="待发货" :value="2"></el-option>
                    <el-option label="已到货" :value="3"></el-option>
                    <el-option label="已完成" :value="4"></el-option>
                    <el-option label="已关闭" :value="5"></el-option>
                    <el-option label="已评价" :value="6"></el-option>
                    <el-option label="退货审核中" :value="7"></el-option>
                    <el-option label="退货被拒绝" :value="8"></el-option>
                </el-select>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <!-- 表格 -->
            <el-table :data="pagedData" border stripe v-loading="loading" style="width:100%">
                <el-table-column prop="id" label="订单号" width="180" align="center"></el-table-column>
                <el-table-column label="下单用户" width="100" align="center">
                    <template slot-scope="scope">
                        <span>{{scope.row.userId || '-'}}</span>
                    </template>
                </el-table-column>
                <el-table-column label="商品信息" min-width="200">
                    <template slot-scope="scope">
                        <span>{{scope.row.itemName || '-'}}</span>
                        <span v-if="scope.row.itemCount"> ({{scope.row.itemCount}}件)</span>
                    </template>
                </el-table-column>
                <el-table-column label="订单金额" width="110" align="center">
                    <template slot-scope="scope">&yen;{{formatMoney(scope.row.totalFee)}}</template>
                </el-table-column>
                <el-table-column label="状态" width="100" align="center">
                    <template slot-scope="scope">
                        <el-tag :type="statusTagType(scope.row.status)" size="small">{{statusText(scope.row.status)}}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="下单时间" width="170" align="center">
                    <template slot-scope="scope">{{formatDate(scope.row.createTime || scope.row.createdTime)}}</template>
                </el-table-column>
                <el-table-column label="操作" width="280" align="center" fixed="right">
                    <template slot-scope="scope">
                        <el-button size="mini" @click="viewDetail(scope.row)">详情</el-button>
                        <el-button size="mini" type="primary" v-if="scope.row.status===2" @click="handleShip(scope.row)">发货</el-button>
                        <el-button size="mini" type="success" v-if="scope.row.status===7" @click="handleApproveReturn(scope.row)">通过退货</el-button>
                        <el-button size="mini" type="danger" v-if="scope.row.status===7" @click="handleRejectReturn(scope.row)">拒绝退货</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <!-- 分页 -->
            <div style="margin-top:16px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>

        <!-- 订单详情弹窗 -->
        <el-dialog title="订单详情" :visible.sync="detailVisible" width="700px">
            <div class="order-detail" v-if="currentOrder">
                <div class="detail-row"><div class="detail-label">订单号：</div><div class="detail-value">{{currentOrder.id}}</div></div>
                <div class="detail-row"><div class="detail-label">下单用户：</div><div class="detail-value">{{currentOrder.userId}}</div></div>
                <div class="detail-row"><div class="detail-label">订单状态：</div><div class="detail-value"><el-tag :type="statusTagType(currentOrder.status)" size="small">{{statusText(currentOrder.status)}}</el-tag></div></div>
                <div class="detail-row"><div class="detail-label">订单金额：</div><div class="detail-value" style="color:#e54346;font-weight:bold;">&yen;{{formatMoney(currentOrder.totalFee)}}</div></div>
                <div class="detail-row"><div class="detail-label">下单时间：</div><div class="detail-value">{{formatDate(currentOrder.createTime || currentOrder.createdTime)}}</div></div>
                <div class="detail-row"><div class="detail-label">支付时间：</div><div class="detail-value">{{formatDate(currentOrder.payTime || currentOrder.paymentTime)}}</div></div>
                <div class="detail-row" v-if="currentOrder.consignTime"><div class="detail-label">发货时间：</div><div class="detail-value">{{formatDate(currentOrder.consignTime)}}</div></div>
                <div class="detail-row" v-if="currentOrder.closeTime"><div class="detail-label">关闭时间：</div><div class="detail-value">{{formatDate(currentOrder.closeTime)}}</div></div>
                <el-divider></el-divider>
                <h4 style="margin-bottom:10px;">商品列表</h4>
                <el-table :data="currentOrder.orderDetails || []" border size="small">
                    <el-table-column prop="name" label="商品名称" min-width="150"></el-table-column>
                    <el-table-column prop="price" label="单价" width="100" align="center">
                        <template slot-scope="scope">&yen;{{formatMoney(scope.row.price)}}</template>
                    </el-table-column>
                    <el-table-column prop="num" label="数量" width="80" align="center"></el-table-column>
                    <el-table-column label="小计" width="100" align="center">
                        <template slot-scope="scope">&yen;{{formatMoney(scope.row.price * scope.row.num)}}</template>
                    </el-table-column>
                </el-table>
            </div>
        </el-dialog>

        <!-- 销售趋势与热销商品 -->
        <div class="chart-row" style="display:flex;gap:15px;margin-top:16px;">
            <div class="page-card" style="flex:1;">
                <div style="font-size:15px;font-weight:bold;margin-bottom:10px;">销售趋势（近7天）</div>
                <div id="orderSalesChart" style="height:320px;"></div>
            </div>
            <div class="page-card" style="flex:1;">
                <div style="font-size:15px;font-weight:bold;margin-bottom:10px;">热销商品排行</div>
                <div id="orderTopItemsChart" style="height:320px;"></div>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            loading: false,
            tableData: [],
            total: 0,
            currentPage: 1,
            pageSize: 10,
            search: { orderId: '', status: null },
            orderStats: { todayNew: 0, pendingShip: 0, shipped: 0, refunding: 0 },
            detailVisible: false,
            currentOrder: null
        };
    },
    computed: {
        filteredData() {
            let list = this.tableData;
            if (this.search.orderId) {
                const key = String(this.search.orderId);
                list = list.filter(item => String(item.id).includes(key));
            }
            if (this.search.status !== null && this.search.status !== '') {
                list = list.filter(item => item.status === this.search.status);
            }
            return list;
        },
        filteredTotal() {
            return this.filteredData.length;
        },
        pagedData() {
            const start = (this.currentPage - 1) * this.pageSize;
            return this.filteredData.slice(start, start + this.pageSize);
        }
    },
    mounted() {
        this.loadList();
        this.loadStats();
        this.loadSalesTrend();
        this.loadTopItems();
    },
    methods: {
        formatMoney(val) { return ZM.formatMoney(val); },
        formatDate(val) { return ZM.formatDate(val); },
        statusText(s) {
            const map = { 1: '待付款', 2: '待发货', 3: '已到货', 4: '已完成', 5: '已关闭', 6: '已评价', 7: '退货审核中', 8: '退货被拒绝' };
            return map[s] || '未知';
        },
        statusTagType(s) {
            const map = { 1: 'warning', 2: 'danger', 3: '', 4: 'success', 5: 'info', 6: 'success', 7: 'warning', 8: 'danger' };
            return map[s] || '';
        },
        loadList() {
            this.loading = true;
            ZM.http.get('/orders/merchant/page', { params: { page: 1, size: 99999 } }).then(res => {
                this.loading = false;
                if (res && res.list) {
                    this.tableData = res.list;
                    this.total = res.total || 0;
                } else if (Array.isArray(res)) {
                    this.tableData = res;
                    this.total = res.length;
                }
            }).catch(() => { this.loading = false; });
        },
        loadStats() {
            ZM.http.get('/orders/merchant/stats').then(res => {
                if (res) {
                    this.orderStats = {
                        total: res.todayNew || 0,
                        pendingShip: res.pendingShip || 0,
                        shipped: res.shipped || 0,
                        completed: res.refunding || 0
                    };
                }
            }).catch(() => {});
        },
        resetSearch() {
            this.search = { orderId: '', status: null };
            this.currentPage = 1;
        },
        viewDetail(row) {
            ZM.http.get('/orders/merchant/' + row.id).then(res => {
                this.currentOrder = res || row;
                this.detailVisible = true;
            }).catch(() => {
                this.currentOrder = row;
                this.detailVisible = true;
            });
        },
        handleShip(row) {
            this.$confirm('确定要发货吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/orders/merchant/' + row.id + '/ship').then(() => {
                    this.$message.success('发货成功');
                    this.loadList();
                    this.loadStats();
                }).catch(() => { this.$message.error('发货失败'); });
            }).catch(() => {});
        },
        handleRefund(row) {
            this.$confirm('确定要退款吗？退款后不可撤销', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/orders/merchant/' + row.id + '/refund').then(() => {
                    this.$message.success('退款成功');
                    this.loadList();
                    this.loadStats();
                }).catch(() => { this.$message.error('退款失败'); });
            }).catch(() => {});
        },
        handleApproveReturn(row) {
            this.$confirm('确定通过退货申请？将自动退款并恢复库存', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/orders/merchant/' + row.id + '/approve-return').then(() => {
                    this.$message.success('已通过退货申请');
                    this.loadList();
                    this.loadStats();
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        },
        handleRejectReturn(row) {
            this.$confirm('确定拒绝退货申请？用户可再次申请退货', '提示', { type: 'warning' }).then(() => {
                ZM.http.put('/orders/merchant/' + row.id + '/reject-return').then(() => {
                    this.$message.success('已拒绝退货申请');
                    this.loadList();
                    this.loadStats();
                }).catch(() => { this.$message.error('操作失败'); });
            }).catch(() => {});
        },
        loadSalesTrend() {
            ZM.http.get('/orders/merchant/sales-trend').then(res => {
                this.renderSalesTrendChart(res || []);
            }).catch(() => { this.renderSalesTrendChart([]); });
        },
        renderSalesTrendChart(data) {
            const chartDom = document.getElementById('orderSalesChart');
            if (!chartDom) return;
            const chart = echarts.init(chartDom);
            const list = Array.isArray(data) ? data : [];
            const days = list.map(d => d.date || '');
            const salesData = list.map(d => d.sales ? d.sales / 100 : 0);
            const orderData = list.map(d => d.orders || 0);
            if (days.length === 0) {
                const now = new Date();
                for (let i = 6; i >= 0; i--) {
                    const d = new Date(now);
                    d.setDate(d.getDate() - i);
                    days.push((d.getMonth() + 1) + '/' + d.getDate());
                    salesData.push(0);
                    orderData.push(0);
                }
            }
            chart.setOption({
                tooltip: { trigger: 'axis' },
                legend: { data: ['销售额', '订单量'] },
                grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                xAxis: { type: 'category', data: days, boundaryGap: false },
                yAxis: [
                    { type: 'value', name: '销售额(元)', position: 'left' },
                    { type: 'value', name: '订单量', position: 'right' }
                ],
                series: [
                    {
                        name: '销售额', type: 'line', smooth: true, data: salesData,
                        itemStyle: { color: '#e54346' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(229,67,70,0.3)' },
                            { offset: 1, color: 'rgba(229,67,70,0.05)' }
                        ])}
                    },
                    {
                        name: '订单量', type: 'line', smooth: true, yAxisIndex: 1, data: orderData,
                        itemStyle: { color: '#409eff' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(64,158,255,0.3)' },
                            { offset: 1, color: 'rgba(64,158,255,0.05)' }
                        ])}
                    }
                ]
            });
            window.addEventListener('resize', () => chart.resize());
        },
        loadTopItems() {
            ZM.http.get('/orders/merchant/top-items').then(res => {
                this.renderTopItemsChart(res || []);
            }).catch(() => { this.renderTopItemsChart([]); });
        },
        renderTopItemsChart(data) {
            const chartDom = document.getElementById('orderTopItemsChart');
            if (!chartDom) return;
            const chart = echarts.init(chartDom);
            const items = Array.isArray(data) ? data.slice(0, 5) : [];
            const names = items.map(i => i.name || '商品');
            const values = items.map(i => i.sold || 0);
            if (names.length === 0) {
                names.push('暂无数据');
                values.push(0);
            }
            chart.setOption({
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '10%', bottom: '3%', containLabel: true },
                xAxis: { type: 'value' },
                yAxis: { type: 'category', data: names.reverse(), axisLabel: { width: 80, overflow: 'truncate' } },
                series: [{
                    type: 'bar',
                    data: values.reverse(),
                    itemStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                            { offset: 0, color: '#409eff' },
                            { offset: 1, color: '#67c23a' }
                        ]),
                        borderRadius: [0, 4, 4, 0]
                    },
                    barWidth: 20,
                    label: { show: true, position: 'right', formatter: '{c}件' }
                }]
            });
            window.addEventListener('resize', () => chart.resize());
        }
    }
});
