const topApp = {
  template:`
  <div class="top">
    <div class="py-container">
      <div class="shortcut">
        <ul class="fl">
          <li class="f-item">Michael杂货铺欢迎您！</li>
          <li class="f-item" v-if="!user">
            <a href="/login.html">请登录</a>
            <span><a href="/register.html">免费注册</a></span>
          </li>
          <li class="f-item" v-else>
            欢迎您 <span style="color: #e54346">{{user.username}}</span>
            <span @click="util.logout()"><a href="#">退出登录</a></span>
          </li>
        </ul>
        <ul class="fr">
          <li class="f-item"><a href="/">首页</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="http://localhost:18082/login.html" target="_blank">我是商家</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/cart.html">我的购物车</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/coupon-center.html">优惠券</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/seckill-index.html">秒杀</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/profile.html">个人中心</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/follow-feed.html">关注动态</a></li>
          <li class="f-item space"></li>
          <li class="f-item"><a href="/order.html">我的订单</a></li>
        </ul>
      </div>
    </div>
  </div>
  `,
  data(){
    return {
      user: null,
      util
    }
  },
  mounted(){
    this.user = this.util.store.get("user-info")
  },
  methods:{

  },
}

Vue.component("top", topApp);