// 商家信息管理页面组件
Vue.component('shop-profile-page', {
    template: `
    <div>
        <div class="page-card">
            <div class="page-header">
                <h3>商家信息</h3>
            </div>
            <div v-loading="loading" style="max-width:600px;">
                <el-form :model="form" :rules="formRules" ref="form" label-width="100px">
                    <el-form-item label="商家ID">
                        <el-input :value="form.id || user.userId" disabled></el-input>
                    </el-form-item>
                    <el-form-item label="账号">
                        <el-input :value="user.username" disabled></el-input>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">账号不可修改</div>
                    </el-form-item>
                    <el-form-item label="店铺名称" prop="shopName">
                        <el-input v-model="form.shopName" placeholder="请输入店铺名称"></el-input>
                    </el-form-item>
                    <el-form-item label="店铺Logo" prop="logo">
                        <div>
                            <el-upload
                                class="logo-uploader"
                                action="/api/merchant/profile/upload"
                                name="file"
                                :headers="uploadHeaders"
                                :show-file-list="false"
                                :on-success="handleLogoUploadSuccess"
                                :on-error="handleLogoUploadError"
                                :before-upload="beforeLogoUpload"
                                accept="image/*">
                                <img v-if="form.logo" :src="getImageUrl(form.logo)" style="max-width:200px;max-height:150px;display:block;border-radius:8px;">
                                <el-button v-else size="small" type="primary" icon="el-icon-upload2">上传图片</el-button>
                            </el-upload>
                            <div v-if="form.logo" style="margin-top:8px;">
                                <el-button size="mini" type="danger" @click="form.logo=''">删除图片</el-button>
                                <span style="font-size:12px;color:#909399;margin-left:8px;">{{form.logo}}</span>
                            </div>
                        </div>
                    </el-form-item>
                    <el-form-item label="店铺简介" prop="description">
                        <el-input v-model="form.description" type="textarea" :rows="4" placeholder="请输入店铺简介"></el-input>
                    </el-form-item>
                    <el-form-item label="联系电话" prop="contactPhone">
                        <el-input v-model="form.contactPhone" placeholder="请输入联系电话"></el-input>
                    </el-form-item>
                    <el-form-item label="店铺地址" prop="address">
                        <el-input v-model="form.address" placeholder="请输入店铺地址"></el-input>
                    </el-form-item>
                    <el-form-item>
                        <el-button type="primary" @click="handleSave" :loading="saving">保存信息</el-button>
                        <el-button v-if="!hasProfile" type="danger" @click="handleCreate" :loading="saving">创建商家信息</el-button>
                    </el-form-item>
                </el-form>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            loading: false,
            saving: false,
            hasProfile: false,
            form: {
                id: null,
                shopName: '',
                logo: '',
                description: '',
                contactPhone: '',
                address: ''
            },
            formRules: {
                shopName: [{ required: true, message: '请输入店铺名称', trigger: 'blur' }]
            },
            uploadHeaders: { 'authorization': 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') }
        };
    },
    computed: {
        user() {
            return ZM.getUser();
        }
    },
    mounted() {
        this.loadProfile();
    },
    methods: {
        getImageUrl(path) {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            return path;
        },
        beforeLogoUpload(file) {
            const isImage = file.type.startsWith('image/');
            const isLt5M = file.size / 1024 / 1024 < 5;
            if (!isImage) {
                this.$message.error('只能上传图片文件!');
                return false;
            }
            if (!isLt5M) {
                this.$message.error('图片大小不能超过5MB!');
                return false;
            }
            return true;
        },
        handleLogoUploadSuccess(res) {
            if (typeof res === 'string' && res) {
                this.form.logo = res;
                this.$message.success('Logo上传成功');
            } else if (res && res.data) {
                this.form.logo = res.data;
                this.$message.success('Logo上传成功');
            } else {
                this.$message.error('Logo上传失败');
            }
        },
        handleLogoUploadError() {
            this.$message.error('Logo上传失败');
        },
        loadProfile() {
            this.loading = true;
            ZM.http.get('/merchant/profile').then(res => {
                this.loading = false;
                if (res && res.shopName) {
                    this.hasProfile = true;
                    this.form = {
                        id: res.id,
                        shopName: res.shopName || '',
                        logo: res.logo || '',
                        description: res.description || '',
                        contactPhone: res.contactPhone || '',
                        address: res.address || ''
                    };
                } else {
                    this.hasProfile = false;
                }
            }).catch(() => {
                this.loading = false;
                this.hasProfile = false;
            });
        },
        handleSave() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                this.saving = true;
                ZM.http.put('/merchant/profile', this.form).then(() => {
                    this.saving = false;
                    this.$message.success('保存成功');
                    this.loadProfile();
                }).catch(() => {
                    this.saving = false;
                    this.$message.error('保存失败');
                });
            });
        },
        handleCreate() {
            this.$refs.form.validate(valid => {
                if (!valid) return;
                this.saving = true;
                ZM.http.put('/merchant/profile', this.form).then(() => {
                    this.saving = false;
                    this.$message.success('创建成功');
                    this.loadProfile();
                }).catch(() => {
                    this.saving = false;
                    this.$message.error('创建失败');
                });
            });
        }
    }
});
