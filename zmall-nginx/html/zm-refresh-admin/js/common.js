// ZMall Admin - 公共工具
const ZM = {
    // axios实例，带token拦截
    http: null,
    // Cookie操作
    setCookie(name, value, hours) {
        let expires = '';
        if (hours) {
            const d = new Date();
            d.setTime(d.getTime() + hours * 3600000);
            expires = ';expires=' + d.toUTCString();
        }
        document.cookie = name + '=' + encodeURIComponent(value) + ';path=/' + expires;
    },
    getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : null;
    },
    deleteCookie(name) {
        document.cookie = name + '=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT';
    },
    // 保存登录信息（同时存localStorage和cookie）
    saveLogin(token, user) {
        localStorage.setItem('zm-admin-token', token);
        localStorage.setItem('zm-admin-user', JSON.stringify(user));
        this.setCookie('zm_admin_token', token, 24);
    },
    // 清除登录信息
    clearLogin() {
        localStorage.removeItem('zm-admin-token');
        localStorage.removeItem('zm-admin-user');
        this.deleteCookie('zm_admin_token');
    },
    // 初始化axios
    initHttp() {
        const instance = axios.create({
            baseURL: '/api',
            timeout: 15000
        });
        instance.interceptors.request.use(config => {
            const token = localStorage.getItem('zm-admin-token');
            if (token) {
                config.headers['authorization'] = 'Bearer ' + token;
            }
            return config;
        });
        instance.interceptors.response.use(
            res => res.data,
            err => {
                if (err.response && (err.response.status === 401 || err.response.status === 403)) {
                    // token无效/过期或无权限，清除登录信息并跳转
                    const msg = err.response.status === 403 ? '无权限访问，请重新登录' : '登录已过期，请重新登录';
                    ZM.clearLogin();
                    alert(msg);
                    window.location.href = '/login.html';
                    return new Promise(() => {}); // 阻止后续catch执行
                }
                return Promise.reject(err);
            }
        );
        this.http = instance;
    },
    // 检查登录（Nginx层检查cookie + JS层检查localStorage + Gateway层校验API请求）
    checkAuth() {
        const token = localStorage.getItem('zm-admin-token');
        const user = this.getUser();
        if (!token || !user.userId || user.role !== 2) {
            this.clearLogin();
            window.location.href = '/login.html';
            return false;
        }
        return true;
    },
    // 获取用户信息
    getUser() {
        try {
            return JSON.parse(localStorage.getItem('zm-admin-user') || '{}');
        } catch (e) {
            return {};
        }
    },
    // 退出登录
    logout() {
        this.clearLogin();
        window.location.href = '/login.html';
    },
    // 格式化日期
    formatDate(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr);
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0') + ':' +
            String(d.getSeconds()).padStart(2, '0');
    },
    // 格式化金额（后端存储为分，前端显示为元）
    formatMoney(val) {
        if (val === null || val === undefined) return '0.00';
        return (Number(val) / 100).toFixed(2);
    }
};

ZM.initHttp();
