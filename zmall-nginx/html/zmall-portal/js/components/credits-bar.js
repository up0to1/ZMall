/* ============================================================
 * CreditsBar 顶部余额展示组件（v3.1）
 *
 * 用法：
 *   <credits-bar :balance="creditsBalance"
 *                :expiring-soon="expiringSoon"
 *                :nearest-expiry="nearestExpiry"
 *                @recharge="showRechargeDialog = true">
 *   </credits-bar>
 *
 * 行为：
 *   - balance < 7：黄色高亮"余额不足，建议充值"
 *   - balance = 0：红色闪烁，强烈提示
 *   - expiringSoon > 0：橙色提示条"X credits 即将过期"
 * ============================================================ */
Vue.component('credits-bar', {
  props: {
    balance: { type: Number, default: 0 },
    expiringSoon: { type: Number, default: 0 },
    nearestExpiry: { type: String, default: '' },
    serviceAvailable: { type: Boolean, default: true },
  },
  computed: {
    // M8 修复：优先用 serviceAvailable prop，兼容旧版 balance=-1 哨兵
    serviceUnavailable() { return !this.serviceAvailable || this.balance === -1; },
    displayBalance() { return this.serviceUnavailable ? 0 : this.balance; },
    barClass() {
      if (this.serviceUnavailable) return 'low';
      if (this.balance === 0) return 'zero';
      if (this.balance < 7) return 'low';
      return '';
    },
    expiryText() {
      if (!this.expiringSoon || this.expiringSoon <= 0) return '';
      const dt = this.nearestExpiry ? new Date(this.nearestExpiry) : null;
      const dtStr = dt ? `${dt.getMonth() + 1}月${dt.getDate()}日` : '';
      return `${this.expiringSoon} credits 即将于 ${dtStr} 过期，请尽快使用`;
    },
  },
  template: `
    <div>
      <div class="expiring-tip" v-if="expiryText">{{ expiryText }}</div>
      <div class="credits-bar" :class="barClass">
        <span class="credits-icon">💎</span>
        <span class="credits-text">{{ serviceUnavailable ? '余额：服务不可用' : ('余额：' + displayBalance + ' credits') }}</span>
        <button class="btn-recharge" @click="$emit('recharge')">充值</button>
        <span class="credits-tip">首充赠送 50 credits · 1 元 = 5 credits</span>
      </div>
    </div>
  `,
});
