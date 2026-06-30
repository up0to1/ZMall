// 修改密码页面组件
Vue.component('change-password-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header">
                <h3>修改密码</h3>
            </div>
            <div style="max-width:500px;">
                <el-form :model="form" :rules="formRules" ref="form" label-width="100px">
                    <el-form-item label="当前账号">
                        <el-input :value="user.username" disabled></el-input>
                    </el-form-item>
                    <el-form-item label="原密码" prop="oldPassword">
                        <el-input v-model="form.oldPassword" type="password" show-password placeholder="请输入原密码"></el-input>
                    </el-form-item>
                    <el-form-item label="新密码" prop="newPassword">
                        <el-input v-model="form.newPassword" type="password" show-password placeholder="请输入新密码（6-20位）"></el-input>
                    </el-form-item>
                    <el-form-item label="确认密码" prop="confirmPassword">
                        <el-input v-model="form.confirmPassword" type="password" show-password placeholder="请再次输入新密码"></el-input>
                    </el-form-item>
                    <el-form-item>
                        <el-button type="primary" @click="handleSubmit" :loading="loading">确认修改</el-button>
                        <el-button @click="resetForm">重置</el-button>
                    </el-form-item>
                </el-form>
            </div>
        </div>
    </div>
    `,
    data() {
        const validateConfirm = (rule, value, callback) => {
            if (value !== this.form.newPassword) {
                callback(new Error('两次输入的密码不一致'));
            } else {
                callback();
            }
        };
        return {
            loading: false,
            form: {
                oldPassword: '',
                newPassword: '',
                confirmPassword: ''
            },
            formRules: {
                oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
                newPassword: [
                    { required: true, message: '请输入新密码', trigger: 'blur' },
                    { min: 6, max: 20, message: '密码长度在6-20位之间', trigger: 'blur' }
                ],
                confirmPassword: [
                    { required: true, message: '请再次输入新密码', trigger: 'blur' },
                    { validator: validateConfirm, trigger: 'blur' }
                ]
            }
        };
    },
    computed: {
        user() {
            return ZM.getUser();
        }
    },
    methods: {
        handleSubmit() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                this.loading = true;
                ZM.http.put('/users/password', {
                    oldPassword: this.form.oldPassword,
                    newPassword: this.form.newPassword
                }).then(() => {
                    this.loading = false;
                    this.$confirm('密码修改成功，需要重新登录', '提示', {
                        confirmButtonText: '去登录',
                        showCancelButton: false,
                        type: 'success'
                    }).then(() => {
                        ZM.logout();
                    });
                }).catch(err => {
                    this.loading = false;
                    const msg = err.response?.data?.msg || err.response?.data?.message || '修改失败，请检查原密码是否正确';
                    this.$message.error(msg);
                });
            });
        },
        resetForm() {
            this.form = { oldPassword: '', newPassword: '', confirmPassword: '' };
            this.$refs.form.resetFields();
        }
    }
});
