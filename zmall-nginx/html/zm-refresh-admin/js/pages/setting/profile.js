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

                    <!-- v3.2：钱包 + Credits 余额展示（充值 credits 扣减钱包） -->
                    <el-form-item label="钱包余额">
                        <span style="font-size:18px;font-weight:bold;color:#e6a23c;">￥{{ walletYuan }}</span>
                        <span style="font-size:12px;color:#909399;margin-left:8px;">{{ walletBalance }} 分</span>
                        <el-button type="text" style="margin-left:12px;" @click="showWalletRechargeDialog = true">💰 钱包充值</el-button>
                    </el-form-item>
                    <el-form-item label="Credits">
                        <span style="font-size:18px;font-weight:bold;color:#409eff;">{{ creditsBalance }} credits</span>
                        <el-button type="text" style="margin-left:12px;" @click="showRechargeDialog = true">💎 充值</el-button>
                        <div style="font-size:12px;color:#909399;margin-top:4px;">充值 credits 时从钱包余额扣减（1 元 = 5 credits）</div>
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

        <!-- 发货地址管理 -->
        <div class="page-card" style="margin-top:20px;">
            <div class="page-header">
                <h3>发货地址管理</h3>
                <el-button type="primary" size="small" icon="el-icon-plus" @click="handleAddShipAddr">新增发货地址</el-button>
            </div>
            <div v-loading="shipAddrLoading">
                <el-table :data="shipAddresses" border stripe style="width:100%" empty-text="暂无发货地址，请新增">
                    <el-table-column label="联系人" prop="contact" width="100"></el-table-column>
                    <el-table-column label="联系电话" prop="mobile" width="130"></el-table-column>
                    <el-table-column label="发货地址" min-width="250">
                        <template slot-scope="scope">
                            {{scope.row.province}}{{scope.row.city}}{{scope.row.town}}{{scope.row.street}}
                        </template>
                    </el-table-column>
                    <el-table-column label="备注" prop="notes" width="150" show-overflow-tooltip></el-table-column>
                    <el-table-column label="当前" width="80" align="center">
                        <template slot-scope="scope">
                            <el-tag v-if="scope.row.isDefault===1" type="success" size="small">当前</el-tag>
                            <span v-else style="color:#ccc;">-</span>
                        </template>
                    </el-table-column>
                    <el-table-column label="操作" width="220" align="center">
                        <template slot-scope="scope">
                            <el-button size="mini" @click="handleEditShipAddr(scope.row)">编辑</el-button>
                            <el-button v-if="scope.row.isDefault!==1" size="mini" type="success" @click="handleSetDefaultShipAddr(scope.row)">设为当前</el-button>
                            <el-button size="mini" type="danger" @click="handleDeleteShipAddr(scope.row)">删除</el-button>
                        </template>
                    </el-table-column>
                </el-table>
                <div style="margin-top:8px;font-size:12px;color:#909399;">
                    可维护多个发货地址，仅一个为当前发货地址（前台商品详情页展示发货地）。新增/设置时自动取消其他默认。
                </div>
            </div>
        </div>

        <!-- 发货地址编辑弹窗 -->
        <el-dialog :title="shipAddrForm.id ? '编辑发货地址' : '新增发货地址'"
                   :visible.sync="shipAddrDialogVisible" width="500px" :close-on-click-modal="false">
            <el-form :model="shipAddrForm" :rules="shipAddrRules" ref="shipAddrForm" label-width="90px">
                <el-form-item label="联系人" prop="contact">
                    <el-input v-model="shipAddrForm.contact" placeholder="请输入联系人"></el-input>
                </el-form-item>
                <el-form-item label="联系电话" prop="mobile">
                    <el-input v-model="shipAddrForm.mobile" placeholder="请输入联系电话"></el-input>
                </el-form-item>
                <el-form-item label="省" prop="province">
                    <el-input v-model="shipAddrForm.province" placeholder="如 广东省"></el-input>
                </el-form-item>
                <el-form-item label="市" prop="city">
                    <el-input v-model="shipAddrForm.city" placeholder="如 深圳市"></el-input>
                </el-form-item>
                <el-form-item label="区/县" prop="town">
                    <el-input v-model="shipAddrForm.town" placeholder="如 南山区"></el-input>
                </el-form-item>
                <el-form-item label="详细地址" prop="street">
                    <el-input v-model="shipAddrForm.street" type="textarea" :rows="2" placeholder="街道门牌号"></el-input>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="shipAddrForm.notes" placeholder="如 仓库A、总仓（选填）"></el-input>
                </el-form-item>
                <el-form-item label="设为当前">
                    <el-switch v-model="shipAddrForm.isDefault" :active-value="1" :inactive-value="0"></el-switch>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="shipAddrDialogVisible = false">取 消</el-button>
                <el-button type="primary" :loading="shipAddrSaving" @click="handleSaveShipAddr">确 定</el-button>
            </span>
        </el-dialog>

        <!-- v3.2：Credits 充值对话框（充值 credits 扣减钱包余额） -->
        <recharge-dialog :show="showRechargeDialog"
                         :current-balance="creditsBalance"
                         :wallet-balance="walletBalance"
                         :first-gift-received="firstGiftReceived"
                         @close="showRechargeDialog = false"
                         @recharged="onRecharged">
        </recharge-dialog>

        <!-- v3.2：钱包充值对话框（与前台用户充值逻辑一致，调用 /users/recharge） -->
        <el-dialog title="💰 钱包充值" :visible.sync="showWalletRechargeDialog"
                   width="450px" :close-on-click-modal="false">
            <div style="margin-bottom:16px;padding:12px;background:#f5f7fa;border-radius:4px;">
                <p style="margin:0;"><strong>当前钱包余额：</strong>￥{{ walletYuan }}</p>
            </div>
            <el-form label-width="90px">
                <el-form-item label="充值金额">
                    <el-input-number v-model="walletRechargeAmount" :min="1" :precision="2"
                                     :step="10" style="width:100%"></el-input-number>
                    <div style="font-size:12px;color:#909399;margin-top:4px;">单位：元</div>
                </el-form-item>
                <el-form-item label="快捷金额">
                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                        <el-button v-for="amt in [10, 50, 100, 200, 500]"
                                   :key="amt" size="mini" @click="walletRechargeAmount = amt">
                            {{amt}}元
                        </el-button>
                    </div>
                </el-form-item>
            </el-form>
            <span slot="footer">
                <el-button @click="showWalletRechargeDialog = false">取 消</el-button>
                <el-button type="primary" :loading="walletRecharging" @click="doWalletRecharge">
                    确认充值
                </el-button>
            </span>
        </el-dialog>
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
            uploadHeaders: { 'authorization': 'Bearer ' + (localStorage.getItem('zm-admin-token') || '') },
            // v3.2：钱包 + Credits 余额（通过 /credits/balance 接口加载）
            walletBalance: 0,          // 钱包余额（分，user.balance）
            creditsBalance: 0,         // Credits 余额
            firstGiftReceived: false,
            showRechargeDialog: false,
            // v3.2：钱包充值（调用 /users/recharge，与前台用户充值逻辑一致）
            showWalletRechargeDialog: false,
            walletRechargeAmount: 100, // 充值金额（元）
            walletRecharging: false,
            // 发货地址管理
            shipAddresses: [],
            shipAddrLoading: false,
            shipAddrDialogVisible: false,
            shipAddrSaving: false,
            shipAddrForm: { id: null, contact: '', mobile: '', province: '', city: '', town: '', street: '', notes: '', isDefault: 0 },
            shipAddrRules: {
                contact: [{ required: true, message: '请输入联系人', trigger: 'blur' }],
                mobile: [{ required: true, message: '请输入联系电话', trigger: 'blur' }],
                province: [{ required: true, message: '请输入省份', trigger: 'blur' }],
                city: [{ required: true, message: '请输入城市', trigger: 'blur' }],
                street: [{ required: true, message: '请输入详细地址', trigger: 'blur' }]
            },
        };
    },
    computed: {
        user() {
            return ZM.getUser();
        },
        // v3.2：钱包余额元（用于展示）
        walletYuan() {
            return (this.walletBalance / 100).toFixed(2);
        },
    },
    mounted() {
        this.loadProfile();
        this.loadCredits();
        this.loadShipAddresses();
    },
    methods: {
        // v3.2：加载钱包 + Credits 余额（/credits/balance 接口返回 walletBalance 字段）
        loadCredits() {
            const userId = (ZM.getUser() || {}).userId || 0;
            if (!userId) return;
            ZM.http.get('/credits/balance/' + userId).then(res => {
                this.creditsBalance = (res && res.balance) || 0;
                this.walletBalance = (res && res.walletBalance) || 0;
                this.firstGiftReceived = !!(res && res.firstGiftReceived);
            }).catch(() => {});
        },
        // v3.2：充值 credits 成功回调
        onRecharged() {
            this.loadCredits();
        },
        // v3.2：钱包充值（与前台用户充值逻辑一致，调用 /users/recharge 接口）
        doWalletRecharge() {
            if (!this.walletRechargeAmount || this.walletRechargeAmount <= 0) {
                this.$message.warning('请输入有效的充值金额');
                return;
            }
            this.walletRecharging = true;
            // 前端输入元，后端接收分（与前台 profile.html 逻辑一致）
            const amountFen = Math.round(this.walletRechargeAmount * 100);
            ZM.http.post('/users/recharge', { amount: amountFen }).then(() => {
                this.walletRecharging = false;
                this.$message.success(`充值成功！已充值 ￥${this.walletRechargeAmount}`);
                this.showWalletRechargeDialog = false;
                this.loadCredits();  // 刷新钱包余额
            }).catch(err => {
                this.walletRecharging = false;
                const msg = (err.response && err.response.data && (err.response.data.msg || err.response.data.message)) || '充值失败';
                this.$message.error(msg);
            });
        },
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
        },
        // ===== 发货地址管理 =====
        loadShipAddresses() {
            this.shipAddrLoading = true;
            ZM.http.get('/merchant/addresses').then(res => {
                this.shipAddrLoading = false;
                this.shipAddresses = Array.isArray(res) ? res : [];
            }).catch(() => {
                this.shipAddrLoading = false;
                this.shipAddresses = [];
            });
        },
        handleAddShipAddr() {
            this.shipAddrForm = { id: null, contact: '', mobile: '', province: '', city: '', town: '', street: '', notes: '', isDefault: 0 };
            this.shipAddrDialogVisible = true;
            this.$nextTick(() => { this.$refs.shipAddrForm && this.$refs.shipAddrForm.clearValidate(); });
        },
        handleEditShipAddr(row) {
            this.shipAddrForm = { ...row };
            this.shipAddrDialogVisible = true;
            this.$nextTick(() => { this.$refs.shipAddrForm && this.$refs.shipAddrForm.clearValidate(); });
        },
        handleSaveShipAddr() {
            this.$refs.shipAddrForm.validate(valid => {
                if (!valid) return;
                this.shipAddrSaving = true;
                const data = { ...this.shipAddrForm };
                const req = data.id
                    ? ZM.http.put('/merchant/addresses/' + data.id, data)
                    : ZM.http.post('/merchant/addresses', data);
                req.then(() => {
                    this.shipAddrSaving = false;
                    this.$message.success(data.id ? '修改成功' : '新增成功');
                    this.shipAddrDialogVisible = false;
                    this.loadShipAddresses();
                }).catch(() => {
                    this.shipAddrSaving = false;
                    this.$message.error(data.id ? '修改失败' : '新增失败');
                });
            });
        },
        handleSetDefaultShipAddr(row) {
            ZM.http.put('/merchant/addresses/' + row.id + '/default').then(() => {
                this.$message.success('已设为当前发货地址');
                this.loadShipAddresses();
            }).catch(() => {
                this.$message.error('设置失败');
            });
        },
        handleDeleteShipAddr(row) {
            this.$confirm('确认删除该发货地址？', '提示', { type: 'warning' }).then(() => {
                ZM.http.delete('/merchant/addresses/' + row.id).then(() => {
                    this.$message.success('删除成功');
                    this.loadShipAddresses();
                }).catch(() => {
                    this.$message.error('删除失败');
                });
            }).catch(() => {});
        }
    }
});
