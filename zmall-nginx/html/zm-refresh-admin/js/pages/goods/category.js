// 商品分类页面组件
Vue.component('goods-category-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header">
                <h3>商品分类</h3>
                <el-button type="primary" size="small" icon="el-icon-plus" @click="handleAdd">添加分类</el-button>
            </div>
            <el-table :data="tableData" border stripe v-loading="loading" row-key="id" default-expand-all :tree-props="{children:'children',hasChildren:'hasChildren'}">
                <el-table-column prop="id" label="ID" width="80" align="center"></el-table-column>
                <el-table-column prop="name" label="分类名称" min-width="200"></el-table-column>
                <el-table-column prop="sort" label="排序" width="80" align="center"></el-table-column>
                <el-table-column label="操作" width="200" align="center">
                    <template slot-scope="scope">
                        <el-button size="mini" @click="handleEdit(scope.row)">编辑</el-button>
                        <el-button size="mini" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
        </div>

        <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="500px" :close-on-click-modal="false">
            <el-form :model="form" :rules="formRules" ref="form" label-width="100px">
                <el-form-item label="分类名称" prop="name">
                    <el-input v-model="form.name" placeholder="请输入分类名称"></el-input>
                </el-form-item>
                <el-form-item label="父级分类">
                    <el-select v-model="form.parentId" placeholder="无（顶级分类）" clearable style="width:100%">
                        <el-option v-for="c in topCategories" :key="c.id" :label="c.name" :value="c.id"></el-option>
                    </el-select>
                </el-form-item>
                <el-form-item label="排序" prop="sort">
                    <el-input-number v-model="form.sort" :min="0" style="width:100%"></el-input-number>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="dialogVisible=false">取 消</el-button>
                <el-button type="primary" @click="submitForm" :loading="submitLoading">确 定</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    data() {
        return {
            loading: false,
            tableData: [],
            flatList: [],
            dialogVisible: false,
            dialogTitle: '添加分类',
            submitLoading: false,
            form: { id: null, name: '', parentId: null, sort: 0 },
            formRules: {
                name: [{ required: true, message: '请输入分类名称', trigger: 'blur' }]
            }
        };
    },
    computed: {
        topCategories() {
            return this.flatList.filter(c => !c.parentId || c.parentId === 0);
        }
    },
    mounted() {
        this.loadList();
    },
    methods: {
        loadList() {
            this.loading = true;
            ZM.http.get('/categories').then(res => {
                this.loading = false;
                let list = Array.isArray(res) ? res : (res.records || res.list || []);
                // 保存扁平列表用于父级分类选择
                this.flatList = list;
                // 构建树形结构
                const map = {};
                const tree = [];
                list.forEach(item => { map[item.id] = { ...item, children: [] }; });
                list.forEach(item => {
                    if (item.parentId && map[item.parentId]) {
                        map[item.parentId].children.push(map[item.id]);
                    } else {
                        tree.push(map[item.id]);
                    }
                });
                // 清理空children
                const clean = nodes => nodes.forEach(n => { if (n.children.length === 0) delete n.children; else clean(n.children); });
                clean(tree);
                this.tableData = tree;
            }).catch(() => { this.loading = false; });
        },
        handleAdd() {
            this.dialogTitle = '添加分类';
            this.form = { id: null, name: '', parentId: null, sort: 0 };
            this.dialogVisible = true;
        },
        handleEdit(row) {
            this.dialogTitle = '编辑分类';
            this.form = { ...row };
            this.dialogVisible = true;
        },
        submitForm() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                this.submitLoading = true;
                const req = this.form.id
                    ? ZM.http.put('/categories/' + this.form.id, this.form)
                    : ZM.http.post('/categories', this.form);
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
        handleDelete(row) {
            this.$confirm('确定要删除该分类吗？', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/categories/' + row.id).then(() => {
                    this.$message.success('删除成功');
                    this.loadList();
                }).catch(() => { this.$message.error('删除失败'); });
            }).catch(() => {});
        }
    }
});
