// 设置后台服务地址
axios.defaults.baseURL = "/api";
axios.defaults.timeout = 15000;
// request拦截器
axios.interceptors.request.use(
  config => {
    const token = localStorage.getItem("token")
    if (token) config.headers['authorization'] = 'Bearer ' + token
    return config
  }
)
// 响应拦截器
axios.interceptors.response.use(
  response => response.data,
  err => {
    const status = err.response && err.response.status;
    const data = err.response && err.response.data || {};
    if (status === 401) {
      // 认证失败，需要重新登录
      console.warn('[401拦截] URL=' + (err.config && err.config.url) + ', 即将清除token并跳转登录页');
      localStorage.removeItem("user-info")
      localStorage.removeItem("token")
      location.href = "/login.html?return=" + encodeURIComponent(location.href);
    } else if (status === 403 && data.errorCode !== 'CONCURRENT') {
      // v3.1 credits 不足（非并发限流）：交由调用方自行处理（弹余额不足对话框）
      // 不在拦截器里统一 alert，便于各页面按 §5.8.3 弹定制对话框
      console.warn('[403余额不足] URL=' + (err.config && err.config.url) + ', msg=' + (data.msg || ''));
    } else if (status === 404) {
      // v3 任务过期：交由调用方处理（多数情况下跳 outfit-agent.html）
      console.warn('[404任务不存在] URL=' + (err.config && err.config.url) + ', detail=' + (data.detail || data.msg || ''));
    } else if (status === 409) {
      // v3 状态冲突：交由调用方处理（刷新页面状态）
      console.warn('[409状态冲突] URL=' + (err.config && err.config.url) + ', detail=' + (data.detail || data.msg || ''));
    } else if (status === 429 || (status === 403 && data.errorCode === 'CONCURRENT')) {
      // v3 并发限流
      const reqUrl = (err.config && err.config.url) || '';
      const isOutfitApi = reqUrl.indexOf('/outfit/agent/') >= 0 || reqUrl.indexOf('/outfit/product/') >= 0;
      // 结果轮询接口（GET result）限流静默处理：轮询器内部会继续重试，弹窗只会误导用户
      // （网关侧对 result 接口已放宽限流，极端情况下的 429 由轮询器自愈）
      const isResultPoll = reqUrl.indexOf('/outfit/agent/result/') >= 0 || reqUrl.indexOf('/outfit/result/') >= 0;
      if (isResultPoll) {
        console.warn('[429结果轮询限流] URL=' + reqUrl + ', detail=' + (data.detail || ''));
      } else if (isOutfitApi && data.errorCode === 'CONCURRENT') {
        util.toast(data.detail || data.msg || '上一条搭配还在生成中，请稍候', 'warning');
      } else if (isOutfitApi) {
        util.toast(data.detail || data.msg || '操作过于频繁，请稍候', 'warning');
      }
      // 非搭配接口的 429 交给调用方处理（避免误导性提示）
    } else if (status >= 500 || err.response === undefined) {
      // 5xx 或网络断开：统一提示，避免调用方静默失败
      util.toast(data.msg || data.detail || '网络异常，请稍后重试', 'error');
    }
    return Promise.reject(err)
  }
)
const util = {
  isLogin(){
    return !!localStorage.getItem("user-info");
  },
  logout(){
    // JWT 无状态：后端暂无 logout 接口，token 过期前仍有效
    // 清除 localStorage 后刷新页面，token 从内存中移除
    localStorage.removeItem("user-info")
    localStorage.removeItem("token")
    location.reload();
  },
  getUserId() {
    // v3.1：从 localStorage 的 user-info 解析 userId
    // 兼容旧版直接存 {id} 与新版存 {user:{id}} 两种格式
    const info = JSON.parse(localStorage.getItem("user-info") || '{}');
    return info.id || (info.user && info.user.id) || null;
  },
  getUrlParam(name) {
    let reg = new RegExp("(^|&)" + name + "=([^&]*)(&|$)", "i");
    let r = window.location.search.substr(1).match(reg);
    if (r != null) {
      return decodeURI(r[2]);
    }
    return "";
  },
  // v3.1：Toast 全局提示（替代 alert，更友好）
  toast(msg, type) {
    type = type || 'info';
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transition = 'opacity 0.3s';
      setTimeout(() => document.body.removeChild(t), 300);
    }, 2500);
  },
  // v3.1：照片会话 Key 管理（多页面共用，TTL 30min 与后端对齐）
  savePhotoSession(key) {
    localStorage.setItem('outfit_photo_session', key);
  },
  getPhotoSession() {
    return localStorage.getItem('outfit_photo_session') || null;
  },
  clearPhotoSession() {
    localStorage.removeItem('outfit_photo_session');
  },
  hasUserPhoto() {
    // 场景 B 判定：localStorage 中是否存在照片会话 Key
    // 后端 WS 不推送 useDefaultModel，前端用此字段判断"重新 VTON"按钮是否禁用
    return !!localStorage.getItem('outfit_photo_session');
  },
  formatPrice(val) {
    if (typeof val === 'string') {
      if (isNaN(val)) {
        return null;
      }
      // 价格转为整数
      const index = val.lastIndexOf(".");
      let p = "";
      if (index < 0) {
        // 无小数
        p = val + "00";
      } else if (index === val.length - 2) {
        // 1位小数
        p = val.replace("\.", "") + "0";
      } else {
        // 2位小数
        p = val.replace("\.", "")
      }
      return parseInt(p);
    } else if (typeof val === 'number') {
      if (val == null) {
        return null;
      }
      const s = val + '';
      if (s.length === 0) {
        return "0.00";
      }
      if (s.length === 1) {
        return "0.0" + val;
      }
      if (s.length === 2) {
        return "0." + val;
      }
      const i = s.indexOf(".");
      if (i < 0) {
        return s.substring(0, s.length - 2) + "." + s.substring(s.length - 2)
      }
      const num = s.substring(0, i) + s.substring(i + 1);
      if (i === 1) {
        // 1位整数
        return "0.0" + num;
      }
      if (i === 2) {
        return "0." + num;
      }
      if (i > 2) {
        return num.substring(0, i - 2) + "." + num.substring(i - 2)
      }
    }
  },
  store: {
    set(key, obj) {
      localStorage.setItem(key, JSON.stringify(obj))
    },
    get(key) {
      return JSON.parse(localStorage.getItem(key))
    }
  },
  // ===== 用户城市定位（天气服务用）=====
  // 通过 ipapi.co 获取用户城市名，存 localStorage（TTL 30 分钟）
  // 缓存有效时续期，过期后由页面弹窗重新询问用户是否允许获取定位
  _userCityCache: null,  // 内存缓存（同一次页面生命周期内）
  _userCountryCache: null,  // 国家内存缓存（与城市缓存生命周期一致）
  // 实际请求 IP 定位 API（ipapi.co 支持 HTTPS，兼容 Mixed Content 策略）
  // 返回 city（英文）+ country_name + country_code（ISO 如 CN/JP/US）
  async requestUserCity() {
    try {
      console.log('[城市定位] 正在请求 ipapi.co 获取定位...');
      const res = await axios.get('https://ipapi.co/json/', { timeout: 3000 });
      if (res && res.city) {
        const city = res.city;
        const countryCode = res.country_code || null;
        const ip = res.ip || '未知';
        console.log('[城市定位] 成功: ip=%s, city=%s, country=%s', ip, city, countryCode);
        util._userCityCache = city;
        util._userCountryCache = countryCode;
        localStorage.setItem('user_city_cache', JSON.stringify({ city: city, country: countryCode, ts: Date.now() }));
        return city;
      }
      console.warn('[城市定位] ipapi.co 返回无 city 字段: %o', res);
    } catch (e) {
      console.warn('[城市定位] ipapi.co 请求失败: %s', e.message || e);
    }
    // 定位失败，缓存 null，后端用"北京"兜底
    console.log('[城市定位] 定位失败，后端将使用默认城市"北京"');
    util._userCityCache = null;
    util._userCountryCache = null;
    localStorage.setItem('user_city_cache', JSON.stringify({ city: null, country: null, ts: Date.now() }));
    return null;
  },
  // 用户拒绝授权时，缓存"北京"作为兜底城市
  setDefaultCity() {
    console.log('[城市定位] 用户选择使用默认城市"北京"');
    util._userCityCache = '北京';
    util._userCountryCache = null;
    localStorage.setItem('user_city_cache', JSON.stringify({ city: '北京', country: null, ts: Date.now() }));
  },
  // 续期城市缓存 TTL：刷新/重进页面时若缓存仍有效，把时间戳更新为当前时间
  // 这样用户持续使用时缓存不会过期；只有 30 分钟内无活动才会失效
  renewCityCache() {
    try {
      const cached = JSON.parse(localStorage.getItem('user_city_cache') || 'null');
      if (cached && cached.city) {
        cached.ts = Date.now();
        localStorage.setItem('user_city_cache', JSON.stringify(cached));
        console.log('[城市定位] 缓存续期: city=%s, TTL 30min', cached.city);
      }
    } catch (e) { /* ignore */ }
  },
  // 获取用户城市（不主动发起 IP 请求）
  // 返回值：城市名字符串；缓存失效返回 null（页面弹窗重新询问，后端兜底"北京"）
  // 注意：本方法不会触发 IP 请求，需先通过页面弹窗获得用户许可后调用 requestUserCity()
  getUserCity() {
    // 1. 内存缓存命中（同一次页面生命周期）
    if (util._userCityCache !== null) {
      return util._userCityCache;
    }
    // 2. localStorage 缓存命中（TTL 30 分钟，跨刷新有效）
    try {
      const cached = JSON.parse(localStorage.getItem('user_city_cache') || 'null');
      if (cached && cached.city && (Date.now() - cached.ts < 30 * 60 * 1000)) {
        util._userCityCache = cached.city;
        console.log('[城市定位] localStorage 缓存命中: city=%s, country=%s', cached.city, cached.country);
        return cached.city;
      }
      if (cached) {
        console.log('[城市定位] 缓存已过期（超过 30 分钟），将重新弹窗询问');
      }
    } catch (e) { /* ignore */ }
    // 3. 缓存失效或不存在：返回 null（页面弹窗重新询问，后端兜底"北京"）
    return null;
  },
  // 提交搭配前校验城市缓存：过期则静默刷新定位，刷新失败用"北京"兜底
  // 返回 { city, country }，保证总有值（不会返回 null）
  async ensureCityFresh() {
    let city = util.getUserCity();
    if (city !== null) {
      // 缓存有效，直接返回
      return { city: city, country: util.getUserCountry() };
    }
    // 缓存过期：静默刷新定位（不弹窗，用户已在使用功能）
    console.log('[城市定位] 提交搭配时发现缓存过期，静默刷新定位...');
    city = await util.requestUserCity();
    if (city === null) {
      // 刷新失败，用"北京"兜底
      util.setDefaultCity();
      city = '北京';
    }
    return { city: city, country: util.getUserCountry() };
  },
  // 获取用户国家（与 getUserCity 同源，用于时尚趋势查询）
  // 返回值：国家名字符串；未定位或缓存失效返回 null（后端走默认）
  getUserCountry() {
    // 1. 内存缓存命中
    if (util._userCountryCache !== null) {
      return util._userCountryCache;
    }
    // 2. localStorage 缓存命中（与城市缓存同对象同 TTL）
    try {
      const cached = JSON.parse(localStorage.getItem('user_city_cache') || 'null');
      if (cached && cached.country && (Date.now() - cached.ts < 30 * 60 * 1000)) {
        util._userCountryCache = cached.country;
        return cached.country;
      }
    } catch (e) { /* ignore */ }
    // 3. 缓存失效或未定位：返回 null
    return null;
  }
}
