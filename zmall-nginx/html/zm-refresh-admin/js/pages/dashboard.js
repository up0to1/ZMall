// 仪表盘页面组件
Vue.component('dashboard-page', {
    template: `
    <div class="dashboard-container">
        <!-- 统计卡片 -->
        <div class="stat-cards">
            <div class="stat-card">
                <div class="stat-icon red"><i class="el-icon-s-order"></i></div>
                <div class="stat-info">
                    <div class="stat-label">今日订单</div>
                    <div class="stat-value">{{stats.todayOrders}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon blue"><i class="el-icon-coin"></i></div>
                <div class="stat-info">
                    <div class="stat-label">今日销售额</div>
                    <div class="stat-value">&yen;{{stats.todaySales}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green"><i class="el-icon-user"></i></div>
                <div class="stat-info">
                    <div class="stat-label">今日新增粉丝</div>
                    <div class="stat-value">{{stats.todayNewFans}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon orange"><i class="el-icon-goods"></i></div>
                <div class="stat-info">
                    <div class="stat-label">在售商品</div>
                    <div class="stat-value">{{stats.totalItems}}</div>
                </div>
            </div>
        </div>

        <!-- 图表区域 -->
        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title">销售趋势（近7天）</div>
                <div id="salesChart" style="height:350px;"></div>
            </div>
            <div class="chart-card">
                <div class="chart-title">商品类别分布</div>
                <div id="categoryChart" style="height:350px;"></div>
            </div>
        </div>

        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title">订单状态分布</div>
                <div id="orderStatusChart" style="height:350px;"></div>
            </div>
            <div class="chart-card">
                <div class="chart-title">热销商品 TOP5</div>
                <div id="topItemsChart" style="height:350px;"></div>
            </div>
        </div>

        <!-- 秒杀活动数据 -->
        <div class="chart-row" v-if="seckillStats.length > 0">
            <div class="chart-card" style="flex:1;">
                <div class="chart-title">秒杀活动数据</div>
                <el-table :data="seckillStats" size="small" style="width:100%;">
                    <el-table-column prop="itemName" label="商品名称" min-width="160" show-overflow-tooltip></el-table-column>
                    <el-table-column prop="totalStock" label="总库存" width="100" align="center"></el-table-column>
                    <el-table-column prop="soldCount" label="已售数量" width="100" align="center">
                        <template slot-scope="scope">
                            <span style="color:#e54346;font-weight:bold;">{{scope.row.soldCount}}</span>
                        </template>
                    </el-table-column>
                    <el-table-column label="售罄率" width="180" align="center">
                        <template slot-scope="scope">
                            <el-progress :percentage="scope.row.sellOutRate || 0" :color="scope.row.sellOutRate > 80 ? '#e54346' : scope.row.sellOutRate > 50 ? '#f39c12' : '#67c23a'" :stroke-width="14" :text-inside="true"></el-progress>
                        </template>
                    </el-table-column>
                </el-table>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            stats: {
                todayOrders: 0,
                todaySales: '0.00',
                todayNewFans: 0,
                totalItems: 0
            },
            seckillStats: []
        };
    },
    mounted() {
        this.loadDashboard();
    },
    methods: {
        loadDashboard() {
            // 加载今日概览
            ZM.http.get('/merchant/dashboard/today').then(res => {
                if (res) {
                    this.stats.todayOrders = res.todayOrders || 0;
                    this.stats.todaySales = ZM.formatMoney(res.todaySales);
                    this.stats.todayNewFans = res.todayNewFans || 0;
                    this.stats.totalItems = res.totalItems || 0;
                }
            }).catch(() => {});

            // 加载销售趋势
            ZM.http.get('/merchant/dashboard/sales').then(res => {
                this.renderSalesChart(res || []);
            }).catch(() => { this.renderSalesChart([]); });

            // 加载商品类别分布（按分类统计商品数量）
            ZM.http.get('/categories').then(res => {
                const list = Array.isArray(res) ? res : (res.list || []);
                this.renderCategoryChart(list);
            }).catch(() => { this.renderCategoryChart([]); });

            // 加载热销商品
            ZM.http.get('/merchant/dashboard/top-items').then(res => {
                this.renderTopItemsChart(res || []);
            }).catch(() => { this.renderTopItemsChart([]); });

            // 加载订单状态分布
            ZM.http.get('/orders/merchant/stats').then(res => {
                this.renderOrderStatusChart(res || {});
            }).catch(() => { this.renderOrderStatusChart({}); });

            // 加载秒杀活动数据
            ZM.http.get('/merchant/dashboard/seckill').then(res => {
                this.seckillStats = Array.isArray(res) ? res : [];
            }).catch(() => { this.seckillStats = []; });
        },
        renderSalesChart(data) {
            const chart = echarts.init(document.getElementById('salesChart'));
            // data是List<SalesTrendDTO>，每个元素有date/sales/orders
            const list = Array.isArray(data) ? data : [];
            const days = list.map(d => d.date || '');
            const salesData = list.map(d => d.sales ? d.sales / 100 : 0);
            const orderData = list.map(d => d.orders || 0);
            // 如果没有数据，显示近7天空数据
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
                        name: '销售额', type: 'line', smooth: true,
                        data: salesData,
                        itemStyle: { color: '#e54346' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(229,67,70,0.3)' },
                            { offset: 1, color: 'rgba(229,67,70,0.05)' }
                        ])}
                    },
                    {
                        name: '订单量', type: 'line', smooth: true, yAxisIndex: 1,
                        data: orderData,
                        itemStyle: { color: '#3498db' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(52,152,219,0.3)' },
                            { offset: 1, color: 'rgba(52,152,219,0.05)' }
                        ])}
                    }
                ]
            });
            window.addEventListener('resize', () => chart.resize());
        },
        renderCategoryChart(list) {
            const chart = echarts.init(document.getElementById('categoryChart'));
            // list是分类列表，每个元素有name字段
            const categoryData = Array.isArray(list) && list.length > 0
                ? list.map(c => ({ name: c.name, value: c.itemCount || c.count || 1 }))
                : [
                    { name: '手机数码', value: 35 },
                    { name: '家用电器', value: 25 },
                    { name: '服饰鞋包', value: 20 },
                    { name: '食品生鲜', value: 12 },
                    { name: '其他', value: 8 }
                ];
            chart.setOption({
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: { orient: 'vertical', left: 'left', top: 'center' },
                series: [{
                    type: 'pie',
                    radius: ['40%', '70%'],
                    center: ['60%', '50%'],
                    avoidLabelOverlap: false,
                    itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
                    label: { show: true, formatter: '{b}\n{d}%' },
                    data: categoryData,
                    color: ['#e54346', '#3498db', '#27ae60', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22']
                }]
            });
            window.addEventListener('resize', () => chart.resize());
        },
        renderOrderStatusChart(data) {
            const chart = echarts.init(document.getElementById('orderStatusChart'));
            // data是OrderStatsDTO，有todayNew/pendingShip/shipped/refunding/todaySales
            const statusData = [
                { name: '今日新订单', value: data.todayNew || 0 },
                { name: '待发货', value: data.pendingShip || 0 },
                { name: '已发货', value: data.shipped || 0 },
                { name: '退款中', value: data.refunding || 0 }
            ].filter(d => d.value > 0);
            if (statusData.length === 0) {
                statusData.push({ name: '暂无订单', value: 1 });
            }
            chart.setOption({
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: { orient: 'vertical', left: 'left', top: 'center' },
                series: [{
                    type: 'pie',
                    radius: '65%',
                    center: ['60%', '50%'],
                    data: statusData,
                    color: ['#f39c12', '#e54346', '#3498db', '#27ae60', '#95a5a6', '#9b59b6'],
                    label: { show: true, formatter: '{b}: {c}' },
                    itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 }
                }]
            });
            window.addEventListener('resize', () => chart.resize());
        },
        renderTopItemsChart(data) {
            const chart = echarts.init(document.getElementById('topItemsChart'));
            // data是List<TopItemDTO>，每个元素有name/sold/totalSales
            const items = Array.isArray(data) ? data : [];
            const names = items.map(i => i.name || '商品').slice(0, 5);
            const values = items.map(i => i.sold || i.totalSales || 0).slice(0, 5);
            // 如果没有数据，展示默认
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
                            { offset: 0, color: '#e54346' },
                            { offset: 1, color: '#f39c12' }
                        ]),
                        borderRadius: [0, 4, 4, 0]
                    },
                    barWidth: 20,
                    label: { show: true, position: 'right', formatter: '{c}' }
                }]
            });
            window.addEventListener('resize', () => chart.resize());
        }
    }
});
