"""
Nacos 服务发现

通过 Nacos Open API 查询服务实例列表，供 Python 侧调用 Java 微服务时做负载均衡。
"""
import logging
import random

import httpx

logger = logging.getLogger(__name__)


class NacosDiscovery:
    """Nacos 服务发现客户端（查询实例列表 + 简单随机负载均衡）"""

    def __init__(self, server_addr: str = "192.168.59.128:8848", username: str = "", password: str = ""):
        self.server_addr = server_addr
        self.username = username
        self.password = password
        self._access_token: str | None = None
        # trust_env=False: 忽略 HTTP_PROXY/HTTPS_PROXY 环境变量，
        # Nacos 是内网服务，不走代理
        self._client = httpx.AsyncClient(timeout=5.0, trust_env=False)

    async def _login(self):
        """若配置了鉴权，登录获取 accessToken"""
        if not self.username or not self.password:
            return
        try:
            resp = await self._client.post(
                f"http://{self.server_addr}/nacos/v1/auth/login",
                params={"username": self.username, "password": self.password},
            )
            if resp.status_code == 200:
                self._access_token = resp.json().get("accessToken")
        except Exception as e:
            logger.warning("Nacos 登录异常: %s", e)

    def _auth_params(self) -> dict:
        if self._access_token:
            return {"accessToken": self._access_token}
        return {}

    async def get_instances(self, service_name: str, healthy_only: bool = True) -> list[dict]:
        """查询服务的健康实例列表

        Args:
            service_name: 服务名（如 user-service, item-service）
            healthyOnly: 仅返回健康实例
        Returns:
            实例列表 [{ip, port, weight, ...}, ...]
        """
        if not self._access_token and self.username:
            await self._login()

        try:
            resp = await self._client.get(
                f"http://{self.server_addr}/nacos/v1/ns/instance/list",
                params={
                    "serviceName": service_name,
                    "healthyOnly": str(healthy_only).lower(),
                    **self._auth_params(),
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                hosts = data.get("hosts", [])
                return hosts
            logger.warning("Nacos 查询实例失败: service=%s, status=%s", service_name, resp.status_code)
            return []
        except Exception as e:
            logger.warning("Nacos 查询实例异常: service=%s, error=%s", service_name, e)
            return []

    async def get_service_url(self, service_name: str) -> str | None:
        """获取一个服务实例的完整 URL（随机负载均衡）

        Returns:
            如 "http://192.168.59.1:8081"，无可用实例返回 None
        """
        instances = await self.get_instances(service_name)
        if not instances:
            logger.warning("Nacos 无可用实例: service=%s", service_name)
            return None

        # 简单随机负载均衡（后续可扩展为加权轮询）
        instance = random.choice(instances)
        ip = instance.get("ip")
        port = instance.get("port")
        if ip and port:
            url = f"http://{ip}:{port}"
            logger.debug("Nacos 服务发现: %s -> %s", service_name, url)
            return url
        return None

    async def close(self):
        await self._client.aclose()
