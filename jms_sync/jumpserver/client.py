#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JumpServer客户端模块 - 负责与JumpServer API交互

提供以下功能：
- 与JumpServer API的认证和通信
- 资产管理（通过AssetManager）
- 节点管理（通过JmsNodeManager）
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
from jms_sync.jumpserver.models import AssetInfo, NodeInfo, SyncResult
from jms_sync.jumpserver.asset_manager import AssetManager


class JumpServerClient:
    """
    JumpServer客户端类，提供与JumpServer API交互的功能。
    
    主要功能：
    - 资产管理（通过AssetManager）
    - 节点管理（通过JmsNodeManager）
    - 自动重试和缓存支持
    
    使用示例:
    ```python
    client = JumpServerClient(
        base_url="https://jumpserver.example.com",
        access_key_id="your-access-key-id",
        access_key_secret="your-access-key-secret"
    )
    
    # 获取所有资产
    assets = client.asset_manager.get_assets_by_node_id(node_id)
    
    # 创建资产
    asset = AssetInfo(
        name="test-server",
        ip="192.168.1.1",
        platform="Linux",
        protocol="ssh",
        port=22,
        node_id="node-id"
    )
    created_asset = client.asset_manager.create_asset(asset)
    ```
    """
    
    def __init__(
        self, 
        base_url: str, 
        access_key_id: str, 
        access_key_secret: str, 
        org_id: str = "00000000-0000-0000-0000-000000000002", 
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化JumpServer客户端
        
        Args:
            base_url: JumpServer API基础URL
            access_key_id: 访问密钥ID
            access_key_secret: 访问密钥密钥
            org_id: 组织ID，默认为"00000000-0000-0000-0000-000000000002"
            config: 配置字典，包含协议端口、账号模板等配置
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
        self.logger = get_logger(__name__)
        self.structured_logger = StructuredLogger(__name__)
        
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
        
        # 初始化资产管理器
        self.asset_manager = AssetManager(self)
        
        # 初始化节点管理器 - 确保在使用前导入NodeManager
        from jms_sync.jumpserver.node_manager import JmsNodeManager
        self.node_manager = JmsNodeManager(self)
        
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
    
    # 兼容方法 - 转发到asset_manager
    def create_asset(self, asset_info: Union[AssetInfo, Dict[str, Any]]) -> Union[AssetInfo, Dict[str, Any]]:
        """
        创建资产 (兼容方法)
        
        Args:
            asset_info: 资产信息，可以是AssetInfo对象或字典
            
        Returns:
            AssetInfo: 创建的资产信息
        """
        return self.asset_manager.create_asset(asset_info)
    
    # 兼容方法 - 转发到asset_manager
    def get_assets_by_node(self, node_id: str, force_refresh: bool = False) -> List[AssetInfo]:
        """
        获取节点下的资产 (兼容方法)
        
        Args:
            node_id: 节点ID
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[AssetInfo]: 资产列表
        """
        return self.asset_manager.get_assets_by_node_id(node_id)

    def get_assets(self, params: Optional[Dict[str, Any]] = None, force_refresh: bool = False) -> List[AssetInfo]:
        """
        获取资产列表 (已废弃)
        
        请使用资产管理器的方法代替
        
        Args:
            params: 查询参数，如分页、筛选等
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[AssetInfo]: 资产列表
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.warning("get_assets方法已废弃，请使用AssetManager类管理资产")
        # 兼容原有代码，使用API直接请求
        if params is None:
            params = {}
            
        try:
            response = self._api_request("GET", "/api/v1/assets/hosts/", params=params)
            assets = []
            
            if isinstance(response, dict) and 'results' in response:
                for item in response['results']:
                    assets.append(self.asset_manager._parse_asset_data(item))
            return assets
        except Exception as e:
            self.logger.error(f"获取资产列表失败: {str(e)}")
            return []
    
    def get_all_assets(self) -> List[AssetInfo]:
        """
        获取所有资产 (已废弃)
        
        请使用资产管理器的方法代替
        
        Returns:
            List[AssetInfo]: 所有资产列表
        """
        self.logger.warning("get_all_assets方法已废弃，请使用AssetManager类管理资产")
        return self.get_assets()
    
    def get_asset_by_ip(self, ip: str) -> Optional[AssetInfo]:
        """
        通过IP获取资产 (已废弃)
        
        请使用资产管理器的方法代替
        
        Args:
            ip: 资产IP
            
        Returns:
            Optional[AssetInfo]: 资产信息，如果不存在则返回None
        """
        self.logger.warning("get_asset_by_ip方法已废弃，请使用AssetManager类管理资产")
        params = {'ip': ip}
        assets = self.get_assets(params)
        if assets:
            return assets[0]
        return None
    
    def get_asset_by_name(self, name: str) -> Optional[AssetInfo]:
        """
        通过名称获取资产 (已废弃)
        
        请使用资产管理器的方法代替
        
        Args:
            name: 资产名称
            
        Returns:
            Optional[AssetInfo]: 资产信息，如果不存在则返回None
        """
        self.logger.warning("get_asset_by_name方法已废弃，请使用AssetManager类管理资产")
        params = {'name': name}
        assets = self.get_assets(params)
        if assets:
            return assets[0]
        return None
    
    def update_asset(self, asset_id: str, asset_info: AssetInfo) -> AssetInfo:
        """
        更新资产
        
        Args:
            asset_id: 资产ID
            asset_info: 资产信息
            
        Returns:
            AssetInfo: 更新后的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        # 确定平台ID
        platform_id = 1  # 默认为Linux
        if asset_info.platform.lower() == 'windows':
            platform_id = 5
            
        # 确定协议和端口
        protocol = "ssh"
        port = 22
        if asset_info.platform.lower() == 'windows':
            protocol = "rdp"
            port = 3389
            
        # 如果有指定协议和端口，则使用指定的值
        if asset_info.protocol:
            protocol = asset_info.protocol
        if asset_info.port:
            port = asset_info.port
            
        # 使用资产管理器更新资产
        return self.asset_manager.update_asset(
            asset_id=asset_id,
            name=asset_info.name,
            address=asset_info.address,
            platform_id=platform_id,
            node_id=asset_info.node_id,
            domain_id=asset_info.domain_id,
            protocol=protocol,
            port=port,
            comment=asset_info.comment,
            is_active=asset_info.is_active
        )
    
    def delete_asset(self, asset_id: str) -> None:
        """
        删除资产
        
        Args:
            asset_id: 资产ID
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        # 使用资产管理器删除资产
        self.asset_manager.delete_asset(asset_id)
    
    def get_nodes(self, params=None, force_refresh=False) -> List[NodeInfo]:
        """
        获取节点列表
        
        此方法已废弃，请使用JmsNodeManager类管理节点
        
        Args:
            params: 查询参数，如分页、筛选等
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[NodeInfo]: 节点列表
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.warning("get_nodes方法已废弃，请使用JmsNodeManager类管理节点")
        # 兼容原有代码，将调用转发到API请求
        endpoint = "/api/v1/assets/nodes/"
        if not params:
            params = {}
        
        try:
            response = self._api_request("GET", endpoint, params=params)
            if isinstance(response, dict) and 'results' in response:
                nodes = []
                for item in response['results']:
                    nodes.append(NodeInfo.from_dict(item))
                return nodes
            elif isinstance(response, list):
                nodes = []
                for item in response:
                    nodes.append(NodeInfo.from_dict(item))
                return nodes
            else:
                self.logger.warning(f"获取节点列表返回意外格式: {response}")
                return []
        except Exception as e:
            self.logger.error(f"获取节点列表失败: {str(e)}")
            return []
    
    def get_node_by_key(self, key: str) -> Optional[NodeInfo]:
        """
        通过Key获取节点 (已废弃)
        
        请使用JmsNodeManager类管理节点
        
        Args:
            key: 节点Key
            
        Returns:
            Optional[NodeInfo]: 节点信息，如果不存在则返回None
        """
        self.logger.warning("get_node_by_key方法已废弃，请使用JmsNodeManager类管理节点")
        return None
        
    def get_node_by_full_path(self, path: str) -> Optional[NodeInfo]:
        """
        通过完整路径获取节点 (已废弃)
        
        请使用JmsNodeManager类管理节点
        
        Args:
            path: 节点完整路径，例如 "/DEFAULT/aliyun/aliyun-prod"
            
        Returns:
            Optional[NodeInfo]: 节点信息，如果不存在则返回None
        """
        self.logger.warning("get_node_by_full_path方法已废弃，请使用JmsNodeManager类管理节点")
        return None
        
    def create_node(self, node_info: NodeInfo) -> NodeInfo:
        """
        创建节点 (已废弃)
        
        请使用JmsNodeManager类管理节点
        
        Args:
            node_info: 节点信息
            
        Returns:
            NodeInfo: 创建后的节点信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.warning("create_node方法已废弃，请使用JmsNodeManager类管理节点")
        return node_info
        
    def update_node(self, node_id: str, node_info: NodeInfo) -> NodeInfo:
        """
        更新节点 (已废弃)
        
        请使用JmsNodeManager类管理节点
        
        Args:
            node_id: 节点ID
            node_info: 更新的节点信息
            
        Returns:
            NodeInfo: 更新后的节点信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.warning("update_node方法已废弃，请使用JmsNodeManager类管理节点")
        return node_info
        
    def delete_node(self, node_id: str) -> None:
        """
        删除节点 (已废弃)
        
        请使用JmsNodeManager类管理节点
        
        Args:
            node_id: 节点ID
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.warning("delete_node方法已废弃，请使用JmsNodeManager类管理节点")
        return 