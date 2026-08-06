/* ============================================================
 * RechargeDialog 后台 Credits 充值对话框（Element UI 风格）
 *
 * 用法：
 *   <recharge-dialog :show.sync="showRechargeDialog"
 *                    :current-balance="creditsBalance"
 *                    :wallet-balance="walletBalance"
 *                    :first-gift-received="firstGiftReceived"
 *                    @recharged="onRecharged">
 *   </recharge-dialog>
 *
 * 充值规则（对齐后端 CreditsServiceImpl.calculateRechargeCredits）：
 *   - 1 元 = 5 credits（所有套餐统一）
 *   - 套餐加成：1=无 / 2=+10 / 3=+50 / 4=+150
 *   - 首充赠送 50 credits（仅首次，任意套餐均可享受）
 *
 * 与前台 recharge-dialog.js 的差异：
 *   - 使用 Element UI（el-dialog / el-radio / el-button）而非原生 HTML
 *   - 使用 ZM.http 而非 axios（baseURL 已配置 /api）
 *   - 使用 this.$message 显示提示（Element UI Message）
 *   - userId 通过 ZM.getUser() 获取
 * ============================================================ */
Vue.component('recharge-dialog', {
  props: {
    show: { type: Boolean, default: false },
    currentBalance: { type: Number, default: 0 },
    walletBalance: { type: Number, default: 0 },  // 钱包余额（分）
    firstGiftReceived: { type: Boolean, default: false },
  },
  data() {
    return {
      packages: [
        { id: 1, credits: 50,  priceFen: 1000,  priceYuan: 10,  desc: '基础 50，无加成' },
        { id: 2, credits: 110, priceFen: 2000,  priceYuan: 20,  desc: '基础 100 + 加成 10', recommended: true },
        { id: 3, credits: 300, priceFen: 5000,  priceYuan: 50,  desc: '基础 250 + 加成 50' },
        { id: 4, credits: 650, priceFen: 10000, priceYuan: 100, desc: '基础 500 + 加成 150' },
      ],
      selectedPkg: 2,
      submitting: false,
    };
  },
  computed: {
    walletYuan() {
      return (this.walletBalance / 100).toFixed(2);
    },
    selectedPackage() {
      return this.packages.find(p => p.id === this.selectedPkg);
    },
    canConfirm() {
      if (this.submitting) return false;
      if (this.walletBalance < this.selectedPackage.priceFen) return false;
      return true;
    },
    firstGiftTip() {
      return this.firstGiftReceived
        ? '（首充赠送已发放过，本次不再赠送）'
        : `（首充额外赠送 50 credits，本次实得 ${this.selectedPackage.credits + 50} credits）`;
    },
    // 桥接 prop show 与 el-dialog 的 :visible.sync（避免直接修改 prop）
    dialogVisible: {
      get() { return this.show; },
      set(val) { if (!val) this.handleClose(); },
    },
  },
  methods: {
    selectPkg(id) { this.selectedPkg = id; },
    handleClose() {
      this.$emit('close');
    },
    async confirm() {
      if (!this.canConfirm) return;
      this.submitting = true;
      try {
        // 直接调 credits 充值接口（后端 CreditsServiceImpl.recharge 内部在同一事务内
        // 扣减 user.balance 钱包余额 + 增加 credits，无需前端先调钱包支付接口）
        const userId = (ZM.getUser() || {}).userId || 0;
        // 生成幂等支付订单号（前端用 UUID 替代 pay-service 的订单号）
        const payOrderNo = 'CR' + Date.now() + Math.floor(Math.random() * 10000);
        const res = await ZM.http.post('/credits/recharge', {
          userId,
          amountFen: this.selectedPackage.priceFen,
          payOrderNo,
          packageId: this.selectedPackage.id,
        });
        // 通知父组件刷新余额（credits 和钱包余额都会变化）
        this.$emit('recharged', res);
        const gained = (res && res.balance !== undefined)
          ? (res.balance - this.currentBalance)
          : this.selectedPackage.credits;
        this.$message.success(`充值成功！获得 ${gained} credits（已从钱包扣款 ￥${this.selectedPackage.priceYuan}）`);
        this.handleClose();
      } catch (e) {
        const msg = (e.response && e.response.data && (e.response.data.msg || e.response.data.detail)) || '充值失败';
        this.$message.error(msg);
      } finally {
        this.submitting = false;
      }
    },
  },
  template: `
    <el-dialog title="💎 Credits 充值"
               :visible.sync="dialogVisible"
               width="560px"
               :close-on-click-modal="false"
               @close="handleClose">
      <div style="margin-bottom:16px;padding:12px;background:#f5f7fa;border-radius:4px;">
        <p style="margin:0 0 6px;"><strong>当前 credits 余额：</strong>{{ currentBalance }} credits</p>
        <p style="margin:0;"><strong>钱包余额：</strong>￥{{ walletYuan }}</p>
      </div>

      <div style="margin: 8px 0 12px; font-weight: bold; color: #333;">选择充值套餐：</div>
      <el-radio-group v-model="selectedPkg" style="display:block;">
        <div v-for="pkg in packages" :key="pkg.id"
             style="display:flex;align-items:center;padding:12px;margin-bottom:8px;
                    border:1px solid #e4e7ed;border-radius:4px;cursor:pointer;"
             :style="{borderColor: selectedPkg === pkg.id ? '#409eff' : '#e4e7ed',
                       background: selectedPkg === pkg.id ? '#ecf5ff' : '#fff'}"
             @click="selectPkg(pkg.id)">
          <el-radio :label="pkg.id" style="margin-right:12px;">
            <span></span>
          </el-radio>
          <div style="flex:1;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <span style="font-size:16px;font-weight:bold;color:#303133;">{{ pkg.credits }} credits</span>
              <el-tag v-if="pkg.recommended" type="warning" size="mini" style="margin-left:8px;">⭐ 推荐</el-tag>
              <div style="font-size:12px;color:#909399;margin-top:2px;">{{ pkg.desc }}</div>
            </div>
            <div style="font-size:18px;font-weight:bold;color:#e6a23c;">￥{{ pkg.priceYuan }}</div>
          </div>
        </div>
      </el-radio-group>

      <el-alert type="warning" :closable="false" style="margin:12px 0;">
        <template slot="title">
          首充赠送 50 credits{{ firstGiftTip }}
        </template>
      </el-alert>

      <div style="padding:12px;border-top:1px solid #ebeef5;">
        <p style="margin:4px 0;font-size:14px;color:#555;">
          <strong>应付：</strong>￥{{ selectedPackage.priceYuan }}
        </p>
        <p style="margin:4px 0;font-size:13px;color:#909399;">
          支付方式：钱包余额（￥{{ walletYuan }}）
          <span v-if="walletBalance < selectedPackage.priceFen" style="color:#f56c6c;">
            余额不足，请先充值钱包
          </span>
        </p>
      </div>

      <span slot="footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canConfirm" @click="confirm">
          {{ submitting ? '充值中...' : '确认充值' }}
        </el-button>
      </span>
    </el-dialog>
  `,
});
