#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JumpServer客户端模块 - 负责与JumpServer API交互

提供以下功能：
- 与JumpServer API的认证和通信
- 资产管理（创建、更新、删除、查询）
- 节点管理（创建、更新、删除、查询）
- 自动重试和缓存支持
"""

import json
import time
import logging
import urllib.parse
import requests
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union, Set

from httpsig.requests_auth import HTTPSignatureAuth

from jms_sync.utils.exceptions import JumpServerError, JumpServerAPIError, JumpServerAuthError
from jms_sync.utils.decorators import retry, log_execution_time
from jms_sync.utils.logger import get_logger, StructuredLogger
from jms_sync.utils.cache import MemoryCache, cached
from jms_sync.jumpserver.models import AssetInfo, NodeInfo, SyncResult


class JumpServerClient:
    """
    JumpServer客户端类，提供与JumpServer API交互的功能。
    
    主要功能：
    - 资产管理（创建、更新、删除、查询）
    - 节点管理（创建、更新、删除、查询）
    - 自动重试和缓存支持
    
    使用示例:
    ```python
    client = JumpServerClient(
        base_url="https://jumpserver.example.com",
        access_key_id="your-access-key-id",
        access_key_secret="your-access-key-secret"
    )
    
    # 获取所有资产
    assets = client.get_all_assets()
    
    # 创建资产
    asset = AssetInfo(
        name="test-server",
        ip="192.168.1.1",
        platform="Linux",
        protocol="ssh",
        port=22,
        node_id="node-id"
    )
    created_asset = client.create_asset(asset)
    ```
    """
    
    def __init__(
        self, 
        base_url: str, 
        access_key_id: str, 
        access_key_secret: str, 
        org_id: str = "00000000-0000-0000-0000-000000000002", 
        config: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 300
    ):
        """
        初始化JumpServer客户端
        
        Args:
            base_url: JumpServer API基础URL
            access_key_id: 访问密钥ID
            access_key_secret: 访问密钥密钥
            org_id: 组织ID，默认为"00000000-0000-0000-0000-000000000002"
            config: 配置字典，包含协议端口、账号模板等配置
            cache_ttl: 缓存有效期（秒）
        """
        # 确保URL包含协议
        if base_url and not (base_url.startswith('http://') or base_url.startswith('https://')):
            base_url = f"https://{base_url}"
            
        # 移除URL末尾的斜杠
        if base_url and base_url.endswith('/'):
            base_url = base_url[:-1]
            
        self.base_url = base_url
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.org_id = org_id
        self.config = config or {}  # 保存配置信息，包括账号模板等
        self.cache_ttl = cache_ttl  # 保存缓存TTL为实例属性
        self.logger = get_logger(__name__)
        self.structured_logger = StructuredLogger(__name__)
        
        # 设置缓存
        self.cache = MemoryCache(prefix="jms", default_ttl=cache_ttl)
        
        # 初始化HTTP签名认证
        self.auth = self._get_auth()
        
        # 初始化会话
        self.session = requests.Session()
        
        # 设置默认请求头
        self.session.headers.update({
            'Content-Type': 'application/json',
            'X-JMS-ORG': org_id,
            'Accept': 'application/json'
        })
        
        # 测试连接
        self.test_connectivity()
        
    def _get_auth(self) -> HTTPSignatureAuth:
        """
        获取HTTP签名认证
        
        Returns:
            HTTPSignatureAuth: HTTP签名认证对象
        """
        signature_headers = ['(request-target)', 'accept', 'date']
        auth = HTTPSignatureAuth(
            key_id=self.access_key_id,
            secret=self.access_key_secret,
            algorithm='hmac-sha256',
            headers=signature_headers
        )
        return auth
    
    @retry(max_retries=3, retry_interval=2, exceptions=(requests.RequestException,))
    def _api_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None, 
        data: Optional[Dict[str, Any]] = None, 
        json_data: Optional[Dict[str, Any]] = None,
        timeout: int = 30
    ) -> Any:
        """
        发送API请求
        
        Args:
            method: 请求方法，如"GET"、"POST"、"PUT"、"DELETE"
            endpoint: API端点，如"/api/v1/assets/assets/"
            params: 查询参数
            data: 表单数据
            json_data: JSON数据
            timeout: 请求超时时间（秒）
            
        Returns:
            Any: 响应数据
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        # 构建URL
        url = f"{self.base_url}{endpoint}"
        
        # 设置请求头
        headers = {
            'Date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        }
        
        # 记录请求信息
        self.structured_logger.debug(
            f"发送请求: {method} {url}",
            params=params,
            json_data=json_data if json_data else None
        )
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=headers,
                auth=self.auth,
                timeout=timeout
            )
            
            # 记录响应状态
            self.structured_logger.debug(
                f"接收响应: {method} {url}",
                status_code=response.status_code,
                reason=response.reason
            )
            
            # 解析响应
            if response.status_code >= 400:
                # 记录失败响应内容
                error_data = {}
                try:
                    error_data = response.json()
                except ValueError:
                    error_data = {"detail": response.text}
                    
                self.structured_logger.error(
                    f"API请求失败: {response.status_code} {response.reason}",
                    error_data=error_data,
                    url=url,
                    method=method
                )
                
                # 根据状态码抛出特定异常
                if response.status_code == 401:
                    raise JumpServerAuthError(f"认证失败: {response.text}")
                else:
                    raise JumpServerAPIError(
                        message=f"API请求失败: {response.status_code} {response.reason}",
                        status_code=response.status_code,
                        response=response.text
                    )
            
            # 尝试解析JSON响应
            if response.headers.get('Content-Type', '').startswith('application/json'):
                return response.json()
            else:
                return response.text
        except requests.RequestException as e:
            self.structured_logger.error(f"请求异常: {str(e)}", url=url, method=method)
            raise
    
    def test_connectivity(self) -> bool:
        """
        测试与JumpServer的连接
        
        Returns:
            bool: 连接是否成功
            
        Raises:
            JumpServerError: 连接失败时抛出异常
        """
        try:
            self.logger.info(f"测试与JumpServer的连接: {self.base_url}")
            # 调用一个轻量级接口来测试连接
            response = self._api_request("GET", "/api/v1/terminal/status/")
            self.logger.info("JumpServer连接测试成功")
            return True
        except JumpServerAuthError as e:
            self.logger.error(f"JumpServer认证失败: {str(e)}")
            raise JumpServerError(f"JumpServer认证失败: {str(e)}")
        except JumpServerAPIError as e:
            self.logger.error(f"JumpServer API错误: {str(e)}")
            raise JumpServerError(f"JumpServer API错误: {str(e)}")
        except Exception as e:
            self.logger.error(f"连接JumpServer失败: {str(e)}")
            raise JumpServerError(f"连接JumpServer失败: {str(e)}")
    
    # 为了向后兼容，添加test_connection作为test_connectivity的别名
    test_connection = test_connectivity
    
    def get_assets(self, params: Optional[Dict[str, Any]] = None, force_refresh: bool = False) -> List[AssetInfo]:
        """
        获取资产列表
        
        Args:
            params: 查询参数，如分页、筛选等
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[AssetInfo]: 资产列表
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info("获取资产列表")
        
        # 默认参数
        if params is None:
            params = {}
            
        # 缓存键
        cache_key = f"get_assets:{json.dumps(params, sort_keys=True)}"
        
        # 如果未强制刷新且缓存中有数据，则返回缓存数据
        if not force_refresh and self.cache.has(cache_key):
            self.logger.debug(f"从缓存获取资产列表: {cache_key}")
            return self.cache.get(cache_key)
        
        # 设置每页数量，最大为100
        if 'limit' not in params:
            params['limit'] = 100
            
        assets = []
        total_page = 1
        current_page = 1
        
        while current_page <= total_page:
            params['page'] = current_page
            
            try:
                response = self._api_request("GET", "/api/v1/assets/assets/", params=params)
                
                if isinstance(response, dict) and 'results' in response:
                    # 获取分页信息
                    count = response.get('count', 0)
                    limit = params.get('limit', 100)
                    if count and limit:
                        total_page = (count + limit - 1) // limit
                    
                    # 获取资产列表
                    for item in response['results']:
                        assets.append(AssetInfo.from_dict(item))
                    
                    current_page += 1
                else:
                    self.logger.warning(f"获取资产列表返回意外格式: {response}")
                    break
            except JumpServerAPIError as e:
                self.logger.error(f"获取资产列表失败: {str(e)}")
                raise
        
        self.logger.info(f"成功获取{len(assets)}个资产")
        
        # 存入缓存
        self.cache.set(cache_key, assets, ttl=self.cache_ttl)
        
        return assets
    
    def get_all_assets(self) -> List[AssetInfo]:
        """
        获取所有资产，使用缓存
        
        Returns:
            List[AssetInfo]: 所有资产列表
        """
        self.logger.info("获取所有资产")
        return self.get_assets()
    
    def get_asset_by_ip(self, ip: str) -> Optional[AssetInfo]:
        """
        通过IP获取资产
        
        Args:
            ip: 资产IP
            
        Returns:
            Optional[AssetInfo]: 资产信息，如果不存在则返回None
        """
        self.logger.info(f"通过IP获取资产: {ip}")
        
        # 首先尝试从缓存获取所有资产
        assets = self.get_all_assets()
        
        # 查找指定IP的资产
        for asset in assets:
            if asset.ip == ip:
                return asset
                
        # 如果缓存中没有找到，直接查询API
        params = {'ip': ip}
        try:
            results = self.get_assets(params)
            if results:
                return results[0]
        except JumpServerAPIError:
            pass
            
        return None
    
    def get_asset_by_name(self, name: str) -> Optional[AssetInfo]:
        """
        通过名称获取资产
        
        Args:
            name: 资产名称
            
        Returns:
            Optional[AssetInfo]: 资产信息，如果不存在则返回None
        """
        self.logger.info(f"通过名称获取资产: {name}")
        
        # 首先尝试从缓存获取所有资产
        assets = self.get_all_assets()
        
        # 查找指定名称的资产
        for asset in assets:
            if asset.name == name:
                return asset
                
        # 如果缓存中没有找到，直接查询API
        params = {'name': name}
        try:
            results = self.get_assets(params)
            if results:
                return results[0]
        except JumpServerAPIError:
            pass
            
        return None
    
    def prepare_asset_data(self, ip: str, name: str, node_id: str, platform: str) -> Dict[str, Any]:
        """
        准备资产数据
        
        Args:
            ip: 资产IP
            name: 资产名称
            node_id: 节点ID
            platform: 平台类型，如"Linux"、"Windows"
            
        Returns:
            Dict[str, Any]: 资产数据
        """
        # 平台类型映射
        platform_map = {
            "linux": 1,
            "windows": 5  # Windows平台ID为5
        }
        
        # 获取平台类型ID
        platform_id = platform_map.get(platform.lower(), 1)  # 默认为Linux
        
        # 获取协议端口配置
        ssh_port = 22
        rdp_port = 3389
        
        # 如果配置中有协议端口配置，则使用配置中的端口
        if hasattr(self, 'config') and self.config and 'protocols' in self.config:
            ssh_port = self.config['protocols'].get('ssh_port', 22)
            rdp_port = self.config['protocols'].get('rdp_port', 3389)
        
        # 设置协议列表
        protocols = []
        
        # 根据平台类型设置协议
        if platform.lower() == "linux":
            # Linux主机使用SSH协议
            protocols.append({
                "name": "ssh",
                "port": ssh_port
            })
        elif platform.lower() == "windows":
            # Windows主机使用RDP协议
            protocols.append({
                "name": "rdp",
                "port": rdp_port
            })
        
        # 获取domain_id
        domain_id = None

        # 首先从config获取
        if hasattr(self, 'config') and self.config and 'domain_id' in self.config:
            domain_id = self.config.get('domain_id')
            if domain_id:
                self.logger.debug(f"从config中获取domain_id: {domain_id}")
            
        # 如果config中没有，尝试从current_cloud_config获取
        if not domain_id and hasattr(self, 'current_cloud_config') and self.current_cloud_config and 'domain_id' in self.current_cloud_config:
            domain_id = self.current_cloud_config.get('domain_id', "")
            if domain_id:
                self.logger.debug(f"从current_cloud_config中获取domain_id: {domain_id}")
            
        # 确保domain_id不为空字符串
        if domain_id == "":
            domain_id = None
            
        # 构建资产数据 - 使用JumpServer API要求的格式
        data = {
            "name": name,
            "address": ip,
            "platform": {"pk": platform_id},  # 使用对象格式
            "nodes": [{"pk": node_id}],  # 使用对象格式
            "protocols": protocols,
            "is_active": True,
            "comment": f"由JMS-Sync同步于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        # 如果有网域ID，则添加到数据中
        if domain_id:
            data["domain"] = domain_id
            self.logger.debug(f"添加domain_id到资产数据: {domain_id}")
            
        # 添加调试日志
        self.logger.debug(f"准备资产数据: {data}")
            
        return data
    
    def create_asset(self, asset_info: Union[AssetInfo, Dict[str, Any]]) -> Union[AssetInfo, Dict[str, Any]]:
        """
        创建资产
        
        Args:
            asset_info: 资产信息或已准备好的资产数据字典
            
        Returns:
            Union[AssetInfo, Dict[str, Any]]: 创建后的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        if isinstance(asset_info, AssetInfo):
            # 如果是AssetInfo对象，直接访问其属性
            ip = asset_info.ip
            name = asset_info.name
            node_id = asset_info.node_id
            platform_type = asset_info.platform
            self.logger.info(f"使用AssetInfo创建资产: {name} ({ip}), 平台: {platform_type}")
            
            # 准备新格式的资产数据
            data = self.prepare_asset_data(ip, name, node_id, platform_type)
            
            # 添加自定义属性
            if hasattr(asset_info, 'attrs') and asset_info.attrs:
                data["attrs"] = asset_info.attrs
                
            # 添加账号信息
            if hasattr(asset_info, 'accounts') and asset_info.accounts:
                data["accounts"] = asset_info.accounts
                self.logger.debug(f"添加账号信息到资产: {asset_info.accounts}")
        else:
            # 如果是已准备好的数据字典，直接使用
            data = asset_info
            # 使用安全的方式获取名称和地址，避免KeyError
            asset_name = data.get('name', '') if isinstance(data, dict) else getattr(data, 'name', '')
            asset_address = data.get('address', '') if isinstance(data, dict) else getattr(data, 'ip', '')
            self.logger.info(f"使用数据字典创建资产: {asset_name} ({asset_address})")
        
        try:
            # 根据平台类型确定接口URL
            platform_id = 1  # 默认为Linux
            if isinstance(data, dict):
                platform = data.get("platform", {})
                # 确保platform是一个字典
                if not isinstance(platform, dict):
                    # 如果platform是字符串，根据值设置平台ID
                    if isinstance(platform, str) and platform.lower() == "windows":
                        platform = {"pk": 5}  # Windows平台ID为5
                    else:
                        platform = {"pk": 1}  # 默认为Linux
                    data["platform"] = platform  # 更新数据中的platform字段
                    self.logger.debug(f"转换平台信息为字典格式: {platform}")
                
                platform_id = platform.get("pk", 1)
                self.logger.debug(f"使用平台ID: {platform_id}")
            
            # 使用hosts端点而不是assets端点
            endpoint = f"/api/v1/assets/hosts/?platform={platform_id}"
            
            # 发送请求
            self.logger.debug(f"创建资产数据: {data}")
            result = self._api_request("POST", endpoint, json_data=data)
            
            # 清除缓存
            self.cache.delete("get_assets")
            self.cache.delete("get_all_assets")
            
            # 安全地获取资产名称用于日志
            if isinstance(data, dict):
                asset_name = data.get('name', '')
            else:
                asset_name = getattr(data, 'name', '')
                
            self.logger.info(f"资产创建成功: {asset_name}")
            return result
        except Exception as e:
            self.logger.error(f"创建资产失败: {str(e)}")
            
            # 尝试直接发送请求，获取更详细的错误信息
            try:
                # 确保endpoint已定义
                if not locals().get('endpoint'):
                    platform_id = 1
                    endpoint = f"/api/v1/assets/hosts/?platform={platform_id}"
                    
                url = f"{self.base_url}{endpoint}"
                headers = {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-JMS-ORG': self.org_id,
                    'Date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
                }
                
                # 确保data是字典格式
                if not isinstance(data, dict):
                    # 如果data是AssetInfo对象，转换为字典
                    if hasattr(data, 'to_dict'):
                        data = data.to_dict()
                    else:
                        # 创建一个基本的字典
                        platform_id = 1
                        if hasattr(data, 'platform') and data.platform.lower() == "windows":
                            platform_id = 5
                            
                        data = {
                            "name": getattr(data, 'name', ''),
                            "address": getattr(data, 'ip', ''),
                            "platform": {"pk": platform_id},
                            "nodes": [{"pk": getattr(data, 'node_id', '')}]
                        }
                
                # 确保data中的platform是字典格式
                if "platform" in data and not isinstance(data["platform"], dict):
                    if isinstance(data["platform"], str) and data["platform"].lower() == "windows":
                        data["platform"] = {"pk": 5}
                    else:
                        data["platform"] = {"pk": 1}
                
                response = requests.post(
                    url=url,
                    headers=headers,
                    json=data,
                    auth=self._get_auth()
                )
                
                if response.status_code >= 400:
                    self.logger.error(f"创建资产详细错误: 状态码={response.status_code}, 响应={response.text}")
            except Exception as e2:
                self.logger.error(f"获取详细错误信息失败: {str(e2)}")
            
            # 重新抛出原始异常，但包装为JumpServerAPIError以提供更多上下文
            if not isinstance(e, JumpServerAPIError):
                raise JumpServerAPIError(
                    message=f"创建资产失败: {str(e)}",
                    status_code=500,
                    response="未知错误"
                ) from e
            else:
                raise
    
    def update_asset(self, asset_id: str, asset_info: AssetInfo) -> AssetInfo:
        """
        更新资产
        
        Args:
            asset_id: 资产ID
            asset_info: 更新的资产信息
            
        Returns:
            AssetInfo: 更新后的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"更新资产: ID={asset_id}, 名称={asset_info.name}, IP={asset_info.ip}, 平台={asset_info.platform}")
        
        try:
            # 设置ID
            asset_info.id = asset_id
            
            # 转换为字典用于请求
            if hasattr(asset_info, 'to_dict'):
                asset_data = asset_info.to_dict()
            else:
                # 如果没有to_dict方法，手动创建字典
                asset_data = {
                    "id": asset_id,
                    "name": getattr(asset_info, 'name', ''),
                    "address": getattr(asset_info, 'ip', ''),
                    "is_active": True
                }
                
                # 处理platform字段
                platform = getattr(asset_info, 'platform', None)
                if platform:
                    if isinstance(platform, dict):
                        asset_data["platform"] = platform
                    else:
                        # 根据平台类型设置平台ID
                        if platform.lower() == "windows":
                            asset_data["platform"] = {"pk": 5}  # Windows平台ID为5
                        else:
                            asset_data["platform"] = {"pk": 1}  # 默认为Linux
                else:
                    asset_data["platform"] = {"pk": 1}
                    
                # 处理nodes字段
                node_id = getattr(asset_info, 'node_id', None)
                if node_id:
                    asset_data["nodes"] = [{"pk": node_id}]
            
            # 确保platform是字典格式
            if "platform" in asset_data and not isinstance(asset_data["platform"], dict):
                if asset_data["platform"].lower() == "windows":
                    asset_data["platform"] = {"pk": 5}  # Windows平台ID为5
                else:
                    asset_data["platform"] = {"pk": 1}  # Linux平台ID为1
                
            # 确保nodes是正确的格式
            if "nodes" in asset_data and isinstance(asset_data["nodes"], list):
                for i, node in enumerate(asset_data["nodes"]):
                    if not isinstance(node, dict):
                        asset_data["nodes"][i] = {"pk": node}
            
            # 使用新的API端点
            platform_id = asset_data.get("platform", {}).get("pk", 1)
            endpoint = f"/api/v1/assets/hosts/{asset_id}/?platform={platform_id}"
            
            # 发送更新请求
            self.logger.debug(f"更新资产数据: {asset_data}")
            response = self._api_request("PUT", endpoint, json_data=asset_data)
            
            # 从响应创建资产对象
            if isinstance(response, dict):
                updated_asset = AssetInfo.from_dict(response)
            else:
                # 如果响应不是字典，直接返回原始资产信息
                updated_asset = asset_info
            
            # 清除缓存
            self.cache.delete("get_assets")
            self.cache.delete("get_all_assets")
            
            self.logger.info(f"资产更新成功: {updated_asset.name} ({updated_asset.ip})")
            return updated_asset
        except Exception as e:
            self.logger.error(f"更新资产失败: {str(e)}")
            
            # 尝试获取更详细的错误信息
            try:
                if not locals().get('endpoint'):
                    platform_id = 1
                    if hasattr(asset_info, 'platform') and asset_info.platform.lower() == "windows":
                        platform_id = 5
                    endpoint = f"/api/v1/assets/hosts/{asset_id}/?platform={platform_id}"
                    
                url = f"{self.base_url}{endpoint}"
                headers = {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-JMS-ORG': self.org_id,
                    'Date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
                }
                
                response = requests.put(
                    url=url,
                    headers=headers,
                    json=asset_data,
                    auth=self._get_auth()
                )
                
                if response.status_code >= 400:
                    self.logger.error(f"更新资产详细错误: 状态码={response.status_code}, 响应={response.text}")
            except Exception as e2:
                self.logger.error(f"获取详细错误信息失败: {str(e2)}")
            
            # 重新抛出异常
            if not isinstance(e, JumpServerAPIError):
                raise JumpServerAPIError(
                    message=f"更新资产失败: {str(e)}",
                    status_code=500,
                    response="未知错误"
                ) from e
            else:
                raise
    
    def delete_asset(self, asset_id: str) -> None:
        """
        删除资产
        
        Args:
            asset_id: 资产ID
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"删除资产: ID={asset_id}")
        
        try:
            # 发送删除请求
            self._api_request("DELETE", f"/api/v1/assets/assets/{asset_id}/")
            
            # 清除缓存
            self.cache.delete("get_assets")
            self.cache.delete("get_all_assets")
            
            self.logger.info(f"资产删除成功: ID={asset_id}")
        except JumpServerAPIError as e:
            self.logger.error(f"删除资产失败: {str(e)}")
            raise
    
    @retry(max_retries=3, retry_interval=1, backoff_factor=2, exceptions=(JumpServerAPIError,))
    def get_nodes(self, params=None, force_refresh=False) -> List[NodeInfo]:
        """
        获取节点列表
        
        Args:
            params: 查询参数，如分页、筛选等
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[NodeInfo]: 节点列表
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info("获取节点列表")
        
        # 如果强制刷新，清除缓存
        if force_refresh:
            self.cache.delete("get_nodes")
        
        # 默认参数
        if params is None:
            params = {}
        
        # 设置每页数量，最大为100
        if 'limit' not in params:
            params['limit'] = 100
            
        nodes = []
        total_page = 1
        current_page = 1
        
        # 尝试不同的API端点
        endpoints = [
            "/api/v1/assets/nodes/",  # 标准端点
            "/api/v1/assets/nodes",   # 不带尾部斜杠
            "/api/v1/nodes/",         # 旧版端点
            "/api/v1/nodes"           # 不带尾部斜杠的旧版端点
        ]
        
        success = False
        error_messages = []
        
        # 尝试不同的API端点
        for endpoint in endpoints:
            if success:
                break
                
            try:
                while current_page <= total_page:
                    params['page'] = current_page
                    
                    try:
                        response = self._api_request("GET", endpoint, params=params)
                        success = True
                        
                        if isinstance(response, dict) and 'results' in response:
                            # 获取分页信息
                            count = response.get('count', 0)
                            limit = params.get('limit', 100)
                            if count and limit:
                                total_page = (count + limit - 1) // limit
                            
                            # 获取节点列表
                            for item in response['results']:
                                nodes.append(NodeInfo.from_dict(item))
                            
                            current_page += 1
                        elif isinstance(response, list):
                            # 如果响应是列表，直接处理
                            for item in response:
                                nodes.append(NodeInfo.from_dict(item))
                            break
                        else:
                            self.logger.warning(f"获取节点列表返回意外格式: {response}")
                            break
                    except JumpServerAPIError as e:
                        error_messages.append(f"端点 {endpoint} 失败: {str(e)}")
                        # 不要在这里重新抛出异常，继续尝试下一个端点
                        break  # 跳出内部循环
            except Exception as e:
                self.logger.warning(f"使用端点 {endpoint} 获取节点失败: {str(e)}")
                # 继续尝试下一个端点
                current_page = 1
                total_page = 1
        
        if not success and error_messages:
            error_msg = "; ".join(error_messages)
            self.logger.error(f"所有端点获取节点失败: {error_msg}")
            # 尝试一种更简单的方法：直接获取根节点
            try:
                self.logger.info("尝试直接获取根节点")
                response = self._api_request("GET", "/api/v1/assets/nodes/children-nodes/", params={"id": ""})
                if isinstance(response, list):
                    for item in response:
                        nodes.append(NodeInfo.from_dict(item))
                    success = True
            except Exception as e:
                self.logger.error(f"获取根节点失败: {str(e)}")
        
        self.logger.info(f"成功获取{len(nodes)}个节点")
        return nodes
    
    def get_node_by_key(self, key: str) -> Optional[NodeInfo]:
        """
        通过Key获取节点
        
        Args:
            key: 节点Key
            
        Returns:
            Optional[NodeInfo]: 节点信息，如果不存在则返回None
        """
        self.logger.info(f"通过Key获取节点: {key}")
        
        # 首先尝试从缓存获取所有节点
        nodes = self.get_nodes()
        
        # 查找指定Key的节点
        for node in nodes:
            if node.key == key:
                return node
                
        # 如果缓存中没有找到，直接查询API
        params = {'key': key}
        try:
            results = self.get_nodes(params=params, force_refresh=True)
            if results:
                return results[0]
        except JumpServerAPIError:
            pass
            
        return None
    
    def get_node_by_full_path(self, path: str) -> Optional[NodeInfo]:
        """
        通过完整路径获取节点
        
        Args:
            path: 节点完整路径，例如 "/DEFAULT/aliyun/aliyun-prod"
            
        Returns:
            Optional[NodeInfo]: 节点信息，如果不存在则返回None
        """
        self.logger.info(f"通过完整路径获取节点: {path}")
        
        # 获取所有节点
        nodes = self.get_nodes()
        
        # 查找指定路径的节点
        for node in nodes:
            if node.full_value == path:
                return node
                
        return None
    
    def create_node(self, node_info: NodeInfo) -> NodeInfo:
        """
        创建节点
        
        Args:
            node_info: 节点信息
            
        Returns:
            NodeInfo: 创建后的节点信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"创建节点: {node_info.value}")
        
        try:
            # 准备节点数据
            node_data = {
                "value": node_info.value
            }
            
            # 如果有key，添加到请求数据
            if node_info.key:
                node_data["key"] = node_info.key
                
            # 获取父节点ID
            parent_id = node_info.parent
            
            # 使用新的API路径创建子节点
            if parent_id:
                # 使用父节点ID创建子节点
                self.logger.info(f"使用父节点ID创建子节点: parent_id={parent_id}")
                response = self._api_request("POST", f"/api/v1/assets/nodes/{parent_id}/children/", json_data=node_data)
            else:
                # 如果没有父节点ID，使用原来的API创建根节点
                self.logger.info("创建根节点")
                response = self._api_request("POST", "/api/v1/assets/nodes/", json_data=node_data)
            
            # 从响应创建节点对象
            created_node = NodeInfo.from_dict(response)
            
            # 清除缓存
            self.cache.delete("get_nodes")
            
            self.logger.info(f"节点创建成功: {created_node.value}, ID: {created_node.id}")
            return created_node
        except JumpServerAPIError as e:
            self.logger.error(f"创建节点失败: {str(e)}")
            raise
    
    def update_node(self, node_id: str, node_info: NodeInfo) -> NodeInfo:
        """
        更新节点
        
        Args:
            node_id: 节点ID
            node_info: 更新的节点信息
            
        Returns:
            NodeInfo: 更新后的节点信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"更新节点: ID={node_id}, 值={node_info.value}")
        
        try:
            # 设置ID
            node_info.id = node_id
            
            # 转换为字典用于请求
            node_data = node_info.to_dict()
            
            # 发送更新请求
            response = self._api_request("PUT", f"/api/v1/assets/nodes/{node_id}/", json_data=node_data)
            
            # 从响应创建节点对象
            updated_node = NodeInfo.from_dict(response)
            
            # 清除缓存
            self.cache.delete("get_nodes")
            
            self.logger.info(f"节点更新成功: {updated_node.value}")
            return updated_node
        except JumpServerAPIError as e:
            self.logger.error(f"更新节点失败: {str(e)}")
            raise
    
    def delete_node(self, node_id: str) -> None:
        """
        删除节点
        
        Args:
            node_id: 节点ID
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"删除节点: {node_id}")
        
        try:
            # 发送删除请求
            self._api_request("DELETE", f"/api/v1/assets/nodes/{node_id}/")
            
            # 清除缓存
            self.cache.delete("get_nodes")
            
            self.logger.info(f"节点删除成功: {node_id}")
        except JumpServerAPIError as e:
            self.logger.error(f"删除节点失败: {str(e)}")
            raise
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            Dict[str, Any]: 缓存统计信息
        """
        return self.cache.stats()
    
    def get_assets_by_node(self, node_id: str, force_refresh: bool = False) -> List[AssetInfo]:
        """
        获取指定节点下的资产列表
        
        Args:
            node_id: 节点ID
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[AssetInfo]: 该节点下的资产列表
        """
        self.logger.info(f"获取节点({node_id})下的资产")
        
        # 构建查询参数，包含节点ID
        params = {'node': node_id}
        
        # 使用已有的get_assets方法获取资产
        return self.get_assets(params, force_refresh) 