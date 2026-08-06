// AI 数据看板页面组件（阶段一：AI 模特图指标）
Vue.component('ai-stats-page', {
    template: `
    <div>
        <!-- 顶部概览卡片 -->
        <div class="stat-cards" style="margin-bottom:16px;">
            <div class="stat-card">
                <div class="stat-icon blue"><i class="el-icon-plus"></i></div>
                <div class="stat-info">
                    <div class="stat-label">今日新增任务</div>
                    <div class="stat-value">{{overview.taskToday}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon orange"><i class="el-icon-s-data"></i></div>
                <div class="stat-info">
                    <div class="stat-label">累计任务</div>
                    <div class="stat-value">{{overview.taskTotal}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green"><i class="el-icon-star-on"></i></div>
                <div class="stat-info">
                    <div class="stat-label">平均评分</div>
                    <div class="stat-value">{{overview.avgRating ? overview.avgRating.toFixed(2) : '0.00'}}</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon red"><i class="el-icon-upload"></i></div>
                <div class="stat-info">
                    <div class="stat-label">发布转化率</div>
                    <div class="stat-value" style="color:#e54346;">{{(overview.publishRate * 100).toFixed(1)}}%</div>
                </div>
            </div>
        </div>

        <!-- 趋势图 -->
        <div class="page-card">
            <div class="page-header">
                <h3>AI 模特图任务趋势</h3>
                <div style="display:flex;align-items:center;gap:8px;">
                    <el-radio-group v-model="days" size="small" @change="loadTrend">
                        <el-radio-button :label="7">近7天</el-radio-button>
                        <el-radio-button :label="30">近30天</el-radio-button>
                        <el-radio-button :label="90">近90天</el-radio-button>
                    </el-radio-group>
                </div>
            </div>
            <div id="aiTrendChart" style="height:380px;"></div>
        </div>

        <!-- 双列图表：任务状态分布 + 评分分布 -->
        <div style="display:flex;gap:16px;margin-top:16px;flex-wrap:wrap;">
            <div class="page-card" style="flex:1;min-width:380px;">
                <div class="page-header"><h3>任务状态分布</h3></div>
                <div id="aiStatusPie" style="height:340px;"></div>
            </div>
            <div class="page-card" style="flex:1;min-width:380px;">
                <div class="page-header"><h3>评分分布</h3></div>
                <div id="aiRatingBar" style="height:340px;"></div>
            </div>
        </div>

        <!-- 概览明细表 -->
        <div class="page-card" style="margin-top:16px;">
            <div class="page-header"><h3>指标明细</h3></div>
            <el-table :data="detailTable" border stripe size="small" style="width:100%;">
                <el-table-column prop="label" label="指标" min-width="180"></el-table-column>
                <el-table-column label="数值" width="160" align="center">
                    <template slot-scope="scope">
                        <span :style="{color: scope.row.color || '#303133', fontWeight: scope.row.bold ? 'bold' : 'normal'}">
                            {{scope.row.value}}
                        </span>
                    </template>
                </el-table-column>
                <el-table-column label="说明" min-width="280" show-overflow-tooltip>
                    <template slot-scope="scope">
                        <span style="color:#909399;font-size:12px;">{{scope.row.desc}}</span>
                    </template>
                </el-table-column>
            </el-table>
        </div>

        <!-- 底部说明 -->
        <div style="margin-top:16px;padding:12px 16px;background:#fff8e6;border:1px solid #ffd58a;border-radius:4px;color:#909399;font-size:13px;">
            <i class="el-icon-info" style="color:#e6a23c;margin-right:4px;"></i>
            本看板仅统计 AI 模特图指标，AI 随心搭指标将在阶段二上线。
        </div>
    </div>
    `,
    data() {
        return {
            days: 7,
            overview: {
                taskTotal: 0, taskToday: 0,
                successCount: 0, failedCount: 0, processingCount: 0, pendingCount: 0,
                successRate: 0, avgCostMs: 0,
                publishedCount: 0, publishRate: 0,
                avgRating: 0, ratingCount: 0,
                rejectCount: 0, rejectRate: 0,
                poolCount: 0
            },
            trend: [],
            ratingDist: [],
            _trendChart: null,
            _pieChart: null,
            _barChart: null,
            _onResize: null
        };
    },
    computed: {
        detailTable() {
            const o = this.overview;
            return [
                { label: '累计任务总数', value: o.taskTotal, desc: '商家全部 AI 模特图任务（task_type=MODEL）', color: '#303133', bold: true },
                { label: '今日新增任务', value: o.taskToday, desc: '今日 00:00 后创建的任务数', color: '#3498db' },
                { label: '成功任务数', value: o.successCount, desc: 'status=SUCCESS', color: '#27ae60' },
                { label: '失败任务数', value: o.failedCount, desc: 'status=FAILED / TIMEOUT', color: '#e54346' },
                { label: '处理中任务数', value: o.processingCount, desc: 'status=PROCESSING', color: '#f39c12' },
                { label: '待处理任务数', value: o.pendingCount, desc: 'status=PENDING', color: '#9b59b6' },
                { label: '成功率', value: (o.successRate * 100).toFixed(1) + '%', desc: '成功任务数 ÷ 累计任务总数', color: '#27ae60', bold: true },
                { label: '平均耗时', value: o.avgCostMs + ' ms', desc: '仅成功任务的平均耗时（cost_ms）', color: '#303133' },
                { label: '已发布到主图数', value: o.publishedCount, desc: 'published_item_id 非空的任务数', color: '#3498db' },
                { label: '发布转化率', value: (o.publishRate * 100).toFixed(1) + '%', desc: '已发布数 ÷ 成功任务数', color: '#e54346', bold: true },
                { label: '平均评分', value: o.avgRating ? o.avgRating.toFixed(2) : '0.00', desc: '商家五星评分均值（1-5）', color: '#f39c12' },
                { label: '评分数', value: o.ratingCount, desc: 'feedback_type=RATING 的反馈数', color: '#303133' },
                { label: '拒绝次数', value: o.rejectCount, desc: 'feedback_type=REJECT 的反馈数', color: '#e54346' },
                { label: '拒绝率', value: (o.rejectRate * 100).toFixed(1) + '%', desc: '拒绝次数 ÷ (评分数 + 拒绝次数)', color: '#e54346' },
                { label: '入池数', value: o.poolCount, desc: 'saved_to_pool=1 的反馈数（最终图入系统模特图池）', color: '#1abc9c' }
            ];
        }
    },
    mounted() {
        this._onResize = () => {
            if (this._trendChart) this._trendChart.resize();
            if (this._pieChart) this._pieChart.resize();
            if (this._barChart) this._barChart.resize();
        };
        window.addEventListener('resize', this._onResize);
        this.loadOverview();
        this.loadTrend();
    },
    beforeDestroy() {
        window.removeEventListener('resize', this._onResize);
        if (this._trendChart) { this._trendChart.dispose(); this._trendChart = null; }
        if (this._pieChart) { this._pieChart.dispose(); this._pieChart = null; }
        if (this._barChart) { this._barChart.dispose(); this._barChart = null; }
    },
    methods: {
        loadOverview() {
            ZM.http.get('/merchant/dashboard/ai-overview').then(res => {
                if (res) {
                    this.overview = { ...this.overview, ...res };
                }
                this.$nextTick(() => this.renderStatusPie());
            }).catch(() => {
                this.$nextTick(() => this.renderStatusPie());
            });
            // 评分分布
            ZM.http.get('/merchant/dashboard/ai-rating-dist').then(res => {
                this.ratingDist = Array.isArray(res) ? res : [];
                this.$nextTick(() => this.renderRatingBar());
            }).catch(() => {
                this.ratingDist = [];
                this.$nextTick(() => this.renderRatingBar());
            });
        },
        loadTrend() {
            ZM.http.get('/merchant/dashboard/ai-trend', { params: { days: this.days } }).then(res => {
                this.trend = Array.isArray(res) ? res : [];
                this.$nextTick(() => this.renderTrendChart());
            }).catch(() => {
                this.trend = [];
                this.$nextTick(() => this.renderTrendChart());
            });
        },
        renderTrendChart() {
            const dom = document.getElementById('aiTrendChart');
            if (!dom) return;
            this._trendChart = echarts.getInstanceByDom(dom) || echarts.init(dom);
            const list = this.trend;
            let dates = list.map(d => d.date || '');
            let totalData = list.map(d => d.total || 0);
            let successData = list.map(d => d.success || 0);
            let failedData = list.map(d => d.failed || 0);
            let costData = list.map(d => d.avgCostMs || 0);
            // 空数据兜底：填充近 N 天 0 值
            if (list.length === 0) {
                const today = new Date();
                for (let i = this.days - 1; i >= 0; i--) {
                    const d = new Date(today);
                    d.setDate(d.getDate() - i);
                    const y = d.getFullYear();
                    const m = String(d.getMonth() + 1).padStart(2, '0');
                    const day = String(d.getDate()).padStart(2, '0');
                    dates.push(y + '-' + m + '-' + day);
                    totalData.push(0); successData.push(0); failedData.push(0); costData.push(0);
                }
            }
            this._trendChart.setOption({
                tooltip: { trigger: 'axis' },
                legend: { data: ['任务总数', '成功数', '失败数', '平均耗时(ms)'] },
                grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                xAxis: { type: 'category', data: dates, boundaryGap: false },
                yAxis: [
                    { type: 'value', name: '任务数' },
                    { type: 'value', name: '耗时(ms)', position: 'right' }
                ],
                series: [
                    {
                        name: '任务总数', type: 'line', smooth: true, data: totalData,
                        itemStyle: { color: '#3498db' },
                        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(52,152,219,0.3)' },
                            { offset: 1, color: 'rgba(52,152,219,0.05)' }
                        ]) }
                    },
                    {
                        name: '成功数', type: 'line', smooth: true, data: successData,
                        itemStyle: { color: '#27ae60' }
                    },
                    {
                        name: '失败数', type: 'line', smooth: true, data: failedData,
                        itemStyle: { color: '#e54346' }
                    },
                    {
                        name: '平均耗时(ms)', type: 'line', smooth: true, data: costData,
                        yAxisIndex: 1,
                        itemStyle: { color: '#f39c12' }
                    }
                ]
            });
        },
        renderStatusPie() {
            const dom = document.getElementById('aiStatusPie');
            if (!dom) return;
            this._pieChart = echarts.getInstanceByDom(dom) || echarts.init(dom);
            const o = this.overview;
            const data = [
                { name: '成功', value: o.successCount, color: '#27ae60' },
                { name: '失败', value: o.failedCount, color: '#e54346' },
                { name: '处理中', value: o.processingCount, color: '#f39c12' },
                { name: '待处理', value: o.pendingCount, color: '#9b59b6' }
            ].filter(d => d.value > 0);
            // 全部为 0 时给一个占位，避免空白
            if (data.length === 0) {
                data.push({ name: '暂无数据', value: 1, color: '#cccccc' });
            }
            this._pieChart.setOption({
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: { bottom: 0, left: 'center' },
                series: [{
                    type: 'pie',
                    radius: ['40%', '65%'],
                    center: ['50%', '45%'],
                    avoidLabelOverlap: false,
                    label: { show: true, formatter: '{b}\\n{c}' },
                    data: data.map(d => ({ name: d.name, value: d.value, itemStyle: { color: d.color } }))
                }]
            });
        },
        renderRatingBar() {
            const dom = document.getElementById('aiRatingBar');
            if (!dom) return;
            this._barChart = echarts.getInstanceByDom(dom) || echarts.init(dom);
            const dist = this.ratingDist;
            const labels = dist.map(d => d.star + '星');
            const counts = dist.map(d => d.count || 0);
            const colors = ['#e54346', '#f39c12', '#f1c40f', '#27ae60', '#3498db'];
            this._barChart.setOption({
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                xAxis: { type: 'category', data: labels },
                yAxis: { type: 'value', name: '评分数' },
                series: [{
                    type: 'bar',
                    data: counts.map((v, i) => ({ value: v, itemStyle: { color: colors[i] || '#3498db' } })),
                    barWidth: '50%',
                    label: { show: true, position: 'top' }
                }]
            });
        }
    }
});
