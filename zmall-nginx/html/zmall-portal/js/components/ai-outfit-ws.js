/* ============================================================
 * AI 随心搭 WebSocket 工具（v3.2）
 *
 * 用法：
 *   const ws = new AiOutfitWS(userId, taskId, {
 *     onMessage: (msg) => { ... },
 *     onClose: () => { ... },  // 默认降级轮询
 *   });
 *   ws.connect();
 *   // ...
 *   ws.close();
 *
 * 端点：ws://host/ws/ai/{userId}（Gateway 透传，鉴权用 user-info header）
 * F8 修复：token 不再暴露在 URL query，改为 onopen 后发送 auth 消息
 * 心跳：客户端 30s 发送 "ping"，服务端回 "pong"
 * ============================================================ */
function AiOutfitWS(userId, taskId, options) {
  this.userId = userId;
  this.taskId = taskId;
  this.options = options || {};
  this.ws = null;
  this.heartbeatTimer = null;
  this.closed = false;  // 主动关闭标记，避免触发 onClose 回调
  this.authenticated = false;  // F8: 鉴权完成标记
}

AiOutfitWS.prototype.connect = function() {
  const self = this;
  // 兼容 https → wss
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.hostname + ':' + (location.port || (proto === 'wss:' ? 443 : 80));
  // F8 修复：token 不再放在 URL query 中，改为 onopen 后发送 auth 消息
  const url = `${proto}//${host}/ws/ai/${this.userId}`;
  try {
    this.ws = new WebSocket(url);
  } catch (e) {
    console.warn('[WS] 连接失败，降级轮询', e);
    if (this.options.onClose) this.options.onClose();
    return;
  }

  this.ws.onopen = function() {
    console.log('[WS] 已连接，发送 auth: taskId=' + self.taskId);
    // F8 修复：onopen 后发送 auth 消息，token 不暴露在 URL
    const token = localStorage.getItem('token') || '';
    try {
      self.ws.send(JSON.stringify({ type: 'auth', token: token }));
    } catch (e) {
      console.warn('[WS] 发送 auth 失败，降级轮询', e);
      if (self.options.onClose) self.options.onClose();
    }
  };

  this.ws.onmessage = function(e) {
    if (e.data === 'pong') return;  // 心跳响应
    try {
      const msg = JSON.parse(e.data);
      // F8: 处理 auth 响应
      if (msg.type === 'auth_ok') {
        console.log('[WS] 鉴权成功: taskId=' + self.taskId);
        self.authenticated = true;
        // 启动心跳
        self.heartbeatTimer = setInterval(function() {
          if (self.ws && self.ws.readyState === WebSocket.OPEN) {
            try { self.ws.send('ping'); } catch (e) {}
          }
        }, 30000);
        return;
      }
      if (msg.type === 'auth_fail') {
        console.warn('[WS] 鉴权失败，降级轮询: taskId=' + self.taskId);
        if (self.options.onClose) self.options.onClose();
        return;
      }
      // 仅处理当前任务的消息
      if (self.taskId && msg.taskId && msg.taskId !== self.taskId) return;
      if (self.options.onMessage) self.options.onMessage(msg);
    } catch (err) {
      console.warn('[WS] 消息解析失败', err, e.data);
    }
  };

  this.ws.onclose = function() {
    console.log('[WS] 连接关闭');
    if (self.heartbeatTimer) {
      clearInterval(self.heartbeatTimer);
      self.heartbeatTimer = null;
    }
    // 主动关闭不触发降级；被动关闭才降级
    if (!self.closed && self.options.onClose) {
      self.options.onClose();
    }
  };

  this.ws.onerror = function(err) {
    console.warn('[WS] 错误', err);
    // P2 修复：onerror 也要清理心跳定时器，避免持续向已损坏的 WS send('ping')
    if (self.heartbeatTimer) {
      clearInterval(self.heartbeatTimer);
      self.heartbeatTimer = null;
    }
  };
};

AiOutfitWS.prototype.close = function() {
  this.closed = true;
  if (this.heartbeatTimer) {
    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }
  if (this.ws) {
    try { this.ws.close(); } catch (e) {}
    this.ws = null;
  }
};

// ============================================================
// 任务轮询工具（WS 断开时降级使用）
// 策略：前 10s 每 2s 一次，之后每 5s 一次，最长 610s（与后端动态超时上限 600s 对齐）
// ============================================================
function AiOutfitPoller(taskId, options) {
  this.taskId = taskId;
  this.options = options || {};
  this.phases = [
    { interval: 2000, count: 5 },    // 前 10s：每 2s
    { interval: 5000, count: 120 },  // 之后：每 5s，持续 600s（与后端动态超时上限 600s 对齐）
  ];
  this.stopped = false;
}

AiOutfitPoller.prototype.start = function() {
  const self = this;
  let phaseIdx = 0;
  let countInPhase = 0;

  function next() {
    if (self.stopped) return;
    if (phaseIdx >= self.phases.length) {
      console.warn('[Poller] 超时');
      if (self.options.onTimeout) self.options.onTimeout();
      return;
    }
    const phase = self.phases[phaseIdx];
    // P0 修复：商品驱动模式结果查询走 /v1/outfit/result/，风格驱动走 /v1/outfit/agent/result/
    // 由调用方通过 options.resultPath 指定，默认风格驱动路径（向后兼容）
    const resultPath = self.options.resultPath || '/v1/outfit/agent/result/';
    axios.get(resultPath + self.taskId).then(function(res) {
      if (self.stopped) return;
      // axios 响应拦截器已返回 response.data，res 即业务数据对象
      const data = res || {};
      if (self.options.onResult) self.options.onResult(data);
      // 终态停止轮询
      if (data.status === 'SUCCESS' || data.status === 'FAILED' || data.status === 'ACCEPTED') {
        return;
      }
      // 继续下一轮
      countInPhase++;
      if (countInPhase >= phase.count) {
        phaseIdx++;
        countInPhase = 0;
      }
      setTimeout(next, phase.interval);
    }).catch(function(err) {
      if (self.stopped) return;
      console.warn('[Poller] 查询失败', err);
      if (err.response && err.response.status === 404) {
        if (self.options.onNotFound) self.options.onNotFound(err);
        return;
      }
      // 出错继续轮询
      countInPhase++;
      if (countInPhase >= phase.count) {
        phaseIdx++;
        countInPhase = 0;
      }
      setTimeout(next, phase.interval);
    });
  }
  next();
};

AiOutfitPoller.prototype.stop = function() {
  this.stopped = true;
};

// ============================================================
// Loading 浮层工具（分阶段进度文案）
// ============================================================
function AiOutfitLoading(options) {
  this.options = options || {};
  this.timer = null;
  this.startTime = 0;
  this.el = null;
  this.phases = [
    { until: 5000,   text: 'AI 正在理解你的需求...',     sub: '解析风格 / 颜色 / 场景' },
    { until: 15000,  text: '正在从全平台商品中检索...',  sub: '向量检索互补商品' },
    { until: 30000,  text: 'AI 审美决策中，挑选 Top3 搭配...', sub: 'LLM 评估搭配候选' },
    { until: 60000,  text: '正在生成换装效果图...',       sub: 'VTON 虚拟试衣（第 1-2 套）' },
    { until: 120000, text: '正在生成换装效果图...',       sub: 'VTON 虚拟试衣（第 3 套）' },
    { until: 180000, text: '快好了，正在最后调整...',     sub: '图片合成与上传' },
  ];
}

AiOutfitLoading.prototype.show = function() {
  const self = this;
  this.startTime = Date.now();
  this.el = document.createElement('div');
  this.el.className = 'loading-overlay';
  this.el.innerHTML = `
    <div class="loading-spinner"></div>
    <div class="loading-text">AI 正在理解你的需求...</div>
    <div class="loading-subtext">解析风格 / 颜色 / 场景</div>
    <div class="loading-progress"><div class="loading-progress-bar" style="width:5%"></div></div>
  `;
  document.body.appendChild(this.el);

  this.timer = setInterval(function() {
    const elapsed = Date.now() - self.startTime;
    const phase = self.phases.find(p => elapsed < p.until) || self.phases[self.phases.length - 1];
    const textEl = self.el.querySelector('.loading-text');
    const subEl = self.el.querySelector('.loading-subtext');
    const barEl = self.el.querySelector('.loading-progress-bar');
    if (textEl) textEl.textContent = phase.text;
    if (subEl) subEl.textContent = phase.sub;
    if (barEl) {
      const pct = Math.min(95, Math.floor(elapsed / 180000 * 100));
      barEl.style.width = pct + '%';
    }
  }, 500);
};

AiOutfitLoading.prototype.hide = function() {
  if (this.timer) {
    clearInterval(this.timer);
    this.timer = null;
  }
  if (this.el && this.el.parentNode) {
    this.el.parentNode.removeChild(this.el);
  }
  this.el = null;
};
