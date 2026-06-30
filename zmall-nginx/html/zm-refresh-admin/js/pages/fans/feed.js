// Feed推送管理页面组件
Vue.component('feed-manage-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;">
                <h3>推送管理</h3>
                <el-button type="primary" size="small" icon="el-icon-plus" @click="openCreate">发布推送</el-button>
            </div>
            <div class="search-bar" style="margin-bottom:15px;">
                <el-input v-model="searchKeyword" placeholder="搜索推送内容" size="small" style="width:220px;" clearable prefix-icon="el-icon-search"></el-input>
                <el-button type="primary" size="small" icon="el-icon-search" @click="currentPage=1">搜索</el-button>
                <el-button size="small" @click="resetSearch">重置</el-button>
            </div>
            <el-table :data="pagedData" v-loading="loading" size="small" style="width:100%;">
                <el-table-column prop="id" label="ID" width="80"></el-table-column>
                <el-table-column prop="content" label="推送内容" min-width="200" show-overflow-tooltip></el-table-column>
                <el-table-column label="关联商品" min-width="160">
                    <template slot-scope="scope">
                        <span v-if="scope.row.itemName">{{scope.row.itemName}}</span>
                        <span v-else-if="scope.row.itemId">ID:{{scope.row.itemId}}</span>
                        <span v-else style="color:#909399;">无</span>
                    </template>
                </el-table-column>
                <el-table-column prop="images" label="图片" width="100">
                    <template slot-scope="scope">
                        <el-image v-if="parseImages(scope.row.images).length" :src="getImageUrl(parseImages(scope.row.images)[0])" style="width:50px;height:50px;border-radius:4px;" fit="cover" :preview-src-list="parseImages(scope.row.images).map(getImageUrl)"></el-image>
                        <span v-else style="color:#909399;">无</span>
                    </template>
                </el-table-column>
                <el-table-column prop="liked" label="点赞数" width="80"></el-table-column>
                <el-table-column prop="createTime" label="发布时间" width="160">
                    <template slot-scope="scope">{{formatDate(scope.row.createTime)}}</template>
                </el-table-column>
                <el-table-column label="操作" width="120" fixed="right">
                    <template slot-scope="scope">
                        <el-button type="text" size="small" style="color:#f56c6c;" @click="deleteFeed(scope.row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div style="margin-top:15px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:8px;">
                <span style="font-size:13px;color:#606266;">共 {{filteredTotal}} 条 / 共 {{Math.ceil(filteredTotal/pageSize)||1}} 页</span>
                <el-pagination background layout="prev, pager, next, jumper" :total="filteredTotal" :page-size="pageSize" :current-page.sync="currentPage"></el-pagination>
            </div>
        </div>

        <!-- 发布推送对话框 -->
        <el-dialog title="发布推送" :visible.sync="createVisible" width="650px" :close-on-click-modal="false">
            <el-form :model="createForm" label-width="100px">
                <el-form-item label="推送内容" required>
                    <el-input v-model="createForm.content" type="textarea" :rows="4" placeholder="请输入推送内容，如新品上架、促销活动等" maxlength="500" show-word-limit></el-input>
                </el-form-item>
                <el-form-item label="关联商品">
                    <el-radio-group v-model="itemSelectType" @change="handleItemSelectTypeChange">
                        <el-radio label="none">不关联商品</el-radio>
                        <el-radio label="all">全部商品</el-radio>
                        <el-radio label="custom">指定商品</el-radio>
                    </el-radio-group>
                    <div v-if="itemSelectType==='custom'" style="margin-top:10px;">
                        <div style="display:flex;gap:8px;margin-bottom:8px;">
                            <el-input v-model="itemSearchKey" placeholder="搜索商品名称" size="small" style="width:200px;" @input="filterItems"></el-input>
                            <el-checkbox v-model="itemSelectAll" @change="toggleSelectAllItems">全选</el-checkbox>
                        </div>
                        <el-checkbox-group v-model="selectedItemIds" @change="handleSelectedItemChange">
                            <div style="max-height:200px;overflow-y:auto;border:1px solid #eee;border-radius:4px;padding:8px;">
                                <div v-for="item in filteredItemList" :key="item.id" style="display:flex;align-items:center;padding:4px 0;border-bottom:1px solid #f5f5f5;">
                                    <el-checkbox :label="item.id" style="margin-right:8px;">&nbsp;</el-checkbox>
                                    <el-image v-if="item.image" :src="getImageUrl(item.image)" style="width:30px;height:30px;margin-right:8px;flex-shrink:0;" fit="cover"></el-image>
                                    <span style="font-size:13px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{item.name}}</span>
                                    <span style="font-size:12px;color:#e54346;margin-left:8px;flex-shrink:0;">&yen;{{formatMoney(item.price)}}</span>
                                </div>
                                <div v-if="!filteredItemList.length" style="text-align:center;color:#999;padding:20px;">暂无商品</div>
                            </div>
                        </el-checkbox-group>
                        <div v-if="selectedItemIds.length" style="margin-top:8px;font-size:12px;color:#409eff;">已选择 {{selectedItemIds.length}} 个商品</div>
                    </div>
                </el-form-item>
                <el-form-item label="上传图片（最多5张）">
                    <div style="display:flex;flex-wrap:wrap;gap:8px;">
                        <div v-for="(img,i) in feedImageList" :key="i" style="width:80px;height:80px;position:relative;">
                            <el-image :src="getImageUrl(img)" style="width:100%;height:100%;" fit="cover"></el-image>
                            <el-button size="mini" type="danger" circle icon="el-icon-delete" style="position:absolute;top:-8px;right:-8px;min-width:20px;width:20px;height:20px;padding:0;" @click="feedImageList.splice(i,1)"></el-button>
                        </div>
                        <el-upload v-if="feedImageList.length < 5" action="/api/shop/feed/upload" name="file" :headers="uploadHeaders" :show-file-list="false" :on-success="handleFeedUploadSuccess" :before-upload="beforeFeedUpload" accept="image/*">
                            <el-button size="small" icon="el-icon-plus">上传图片</el-button>
                        </el-upload>
                    </div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="createVisible=false">取消</el-button>
                <el-button type="primary" @click="doCreate" :loading="createLoading">发布</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            feedList: [],
            loading: false,
            total: 0,
            currentPage: 1,
            pageSize: 10,
            searchKeyword: '',
            createVisible: false,
            createLoading: false,
            createForm: { content: '' },
            feedImageList: [],
            uploadHeaders: { 'authorization': 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') },
            // 商品选择
            itemSelectType: 'none',
            allItemList: [],
            filteredItemList: [],
            itemSearchKey: '',
            itemSelectAll: false,
            selectedItemIds: []
        };
    },
    computed: {
        filteredData() {
            let list = this.feedList;
            if (this.searchKeyword) {
                const key = this.searchKeyword.toLowerCase();
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
        this.loadFeeds();
    },
    methods: {
        formatDate(val) { return ZM.formatDate(val); },
        formatMoney(val) { return ZM.formatMoney(val); },
        getImageUrl(path) {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            return path;
        },
        beforeFeedUpload(file) {
            const isImage = file.type.startsWith('image/');
            const isLt5M = file.size / 1024 / 1024 < 5;
            if (!isImage) { this.$message.error('只能上传图片文件!'); return false; }
            if (!isLt5M) { this.$message.error('图片大小不能超过5MB!'); return false; }
            return true;
        },
        handleFeedUploadSuccess(res) {
            const path = typeof res === 'string' && res ? res : (res && res.data ? res.data : '');
            if (path) {
                this.feedImageList.push(path);
            } else {
                this.$message.error('图片上传失败');
            }
        },
        loadFeeds() {
            this.loading = true;
            ZM.http.get('/shop/feed/page', { params: { page: 1, size: 99999 } }).then(res => {
                this.feedList = res.list || [];
                this.total = res.total || 0;
                this.loading = false;
            }).catch(() => { this.loading = false; });
        },
        resetSearch() {
            this.searchKeyword = '';
            this.currentPage = 1;
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
        handleItemSelectTypeChange(val) {
            this.selectedItemIds = [];
            this.itemSelectAll = false;
            if (val === 'custom' && this.allItemList.length === 0) {
                this.loadAllItems();
            }
        },
        toggleSelectAllItems(val) {
            if (val) {
                this.selectedItemIds = this.filteredItemList.map(i => i.id);
            } else {
                this.selectedItemIds = [];
            }
        },
        handleSelectedItemChange(val) {
            this.itemSelectAll = val.length === this.filteredItemList.length && this.filteredItemList.length > 0;
        },
        parseImages(images) {
            if (!images) return [];
            try {
                var arr = JSON.parse(images);
                return Array.isArray(arr) ? arr : [];
            } catch (e) {
                return images.split(',').filter(function(s) { return s.trim(); });
            }
        },
        openCreate() {
            this.createForm = { content: '' };
            this.feedImageList = [];
            this.itemSelectType = 'none';
            this.selectedItemIds = [];
            this.itemSelectAll = false;
            this.itemSearchKey = '';
            this.createVisible = true;
        },
        doCreate() {
            if (!this.createForm.content.trim()) {
                this.$message.warning('请输入推送内容');
                return;
            }
            this.createLoading = true;
            // 根据商品选择方式构建推送
            const feeds = [];
            if (this.itemSelectType === 'none') {
                // 不关联商品，发一条推送
                feeds.push({
                    content: this.createForm.content,
                    itemId: null,
                    images: this.feedImageList.length > 0 ? JSON.stringify(this.feedImageList) : null
                });
            } else if (this.itemSelectType === 'all') {
                // 全部商品，每个商品发一条推送
                if (this.allItemList.length === 0) {
                    this.createLoading = false;
                    this.$message.warning('暂无商品数据，请稍后重试');
                    return;
                }
                this.allItemList.forEach(item => {
                    feeds.push({
                        content: this.createForm.content,
                        itemId: item.id,
                        images: this.feedImageList.length > 0 ? JSON.stringify(this.feedImageList) : null
                    });
                });
            } else if (this.itemSelectType === 'custom') {
                // 指定商品
                if (this.selectedItemIds.length === 0) {
                    this.createLoading = false;
                    this.$message.warning('请选择至少一个商品');
                    return;
                }
                this.selectedItemIds.forEach(id => {
                    feeds.push({
                        content: this.createForm.content,
                        itemId: id,
                        images: this.feedImageList.length > 0 ? JSON.stringify(this.feedImageList) : null
                    });
                });
            }
            // 逐条发布
            let promise = Promise.resolve();
            feeds.forEach(feed => {
                promise = promise.then(() => ZM.http.post('/shop/feed', feed));
            });
            promise.then(() => {
                this.createLoading = false;
                this.$message.success('推送发布成功（共' + feeds.length + '条）');
                this.createVisible = false;
                this.loadFeeds();
            }).catch(err => {
                this.createLoading = false;
                const msg = (err.response && err.response.data && err.response.data.msg) || '发布失败';
                this.$message.error(msg);
            });
        },
        deleteFeed(item) {
            this.$confirm('确定删除该推送吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/shop/feed/' + item.id).then(() => {
                    this.$message.success('删除成功');
                    this.loadFeeds();
                }).catch(() => { this.$message.error('删除失败'); });
            }).catch(() => {});
        }
    }
});
