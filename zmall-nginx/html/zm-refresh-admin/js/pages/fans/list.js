// 粉丝管理页面组件
Vue.component('fans-list-page', {
    template: `
    <div>
        <!-- 粉丝统计 -->
        <div style="display:flex;gap:15px;margin-bottom:20px;">
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e54346;">{{stats.totalFans || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">粉丝总数</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#67c23a;">{{stats.todayNew || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">今日新增</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#409eff;">{{stats.weekNew || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">本周新增</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e6a23c;">{{stats.activeFans || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">活跃粉丝</div>
            </div>
        </div>

        <!-- 粉丝列表 -->
        <div class="page-card">
            <div class="page-header">
                <h3>粉丝列表</h3>
            </div>
            <div class="search-bar" style="margin-bottom:15px;">
                <el-input v-model="searchKeyword" placeholder="搜索粉丝用户ID" size="small" style="width:220px;" clearable prefix-icon="el-icon-search"></el-input>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <el-table :data="pagedData" v-loading="loading" size="small" style="width:100%;">
                <el-table-column prop="userId" label="用户ID" width="150"></el-table-column>
                <el-table-column prop="createTime" label="关注时间" width="200">
                    <template slot-scope="scope">{{formatDate(scope.row.createTime)}}</template>
                </el-table-column>
                <el-table-column label="关注时长">
                    <template slot-scope="scope">
                        <span>{{calcDuration(scope.row.createTime)}}</span>
                    </template>
                </el-table-column>
            </el-table>
            <div style="margin-top:15px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            stats: {},
            fansList: [],
            loading: false,
            total: 0,
            currentPage: 1,
            pageSize: 10,
            searchKeyword: ''
        };
    },
    computed: {
        filteredData() {
            let list = this.fansList;
            if (this.searchKeyword) {
                const key = String(this.searchKeyword);
                list = list.filter(item => String(item.userId).includes(key));
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
        this.loadStats();
        this.loadFans();
    },
    methods: {
        formatDate(val) { return ZM.formatDate(val); },
        loadStats() {
            ZM.http.get('/shop/fans/stats').then(res => {
                this.stats = res || {};
            }).catch(() => {});
        },
        loadFans() {
            this.loading = true;
            ZM.http.get('/shop/fans/page', { params: { page: 1, size: 99999 } }).then(res => {
                this.fansList = res.list || [];
                this.total = res.total || 0;
                this.loading = false;
            }).catch(() => { this.loading = false; });
        },
        resetSearch() {
            this.searchKeyword = '';
            this.currentPage = 1;
        },
        calcDuration(createTime) {
            if (!createTime) return '-';
            var d = new Date(createTime);
            var now = new Date();
            var diff = now - d;
            var days = Math.floor(diff / 86400000);
            if (days < 1) return '今天';
            if (days < 30) return days + '天';
            if (days < 365) return Math.floor(days / 30) + '个月';
            return Math.floor(days / 365) + '年' + (Math.floor((days % 365) / 30) ? Math.floor((days % 365) / 30) + '个月' : '');
        }
    }
});
