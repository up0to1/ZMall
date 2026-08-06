"""
Nacos 服务注册/心跳管理

通过 Nacos Open API 注册 Python 服务，使 Gateway 能通过 lb://ai-models 发现。
启动时注册 → 后台协程每 5s 发送心跳 → 关闭时注销。
"""
import asyncio
import json
import socket
import logging

import httpx

logger = logging.getLogger(__name__)


class NacosRegistrar:
    """Nacos 服务注册器（轻量级 HTTP 实现，无需额外 SDK）"""

    def __init__(
        self,
        server_addr: str = "192.168.59.128:8848",
        service_name: str = "ai-models",
        port: int = 9000,
        group_name: str = "DEFAULT_GROUP",
        cluster_name: str = "DEFAULT",
        username: str = "",
        password: str = "",
    ):
        self.base_url = f"http://{server_addr}/nacos/v1/ns/instance"
        self.server_addr = server_addr
        self.service_name = service_name
        self.port = port
        self.group_name = group_name
        self.cluster_name = cluster_name
        self.username = username
        self.password = password
        self._access_token: str | None = None
        self.ip = self._get_local_ip()
        self._heartbeat_task: asyncio.Task | None = None
        # trust_env=False: 忽略 HTTP_PROXY/HTTPS_PROXY 环境变量，
        # Nacos 是内网服务，不走代理（避免被系统代理环境变量污染导致连接超时）
        self._client = httpx.AsyncClient(timeout=5.0, trust_env=False)

    @staticmethod
    def _get_local_ip() -> str:
        """获取本机局域网 IP（用于 Nacos 注册）"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def _login(self):
        """若配置了 username/password，登录获取 accessToken（Nacos 2.2+ 鉴权必需）"""
        if not self.username or not self.password:
            return
        try:
            resp = await self._client.post(
                f"http://{self.server_addr}/nacos/v1/auth/login",
                params={"username": self.username, "password": self.password},
            )
            if resp.status_code == 200:
                self._access_token = resp.json().get("accessToken")
                logger.info("Nacos 登录成功，已获取 accessToken")
            else:
                logger.warning("Nacos 登录失败: status=%s, body=%s", resp.status_code, resp.text)
        except Exception as e:
            logger.warning("Nacos 登录异常: %s", e)

    def _auth_params(self) -> dict:
        """返回鉴权参数（仅在已登录时附加）"""
        if self._access_token:
            return {"accessToken": self._access_token}
        return {}

    async def register(self) -> bool:
        """注册服务实例到 Nacos（ephemeral=true，需要客户端心跳保活）"""
        # 若配置了鉴权，先登录获取 token
        await self._login()

        params = {
            "serviceName": self.service_name,
            "ip": self.ip,
            "port": self.port,
            "weight": 1.0,
            "enabled": "true",
            "healthy": "true",
            "ephemeral": "true",
            "groupName": self.group_name,
            "clusterName": self.cluster_name,
            "metadata": json.dumps({"preserved.register.source": "PYTHON"}),
            **self._auth_params(),
        }
        try:
            resp = await self._client.post(self.base_url, params=params)
            if resp.status_code == 200 and resp.text.strip() == "ok":
                logger.info(
                    "Nacos 注册成功: service=%s, ip=%s, port=%s",
                    self.service_name, self.ip, self.port,
                )
                # 启动心跳协程
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return True
            logger.error("Nacos 注册失败: status=%s, body=%s", resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.error("Nacos 注册异常: %s", e)
            return False

    async def _heartbeat_loop(self):
        """每 5 秒发送一次心跳（ephemeral 实例需要客户端保活）"""
        beat_data = json.dumps({
            "ip": self.ip,
            "port": self.port,
            "serviceName": self.service_name,
            "cluster": self.cluster_name,
            "weight": 1.0,
        })
        while True:
            try:
                await asyncio.sleep(5)
                resp = await self._client.put(
                    f"http://{self.server_addr}/nacos/v1/ns/instance/beat",
                    params={
                        "serviceName": self.service_name,
                        "ip": self.ip,
                        "port": self.port,
                        "groupName": self.group_name,
                        "beat": beat_data,
                        **self._auth_params(),
                    },
                )
                if resp.status_code != 200:
                    logger.warning("Nacos 心跳异常: status=%s, body=%s", resp.status_code, resp.text)
                    # token 过期时重新登录
                    if resp.status_code == 403 and self.username:
                        await self._login()
            except asyncio.CancelledError:
                logger.info("Nacos 心跳任务已取消")
                break
            except Exception as e:
                logger.warning("Nacos 心跳发送失败: %s", e)

    async def deregister(self):
        """从 Nacos 注销服务实例"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        try:
            resp = await self._client.delete(
                self.base_url,
                params={
                    "serviceName": self.service_name,
                    "ip": self.ip,
                    "port": self.port,
                    "groupName": self.group_name,
                    "clusterName": self.cluster_name,
                    "ephemeral": "true",
                    **self._auth_params(),
                },
            )
            if resp.status_code == 200:
                logger.info("Nacos 注销成功: service=%s", self.service_name)
            else:
                logger.warning("Nacos 注销失败: status=%s", resp.status_code)
        except Exception as e:
            logger.error("Nacos 注销异常: %s", e)
        finally:
            await self._client.aclose()
