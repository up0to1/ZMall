/* ============================================================
 * RechargeDialog 充值对话框组件（v3.1）
 *
 * 用法：
 *   <recharge-dialog :show="showRechargeDialog"
 *                   :current-balance="creditsBalance"
 *                   :wallet-balance="walletBalance"
 *                   :first-gift-received="firstGiftReceived"
 *                   @close="showRechargeDialog = false"
 *                   @recharged="onRecharged">
 *   </recharge-dialog>
 *
 * 充值规则（对齐后端 CreditsServiceImpl.calculateRechargeCredits）：
 *   - 1 元 = 5 credits（所有套餐统一）
 *   - 套餐加成：1=无 / 2=+10 / 3=+50 / 4=+150
 *   - 首充赠送 50 credits（仅首次，任意套餐均可享受）
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
  },
  methods: {
    selectPkg(id) { this.selectedPkg = id; },
    async confirm() {
      if (!this.canConfirm) return;
      this.submitting = true;
      try {
        // 直接调 credits 充值接口（后端 CreditsServiceImpl.recharge 内部在同一事务内
        // 扣减 user.balance 钱包余额 + 增加 credits，无需前端先调钱包支付接口）
        // F7 安全修复：userId 由后端从 JWT token 解析，前端不再传
        // 生成幂等支付订单号（前端用时间戳+随机数替代 pay-service 的订单号）
        const payOrderNo = 'CR' + Date.now() + Math.floor(Math.random() * 10000);
        const res = await axios.post('/credits/recharge', {
          amountFen: this.selectedPackage.priceFen,
          payOrderNo,
          packageId: this.selectedPackage.id,
        });
        // 通知父组件刷新余额（credits 和钱包余额都会变化）
        this.$emit('recharged', res);
        const gained = (res && res.balance !== undefined)
          ? (res.balance - this.currentBalance)
          : this.selectedPackage.credits;
        util.toast(`充值成功！获得 ${gained} credits（已从钱包扣款 ￥${this.selectedPackage.priceYuan}）`, 'success');
        this.$emit('close');
      } catch (e) {
        const msg = (e.response && e.response.data && (e.response.data.msg || e.response.data.detail)) || '充值失败';
        util.toast(msg, 'error');
      } finally {
        this.submitting = false;
      }
    },
  },
  template: `
    <div class="modal-mask" v-if="show" @click.self="$emit('close')">
      <div class="modal-box">
        <h3>💎 Credits 充值</h3>
        <div class="modal-info">
          <p><strong>当前 credits 余额：</strong>{{ currentBalance }} credits</p>
          <p><strong>钱包余额：</strong>￥{{ walletYuan }}</p>
        </div>
        <div style="margin: 16px 0 8px; font-weight: bold; color: #333;">选择充值套餐：</div>
        <div class="recharge-packages">
          <div v-for="pkg in packages" :key="pkg.id"
               class="recharge-package"
               :class="{ selected: selectedPkg === pkg.id }"
               @click="selectPkg(pkg.id)">
            <span v-if="pkg.recommended" class="pkg-badge">⭐ 推荐</span>
            <div class="pkg-credits">{{ pkg.credits }} credits</div>
            <div class="pkg-price">￥{{ pkg.priceYuan }}</div>
            <div class="pkg-desc">{{ pkg.desc }}</div>
          </div>
        </div>
        <div style="background: #fff8e1; padding: 10px; border-radius: 4px; font-size: 13px; color: #666;">
          首充赠送 50 credits{{ firstGiftTip }}
        </div>
        <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #eee;">
          <p style="margin: 4px 0; font-size: 14px; color: #555;">
            <strong>应付：</strong>￥{{ selectedPackage.priceYuan }}
          </p>
          <p style="margin: 4px 0; font-size: 13px; color: #999;">
            支付方式：钱包余额（￥{{ walletYuan }}）
            <span v-if="walletBalance < selectedPackage.priceFen" style="color: #e54346;">余额不足，请先充值钱包</span>
          </p>
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="$emit('close')">取消</button>
          <button class="btn-confirm" :disabled="!canConfirm" @click="confirm">
            {{ submitting ? '充值中...' : '确认充值' }}
          </button>
        </div>
      </div>
    </div>
  `,
});
