// 评价管理页面组件
Vue.component('comment-list-page', {
    template: `
    <div>
        <!-- 评价统计 -->
        <div style="display:flex;gap:15px;margin-bottom:20px;">
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e54346;">{{stats.totalComments || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">评价总数</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#e6a23c;">{{stats.todayNew || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">今日新增</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#409eff;">{{stats.avgRating || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">平均评分</div>
            </div>
            <div class="page-card" style="flex:1;text-align:center;padding:15px;">
                <div style="font-size:28px;font-weight:bold;color:#f56c6c;">{{stats.pendingReply || 0}}</div>
                <div style="font-size:13px;color:#909399;margin-top:5px;">待回复</div>
            </div>
        </div>

        <!-- 评价列表 -->
        <div class="page-card">
            <div class="page-header">
                <h3>评价列表</h3>
            </div>
            <div class="search-bar" style="margin-bottom:15px;">
                <el-input v-model="searchContent" placeholder="搜索评价内容" size="small" style="width:220px;" clearable prefix-icon="el-icon-search"></el-input>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <el-table :data="pagedData" v-loading="loading" size="small" style="width:100%;">
                <el-table-column prop="id" label="ID" width="80"></el-table-column>
                <el-table-column prop="itemName" label="商品" min-width="160" show-overflow-tooltip></el-table-column>
                <el-table-column prop="userId" label="用户ID" width="80"></el-table-column>
                <el-table-column prop="content" label="评价内容" min-width="200" show-overflow-tooltip></el-table-column>
                <el-table-column prop="rating" label="评分" width="140">
                    <template slot-scope="scope">
                        <el-rate :value="scope.row.rating" disabled show-score text-color="#ff9900" score-template="{value}"></el-rate>
                    </template>
                </el-table-column>
                <el-table-column label="评价图片" width="120" align="center">
                    <template slot-scope="scope">
                        <template v-if="parseImages(scope.row.images).length">
                            <el-image v-for="(img,i) in parseImages(scope.row.images).slice(0,3)" :key="i" :src="getImageUrl(img)" style="width:30px;height:30px;margin-right:2px;" fit="cover" :preview-src-list="parseImages(scope.row.images).map(getImageUrl)"></el-image>
                        </template>
                        <span v-else style="color:#909399;">无</span>
                    </template>
                </el-table-column>
                <el-table-column prop="reply" label="商家回复" min-width="160" show-overflow-tooltip>
                    <template slot-scope="scope">
                        <span v-if="scope.row.reply" style="color:#67c23a;">{{scope.row.reply}}</span>
                        <span v-else style="color:#f56c6c;">未回复</span>
                    </template>
                </el-table-column>
                <el-table-column prop="createTime" label="评价时间" width="160">
                    <template slot-scope="scope">{{formatDate(scope.row.createTime)}}</template>
                </el-table-column>
                <el-table-column label="操作" width="120" fixed="right">
                    <template slot-scope="scope">
                        <el-button type="text" size="small" @click="openReply(scope.row)">回复</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div style="margin-top:15px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>

        <!-- 回复对话框 -->
        <el-dialog title="回复评价" :visible.sync="replyVisible" width="500px">
            <div v-if="replyItem" style="margin-bottom:15px;padding:12px;background:#f5f7fa;border-radius:6px;">
                <p style="margin:0 0 8px;"><strong>评价内容：</strong>{{replyItem.content}}</p>
                <p style="margin:0;"><strong>评分：</strong>
                    <el-rate :value="replyItem.rating" disabled></el-rate>
                </p>
                <p v-if="replyItem.reply" style="margin:8px 0 0;color:#67c23a;"><strong>当前回复：</strong>{{replyItem.reply}}</p>
            </div>
            <el-input v-model="replyContent" type="textarea" :rows="3" placeholder="请输入回复内容" maxlength="200" show-word-limit></el-input>
            <span slot="footer">
                <el-button @click="replyVisible=false">取消</el-button>
                <el-button type="primary" @click="doReply" :loading="replyLoading">确认回复</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            stats: {},
            commentList: [],
            loading: false,
            total: 0,
            currentPage: 1,
            pageSize: 10,
            searchContent: '',
            replyVisible: false,
            replyItem: null,
            replyContent: '',
            replyLoading: false
        };
    },
    computed: {
        filteredData() {
            let list = this.commentList;
            if (this.searchContent) {
                const key = this.searchContent.toLowerCase();
                list = list.filter(item => (item.content || '').toLowerCase().includes(key));
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
        this.loadComments();
    },
    methods: {
        formatDate(val) { return ZM.formatDate(val); },
        parseImages(images) {
            if (!images) return [];
            try {
                var arr = JSON.parse(images);
                return Array.isArray(arr) ? arr : [];
            } catch (e) {
                return images.split(',').filter(function(s) { return s.trim(); });
            }
        },
        getImageUrl(path) {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            return path;
        },
        loadStats() {
            ZM.http.get('/comments/admin/stats').then(res => {
                this.stats = res || {};
            }).catch(() => {});
        },
        loadComments() {
            this.loading = true;
            ZM.http.get('/comments/admin/page', { params: { page: 1, size: 99999 } }).then(res => {
                this.commentList = res.list || [];
                this.total = res.total || 0;
                this.loading = false;
            }).catch(() => { this.loading = false; });
        },
        resetSearch() {
            this.searchContent = '';
            this.currentPage = 1;
        },
        openReply(item) {
            this.replyItem = item;
            this.replyContent = '';
            this.replyVisible = true;
        },
        doReply() {
            if (!this.replyContent.trim()) {
                this.$message.warning('请输入回复内容');
                return;
            }
            this.replyLoading = true;
            ZM.http.put('/comments/admin/' + this.replyItem.id + '/reply', { reply: this.replyContent }).then(() => {
                this.replyLoading = false;
                this.$message.success('回复成功');
                this.replyVisible = false;
                this.loadComments();
                this.loadStats();
            }).catch(() => {
                this.replyLoading = false;
                this.$message.error('回复失败');
            });
        }
    }
});
