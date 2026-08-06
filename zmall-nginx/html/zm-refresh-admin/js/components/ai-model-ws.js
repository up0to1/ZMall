/* ============================================================
 * AI 模特图 WebSocket + 轮询降级 + Loading 工具（v3.2）
 *
 * 用法：
 *   const ws = new AiModelWS(userId, taskId, {
 *     onMessage: (msg) => { ... },   // msg.type === 'AI_MODEL'
 *     onClose: () => { ...},          // 默认降级轮询
 *   });
 *   ws.connect();
 *   ws.close();
 *
 * 端点：ws://host/ws/model/{userId}
 *      Gateway 透传，鉴权用 user-info header 或首条 auth 消息
 * F8 修复：token 不再暴露在 URL query，改为 onopen 后发送 auth 消息
 * 心跳：客户端 30s 发送 "ping"，服务端回 "pong"
 *
 * 轮询策略：前 10s 每 2s 一次，之后每 5s 一次，最长 660s（与 Java 超时阈值 11min 对齐）
 * ============================================================ */

// AI 模特图任务 WS 连接
function AiModelWS(userId, taskId, options) {
  this.userId = userId;
  this.taskId = taskId;
  this.options = options || {};
  this.ws = null;
  this.heartbeatTimer = null;
  this.closed = false;
  this.authenticated = false;  // F8: 鉴权完成标记
}

AiModelWS.prototype.connect = function () {
  const self = this;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.hostname + ':' + (location.port || (proto === 'wss:' ? 443 : 80));
  // F8 修复：token 不再放在 URL query 中，改为 onopen 后发送 auth 消息
  const url = `${proto}//${host}/ws/model/${this.userId}`;
  try {
    this.ws = new WebSocket(url);
  } catch (e) {
    console.warn('[AiModelWS] 连接失败，降级轮询', e);
    if (this.options.onClose) this.options.onClose();
    return;
  }

  this.ws.onopen = function () {
    console.log('[AiModelWS] 已连接，发送 auth: taskId=' + self.taskId);
    // F8 修复：onopen 后发送 auth 消息，token 不暴露在 URL
    // 管理后台用 zm-admin-token
    const token = localStorage.getItem('zm-admin-token') || '';
    try {
      self.ws.send(JSON.stringify({ type: 'auth', token: token }));
    } catch (e) {
      console.warn('[AiModelWS] 发送 auth 失败，降级轮询', e);
      if (self.options.onClose) self.options.onClose();
    }
  };

  this.ws.onmessage = function (e) {
    if (e.data === 'pong') return;
    try {
      const msg = JSON.parse(e.data);
      // F8: 处理 auth 响应
      if (msg.type === 'auth_ok') {
        console.log('[AiModelWS] 鉴权成功: taskId=' + self.taskId);
        self.authenticated = true;
        // 启动心跳
        self.heartbeatTimer = setInterval(function () {
          if (self.ws && self.ws.readyState === WebSocket.OPEN) {
            try { self.ws.send('ping'); } catch (e) {}
          }
        }, 30000);
        return;
      }
      if (msg.type === 'auth_fail') {
        console.warn('[AiModelWS] 鉴权失败，降级轮询: taskId=' + self.taskId);
        if (self.options.onClose) self.options.onClose();
        return;
      }
      // 仅处理当前任务的消息
      if (self.taskId && msg.taskId && msg.taskId !== self.taskId) return;
      if (self.options.onMessage) self.options.onMessage(msg);
    } catch (err) {
      console.warn('[AiModelWS] 消息解析失败', err, e.data);
    }
  };

  this.ws.onclose = function () {
    console.log('[AiModelWS] 连接关闭');
    if (self.heartbeatTimer) {
      clearInterval(self.heartbeatTimer);
      self.heartbeatTimer = null;
    }
    if (!self.closed && self.options.onClose) {
      self.options.onClose();
    }
  };

  this.ws.onerror = function (err) {
    console.warn('[AiModelWS] 错误', err);
    // M9 修复：onerror 时清理心跳定时器，避免向已损坏的 ws 发送 ping
    if (self.heartbeatTimer) {
      clearInterval(self.heartbeatTimer);
      self.heartbeatTimer = null;
    }
  };
};

AiModelWS.prototype.close = function () {
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
// 策略：前 10s 每 2s 一次，之后每 5s 一次，最长 660s（11min，与 Java 超时阈值对齐）
// ============================================================
function AiModelPoller(taskId, options) {
  this.taskId = taskId;
  this.options = options || {};
  this.phases = [
    { interval: 2000, count: 5 },    // 前 10s：每 2s
    { interval: 5000, count: 130 },  // 之后 650s：每 5s（共 660s = 11min）
  ];
  this.stopped = false;
}

AiModelPoller.prototype.start = function () {
  const self = this;
  let phaseIdx = 0;
  let countInPhase = 0;

  function next() {
    if (self.stopped) return;
    if (phaseIdx >= self.phases.length) {
      console.warn('[AiModelPoller] 超时');
      if (self.options.onTimeout) self.options.onTimeout();
      return;
    }
    const phase = self.phases[phaseIdx];
    ZM.http.get('/items/admin/ai-model/task/' + self.taskId).then(function (res) {
      if (self.stopped) return;
      if (self.options.onResult) self.options.onResult(res);
      // 终态停止轮询
      if (res && (res.status === 'SUCCESS' || res.status === 'FAILED' || res.status === 'TIMEOUT')) {
        return;
      }
      countInPhase++;
      if (countInPhase >= phase.count) {
        phaseIdx++;
        countInPhase = 0;
      }
      setTimeout(next, phase.interval);
    }).catch(function (err) {
      if (self.stopped) return;
      console.warn('[AiModelPoller] 查询失败', err);
      if (err.response && err.response.status === 404) {
        if (self.options.onNotFound) self.options.onNotFound(err);
        return;
      }
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

AiModelPoller.prototype.stop = function () {
  this.stopped = true;
};

// ============================================================
// Loading 浮层（多商品链式 VTON 进度文案）
// ============================================================
function AiModelLoading(options) {
  this.options = options || {};
  this.timer = null;
  this.startTime = 0;
  this.el = null;
  this.phases = [
    { until: 3000,   text: 'AI 正在分析商品图...',           sub: '解析品类 / 颜色 / 风格' },
    { until: 8000,   text: '正在选定契合的模特图...',         sub: '从系统池匹配肤色 / 气质' },
    { until: 20000,  text: 'AI 正在生成模特图...',           sub: '链式 VTON 试衣合成' },
    { until: 60000,  text: '多商品合成中，请耐心等待...',     sub: '逐个商品 VTON + 图融合' },
    { until: 180000, text: '快好了，正在最后调整...',         sub: '图片合成与上传 OSS' },
    { until: 660000, text: '多图模式耗时较长，请耐心等待...', sub: '多套搭配并行生成中（11min 超时阈值）' },
  ];
}

AiModelLoading.prototype.show = function () {
  const self = this;
  this.startTime = Date.now();
  this.el = document.createElement('div');
  this.el.className = 'ai-model-loading-overlay';
  this.el.innerHTML = `
    <div class="ai-model-loading-box">
      <div class="ai-model-loading-spinner"></div>
      <div class="ai-model-loading-text">AI 正在分析商品图...</div>
      <div class="ai-model-loading-subtext">解析品类 / 颜色 / 风格</div>
      <div class="ai-model-loading-progress"><div class="ai-model-loading-progress-bar" style="width:5%"></div></div>
    </div>
  `;
  // 注入样式（仅一次）
  if (!document.getElementById('ai-model-loading-style')) {
    const style = document.createElement('style');
    style.id = 'ai-model-loading-style';
    style.textContent = `
      .ai-model-loading-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.55); z-index: 9999;
        display: flex; align-items: center; justify-content: center;
      }
      .ai-model-loading-box {
        background: #fff; padding: 32px 48px; border-radius: 12px;
        text-align: center; min-width: 360px; box-shadow: 0 8px 24px rgba(0,0,0,0.2);
      }
      .ai-model-loading-spinner {
        width: 48px; height: 48px; border: 4px solid #f0f0f0;
        border-top-color: #e54346; border-radius: 50%;
        margin: 0 auto 16px; animation: ai-model-spin 0.8s linear infinite;
      }
      @keyframes ai-model-spin { to { transform: rotate(360deg); } }
      .ai-model-loading-text { font-size: 16px; color: #333; font-weight: bold; margin-bottom: 4px; }
      .ai-model-loading-subtext { font-size: 13px; color: #999; margin-bottom: 16px; }
      .ai-model-loading-progress {
        width: 100%; height: 6px; background: #f0f0f0; border-radius: 3px; overflow: hidden;
      }
      .ai-model-loading-progress-bar {
        height: 100%; background: linear-gradient(90deg, #e54346, #ff6b6b);
        transition: width 0.3s ease;
      }
    `;
    document.head.appendChild(style);
  }
  document.body.appendChild(this.el);

  this.timer = setInterval(function () {
    const elapsed = Date.now() - self.startTime;
    const phase = self.phases.find(p => elapsed < p.until) || self.phases[self.phases.length - 1];
    const textEl = self.el.querySelector('.ai-model-loading-text');
    const subEl = self.el.querySelector('.ai-model-loading-subtext');
    const barEl = self.el.querySelector('.ai-model-loading-progress-bar');
    if (textEl) textEl.textContent = phase.text;
    if (subEl) subEl.textContent = phase.sub;
    if (barEl) {
      const pct = Math.min(95, Math.floor(elapsed / 660000 * 100));
      barEl.style.width = pct + '%';
    }
  }, 500);
};

AiModelLoading.prototype.hide = function () {
  if (this.timer) {
    clearInterval(this.timer);
    this.timer = null;
  }
  if (this.el && this.el.parentNode) {
    this.el.parentNode.removeChild(this.el);
  }
  this.el = null;
};
