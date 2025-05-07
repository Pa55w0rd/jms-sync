#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JumpServer资产管理模块 - 负责JumpServer资产的创建、更新、删除和查询

提供以下功能：
- 创建Linux/Windows资产
- 更新资产
- 删除资产
- 查询节点下资产
"""

import logging
import json
import time
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from jms_sync.utils.exceptions import JumpServerError, JumpServerAPIError
from jms_sync.utils.decorators import retry, log_execution_time
from jms_sync.utils.logger import get_logger
from jms_sync.jumpserver.models import AssetInfo

class AssetManager:
    """
    JumpServer资产管理类，负责资产的创建、更新、删除和查询
    
    使用示例:
    ```python
    # 初始化资产管理器
    asset_manager = AssetManager(js_client)
    
    # 获取节点下的所有资产
    assets = asset_manager.get_assets_by_node_id('node-id')
    
    # 创建Linux资产
    asset = asset_manager.create_linux_asset(
        name='test-server',
        address='192.168.1.1',
        node_id='node-id',
        domain_id='domain-id'
    )
    ```
    """
    
    def __init__(self, js_client):
        """
        初始化资产管理器
        
        Args:
            js_client: JumpServer客户端实例
        """
        self.client = js_client
        self.logger = get_logger(__name__)
        
    def get_assets_by_node_id(self, node_id: str) -> List[AssetInfo]:
        """
        获取节点下的所有资产
        
        Args:
            node_id: 节点ID
            
        Returns:
            List[AssetInfo]: 资产列表
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"获取节点({node_id})下的资产")
        try:
            # 构建API请求
            endpoint = f"/api/v1/assets/hosts/?node_id={node_id}"
            
            # 发送请求
            response = self.client._api_request("GET", endpoint)
            
            # 解析响应
            if isinstance(response, list):
                assets = []
                for asset_data in response:
                    asset = self._parse_asset_data(asset_data)
                    assets.append(asset)
                return assets
            else:
                self.logger.error(f"获取节点({node_id})资产返回格式错误: {response}")
                return []
                
        except JumpServerAPIError as e:
            self.logger.error(f"获取节点({node_id})资产失败: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"获取节点({node_id})资产失败: {str(e)}")
            raise JumpServerAPIError(f"获取节点资产失败: {str(e)}")
    
    def _parse_asset_data(self, asset_data: Dict[str, Any]) -> AssetInfo:
        """
        解析资产数据
        
        Args:
            asset_data: API返回的资产数据
            
        Returns:
            AssetInfo: 资产信息对象
        """
        asset = AssetInfo()
        
        # 获取基本信息
        asset.id = asset_data.get('id', '')
        asset.name = asset_data.get('name', '')
        asset.address = asset_data.get('address', '')
        
        # 获取平台信息
        platform = asset_data.get('platform', {})
        asset.platform = platform.get('name', '') if isinstance(platform, dict) else str(platform)
        
        # 获取节点信息
        nodes = asset_data.get('nodes', [])
        if nodes and isinstance(nodes, list) and len(nodes) > 0:
            node = nodes[0]
            asset.node_id = node.get('id', '') if isinstance(node, dict) else ''
        
        # 获取协议信息
        protocols = asset_data.get('protocols', [])
        if protocols and isinstance(protocols, list) and len(protocols) > 0:
            protocol = protocols[0]
            if isinstance(protocol, dict):
                asset.protocol = protocol.get('name', '')
                asset.port = protocol.get('port', 0)
        
        # 获取其他信息
        asset.comment = asset_data.get('comment', '')
        asset.domain_id = asset_data.get('domain', '')
        asset.is_active = asset_data.get('is_active', True)
        
        return asset
    
    def create_linux_asset(self, name: str, address: str, node_id: str, domain_id: Optional[str] = None, 
                          comment: Optional[str] = None, port: int = 22) -> AssetInfo:
        """
        创建Linux资产
        
        Args:
            name: 资产名称
            address: 资产地址（IP）
            node_id: 节点ID
            domain_id: 网域ID，可选
            comment: 备注信息，可选
            port: SSH端口，默认22
            
        Returns:
            AssetInfo: 创建的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"创建Linux资产: {name} ({address})")
        
        # 构建请求数据
        asset_data = {
            "platform": {"pk": 1},  # 1表示Linux平台
            "nodes": [{"pk": node_id}],
            "protocols": [{"name": "ssh", "port": port}],
            "labels": [],
            "is_active": True,
            "name": name,
            "address": address,
            "comment": comment or f"由JMS-Sync同步于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        # 如果指定了网域，添加到请求数据
        if domain_id:
            asset_data["domain"] = domain_id
        
        # 添加账号列表，初始为空
        asset_data["accounts"] = []
        
        try:
            # 发送API请求
            endpoint = "/api/v1/assets/hosts/?platform=1"
            response = self.client._api_request("POST", endpoint, json_data=asset_data)
            
            # 解析响应
            asset = self._parse_asset_data(response)
            self.logger.info(f"Linux资产创建成功: {asset.name} (ID: {asset.id})")
            return asset
        except JumpServerAPIError as e:
            self.logger.error(f"创建Linux资产失败: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"创建Linux资产失败: {str(e)}")
            raise JumpServerAPIError(f"创建Linux资产失败: {str(e)}")
    
    def create_windows_asset(self, name: str, address: str, node_id: str, domain_id: Optional[str] = None,
                            comment: Optional[str] = None, port: int = 3389) -> AssetInfo:
        """
        创建Windows资产
        
        Args:
            name: 资产名称
            address: 资产地址（IP）
            node_id: 节点ID
            domain_id: 网域ID，可选
            comment: 备注信息，可选
            port: RDP端口，默认3389
            
        Returns:
            AssetInfo: 创建的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"创建Windows资产: {name} ({address})")
        
        # 构建请求数据
        asset_data = {
            "platform": {"pk": 5},  # 5表示Windows平台
            "nodes": [{"pk": node_id}],
            "protocols": [{"name": "rdp", "port": port}],
            "labels": [],
            "is_active": True,
            "name": name,
            "address": address,
            "comment": comment or f"由JMS-Sync同步于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        # 如果指定了网域，添加到请求数据
        if domain_id:
            asset_data["domain"] = domain_id
        
        # 添加账号列表，初始为空
        asset_data["accounts"] = []
        
        try:
            # 发送API请求
            endpoint = "/api/v1/assets/hosts/?platform=5"
            response = self.client._api_request("POST", endpoint, json_data=asset_data)
            
            # 解析响应
            asset = self._parse_asset_data(response)
            self.logger.info(f"Windows资产创建成功: {asset.name} (ID: {asset.id})")
            return asset
        except JumpServerAPIError as e:
            self.logger.error(f"创建Windows资产失败: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"创建Windows资产失败: {str(e)}")
            raise JumpServerAPIError(f"创建Windows资产失败: {str(e)}")
    
    def update_asset(self, asset_id: str, name: str, address: str, platform_id: int, node_id: str,
                    domain_id: Optional[str] = None, protocol: str = "ssh", port: int = 22,
                    comment: Optional[str] = None, is_active: bool = True) -> AssetInfo:
        """
        更新资产信息
        
        Args:
            asset_id: 资产ID
            name: 资产名称
            address: 资产地址（IP）
            platform_id: 平台ID，1表示Linux，5表示Windows
            node_id: 节点ID
            domain_id: 网域ID，可选
            protocol: 协议，ssh或rdp
            port: 端口号
            comment: 备注信息，可选
            is_active: 是否激活
            
        Returns:
            AssetInfo: 更新后的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"更新资产: {name} (ID: {asset_id})")
        
        # 构建请求数据
        asset_data = {
            "name": name,
            "address": address,
            "platform": {"pk": platform_id},
            "nodes": [{"pk": node_id}],
            "protocols": [{"name": protocol, "port": port}],
            "directory_services": [],
            "labels": [],
            "is_active": is_active,
            "comment": comment or f"由JMS-Sync同步于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        # 如果指定了网域，添加到请求数据
        if domain_id:
            asset_data["domain"] = domain_id
        else:
            asset_data["domain"] = None
        
        try:
            # 发送API请求
            endpoint = f"/api/v1/assets/hosts/{asset_id}/"
            response = self.client._api_request("PUT", endpoint, json_data=asset_data)
            
            # 解析响应
            asset = self._parse_asset_data(response)
            self.logger.info(f"资产更新成功: {asset.name} (ID: {asset.id})")
            return asset
        except JumpServerAPIError as e:
            self.logger.error(f"更新资产失败: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"更新资产失败: {str(e)}")
            raise JumpServerAPIError(f"更新资产失败: {str(e)}")
    
    def delete_asset(self, asset_id: str) -> bool:
        """
        删除资产
        
        Args:
            asset_id: 资产ID
            
        Returns:
            bool: 删除是否成功
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        self.logger.info(f"删除资产: ID={asset_id}")
        
        try:
            # 发送API请求
            endpoint = f"/api/v1/assets/hosts/{asset_id}/"
            self.client._api_request("DELETE", endpoint)
            
            self.logger.info(f"资产删除成功: ID={asset_id}")
            return True
        except JumpServerAPIError as e:
            self.logger.error(f"删除资产失败: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"删除资产失败: {str(e)}")
            raise JumpServerAPIError(f"删除资产失败: {str(e)}")
    
    def create_asset(self, asset_info: AssetInfo) -> AssetInfo:
        """
        根据操作系统类型创建资产
        
        Args:
            asset_info: 资产信息对象
            
        Returns:
            AssetInfo: 创建的资产信息
            
        Raises:
            JumpServerAPIError: API请求失败时抛出异常
        """
        # 根据平台类型选择创建方法
        if asset_info.platform.lower() == 'windows':
            return self.create_windows_asset(
                name=asset_info.name,
                address=asset_info.address,
                node_id=asset_info.node_id,
                domain_id=asset_info.domain_id,
                comment=asset_info.comment,
                port=asset_info.port or 3389
            )
        else:
            # 默认为Linux
            return self.create_linux_asset(
                name=asset_info.name,
                address=asset_info.address,
                node_id=asset_info.node_id,
                domain_id=asset_info.domain_id,
                comment=asset_info.comment,
                port=asset_info.port or 22
            ) 