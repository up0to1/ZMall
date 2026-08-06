// 利润统计页面组件（含运费/成本/利润）
Vue.component('profit-stats-page', {
    template: `
    <div>
        <!-- 概览卡片 -->
        <div class="stat-cards" style="margin-bottom:16px;">
            <div class="stat-card">
                <div class="stat-icon blue"><i class="el-icon-coin"></i></div>
                <div class="stat-info">
                    <div class="stat-label">销售额</div>
                    <div class="stat-value">&yen;{{formatMoney(stats.totalSales)}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon orange"><i class="el-icon-goods"></i></div>
                <div class="stat-info">
                    <div class="stat-label">商品成本</div>
                    <div class="stat-value">&yen;{{formatMoney(stats.totalCost)}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green"><i class="el-icon-truck"></i></div>
                <div class="stat-info">
                    <div class="stat-label">运费成本</div>
                    <div class="stat-value">&yen;{{formatMoney(stats.totalShippingFee)}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon red"><i class="el-icon-trophy"></i></div>
                <div class="stat-info">
                    <div class="stat-label">净利润</div>
                    <div class="stat-value" style="color:#e54346;">&yen;{{formatMoney(stats.netProfit)}}</div>
                </div>
            </div>
        </div>

        <div class="page-card">
            <div class="page-header">
                <h3>利润统计</h3>
                <div style="display:flex;align-items:center;gap:8px;">
                    <el-radio-group v-model="days" size="small" @change="loadStats">
                        <el-radio-button :label="7">近7天</el-radio-button>
                        <el-radio-button :label="30">近30天</el-radio-button>
                        <el-radio-button :label="90">近90天</el-radio-button>
                        <el-radio-button :label="365">近1年</el-radio-button>
                    </el-radio-group>
                </div>
            </div>

            <!-- 详细数据表 -->
            <el-table :data="detailTable" border stripe size="small" style="width:100%;">
                <el-table-column prop="label" label="指标" min-width="180"></el-table-column>
                <el-table-column label="金额（元）" width="160" align="center">
                    <template slot-scope="scope">
                        <span :style="{color: scope.row.color || '#303133', fontWeight: scope.row.bold ? 'bold' : 'normal'}">
                            &yen;{{scope.row.value}}
                        </span>
                    </template>
                </el-table-column>
                <el-table-column label="说明" min-width="280" show-overflow-tooltip>
                    <template slot-scope="scope">
                        <span style="color:#909399;font-size:12px;">{{scope.row.desc}}</span>
                    </template>
                </el-table-column>
            </el-table>

            <!-- 利润趋势图 -->
            <div style="margin-top:20px;">
                <div style="font-size:15px;font-weight:bold;margin-bottom:10px;">利润趋势（{{days}}天）</div>
                <div id="profitTrendChart" style="height:380px;"></div>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            days: 7,
            stats: {
                orderCount: 0,
                totalSales: 0,
                totalCost: 0,
                totalShippingFee: 0,
                totalDiscount: 0,
                grossProfit: 0,
                netProfit: 0,
                profitMargin: 0
            },
            trend: [],
            _chart: null,
            _onResize: null
        };
    },
    computed: {
        detailTable() {
            return [
                { label: '订单数（已完成）', value: this.stats.orderCount || 0, desc: '统计已完成订单（状态=交易成功/已评价），不含已关闭', color: '#303133' },
                { label: '销售额', value: this.formatMoney(this.stats.totalSales), desc: '订单实付金额之和（优惠后，不含运费）', color: '#3498db', bold: true },
                { label: '商品成本', value: this.formatMoney(this.stats.totalCost), desc: '订单详情中成本价快照 × 数量之和', color: '#f39c12' },
                { label: '运费成本', value: this.formatMoney(this.stats.totalShippingFee), desc: '物流记录中运费之和（商家承担）', color: '#27ae60' },
                { label: '优惠折扣', value: this.formatMoney(this.stats.totalDiscount), desc: '订单优惠金额之和（满减/折扣券）', color: '#9b59b6' },
                { label: '毛利润', value: this.formatMoney(this.stats.grossProfit), desc: '销售额 − 商品成本', color: '#1abc9c', bold: true },
                { label: '净利润', value: this.formatMoney(this.stats.netProfit), desc: '销售额 − 商品成本 − 运费', color: '#e54346', bold: true },
                { label: '利润率', value: ((this.stats.profitMargin || 0)).toFixed(2) + '%', desc: '净利润 ÷ 销售额 × 100%', color: '#e54346', bold: true }
            ];
        }
    },
    mounted() {
        this._onResize = () => { if (this._chart) this._chart.resize(); };
        window.addEventListener('resize', this._onResize);
        this.loadStats();
    },
    beforeDestroy() {
        window.removeEventListener('resize', this._onResize);
        if (this._chart) {
            this._chart.dispose();
            this._chart = null;
        }
    },
    methods: {
        formatMoney(val) { return ZM.formatMoney(val); },
        loadStats() {
            // 利润概览
            ZM.http.get('/orders/merchant/profit-stats', { params: { days: this.days } }).then(res => {
                if (res) {
                    this.stats = { ...this.stats, ...res };
                }
            }).catch(() => {});
            // 利润趋势
            ZM.http.get('/orders/merchant/profit-trend', { params: { days: this.days } }).then(res => {
                this.trend = Array.isArray(res) ? res : [];
                this.$nextTick(() => this.renderTrendChart());
            }).catch(() => {
                this.trend = [];
                this.$nextTick(() => this.renderTrendChart());
            });
        },
        renderTrendChart() {
            const dom = document.getElementById('profitTrendChart');
            if (!dom) return;
            // 复用 echarts 实例，避免重复 init 警告与内存泄漏
            this._chart = echarts.getInstanceByDom(dom) || echarts.init(dom);
            const list = this.trend;
            // 空数据兜底：填充近 N 天 0 值，避免图表完全空白
            let dates = list.map(d => d.date || '');
            let salesData = list.map(d => d.sales ? d.sales / 100 : 0);
            let costData = list.map(d => d.cost ? d.cost / 100 : 0);
            let shipData = list.map(d => d.shippingFee ? d.shippingFee / 100 : 0);
            let profitData = list.map(d => d.netProfit ? d.netProfit / 100 : 0);
            if (list.length === 0) {
                const today = new Date();
                for (let i = this.days - 1; i >= 0; i--) {
                    const d = new Date(today);
                    d.setDate(d.getDate() - i);
                    const y = d.getFullYear();
                    const m = String(d.getMonth() + 1).padStart(2, '0');
                    const day = String(d.getDate()).padStart(2, '0');
                    dates.push(`${y}-${m}-${day}`);
                    salesData.push(0); costData.push(0); shipData.push(0); profitData.push(0);
                }
            }
            this._chart.setOption({
                tooltip: { trigger: 'axis' },
                legend: { data: ['销售额', '商品成本', '运费', '净利润'] },
                grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                xAxis: { type: 'category', data: dates, boundaryGap: false },
                yAxis: { type: 'value', name: '金额(元)' },
                series: [
                    {
                        name: '销售额', type: 'line', smooth: true, data: salesData,
                        itemStyle: { color: '#3498db' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(52,152,219,0.3)' },
                            { offset: 1, color: 'rgba(52,152,219,0.05)' }
                        ])}
                    },
                    {
                        name: '商品成本', type: 'line', smooth: true, data: costData,
                        itemStyle: { color: '#f39c12' }
                    },
                    {
                        name: '运费', type: 'line', smooth: true, data: shipData,
                        itemStyle: { color: '#27ae60' }
                    },
                    {
                        name: '净利润', type: 'line', smooth: true, data: profitData,
                        itemStyle: { color: '#e54346' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(229,67,70,0.3)' },
                            { offset: 1, color: 'rgba(229,67,70,0.05)' }
                        ])}
                    }
                ]
            });
        }
    }
});
