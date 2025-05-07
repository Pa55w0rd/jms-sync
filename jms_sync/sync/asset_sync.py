#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
资产同步模块 - 负责JumpServer资产的同步操作

提供以下功能：
- 将云平台资产同步到JumpServer
- 资产创建、更新、删除操作
- 同步结果统计和报告
"""

import logging
import time
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from jms_sync.jumpserver.models import AssetInfo
from jms_sync.jumpserver.asset_manager import AssetManager
from jms_sync.jumpserver.node_manager import JmsNodeManager
from jms_sync.jumpserver.client import JumpServerClient
from jms_sync.utils.logger import get_logger

class AssetSyncManager:
    """
    资产同步管理器，负责协调云平台资产与JumpServer资产的同步
    
    使用示例:
    ```python
    # 初始化资产同步管理器
    sync_manager = AssetSyncManager(js_client)
    
    # 同步云平台资产到JumpServer
    result = sync_manager.sync_assets(
        cloud_assets=cloud_assets,
        node_id=node_id,
        cloud_type='aliyun',
        cloud_name='prod'
    )
    ```
    """
    
    def __init__(self, js_client: JumpServerClient, logger: Optional[logging.Logger] = None):
        """
        初始化资产同步管理器
        
        Args:
            js_client: JumpServer客户端实例
            logger: 日志记录器
        """
        self.js_client = js_client
        self.logger = logger or get_logger(__name__)
        self.asset_manager = js_client.asset_manager
        self.node_manager = JmsNodeManager(js_client, logger=self.logger)
        
        # 记录同步状态
        self.created_assets = []
        self.updated_assets = []
        self.deleted_assets = []
        self.update_reasons = []  # 添加更新原因记录
        self.failed_operations = []  # 添加失败操作记录
        
    def sync_assets(self, cloud_assets: List[Dict], node_id: str, cloud_type: str, 
                   cloud_name: str, no_delete: bool = False, protected_ips: List[str] = None) -> Dict[str, Any]:
        """
        同步云平台资产到JumpServer
        
        Args:
            cloud_assets: 云平台资产列表
            node_id: JumpServer节点ID
            cloud_type: 云平台类型，如'aliyun'、'huawei'
            cloud_name: 云平台名称，用于区分同类型的不同云账号
            no_delete: 是否禁止删除JumpServer资产
            protected_ips: 受保护的IP列表，这些IP对应的资产不会被删除
            
        Returns:
            Dict[str, Any]: 同步结果统计
        """
        self.logger.info(f"开始同步 {cloud_type}/{cloud_name} 云平台资产到JumpServer节点 {node_id}")
        
        # 重置同步状态
        self.reset_sync_status()
        
        # 初始化结果统计
        result = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "total": len(cloud_assets),
            "errors": []  # 用于记录错误信息
        }
        
        # 初始化受保护的IP列表
        if protected_ips is None:
            protected_ips = []
            
        # 记录开始时间
        start_time = time.time()
        
        try:
            # 1. 获取JumpServer节点下的资产
            js_assets = self.asset_manager.get_assets_by_node_id(node_id)
            self.logger.info(f"节点 {node_id} 下有 {len(js_assets)} 个JumpServer资产")
            
            # 2. 构建JumpServer资产索引 - 按IP、名称和实例ID
            js_assets_by_ip = {}
            js_assets_by_name = {}
            js_assets_by_instance_id = {}  # 添加按实例ID索引
            for asset in js_assets:
                if asset.address:
                    js_assets_by_ip[asset.address] = asset
                if asset.name:
                    js_assets_by_name[asset.name] = asset
                # 从备注中提取实例ID
                instance_id = self._extract_instance_id_from_comment(asset.comment)
                if instance_id:
                    js_assets_by_instance_id[instance_id] = asset
            
            # 3. 构建云平台资产索引 - 按IP和实例ID
            cloud_assets_by_ip = {}
            cloud_assets_by_instance_id = {}  # 添加按实例ID索引
            for asset in cloud_assets:
                # 提取IP
                ip = asset.get('ip') or asset.get('address') or asset.get('private_ip')
                if ip:
                    cloud_assets_by_ip[ip] = asset
                
                # 提取实例ID
                instance_id = asset.get('instance_id')
                if instance_id:
                    cloud_assets_by_instance_id[instance_id] = asset
                    
            self.logger.info(f"云平台资产: {len(cloud_assets)}个 (按IP: {len(cloud_assets_by_ip)}个, 按实例ID: {len(cloud_assets_by_instance_id)}个)")
            self.logger.info(f"JumpServer资产: {len(js_assets)}个 (按IP: {len(js_assets_by_ip)}个, 按实例ID: {len(js_assets_by_instance_id)}个)")
            
            # 4. 处理需要创建和更新的资产 - 基于实例ID优先
            processed_js_assets = set()  # 记录已处理的JMS资产ID，避免重复处理
            
            # 4.1 先基于实例ID处理
            for instance_id, cloud_asset in cloud_assets_by_instance_id.items():
                try:
                    # 提取必要信息
                    ip = cloud_asset.get('ip') or cloud_asset.get('address') or cloud_asset.get('private_ip')
                    name = cloud_asset.get('hostname') or cloud_asset.get('instance_name', f"{cloud_type}-{ip}")
                    platform = cloud_asset.get('os_type', 'Linux')
                    
                    # 构建备注信息
                    comment_parts = [f"由JMS-Sync同步于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
                    for key in ["instance_id", "instance_type", "region", "vpc_id"]:
                        if cloud_asset.get(key):
                            comment_parts.append(f"{key}: {cloud_asset.get(key)}")
                    comment = "\n".join(comment_parts)
                    
                    # 判断是否需要根据实例ID更新
                    if instance_id in js_assets_by_instance_id:
                        js_asset = js_assets_by_instance_id[instance_id]
                        processed_js_assets.add(js_asset.id)  # 标记为已处理
                        
                        # 检查是否需要更新（比对关键属性）
                        need_update = False
                        update_reasons = []
                        
                        # 检查IP是否变化
                        if js_asset.address != ip:
                            need_update = True
                            update_reasons.append(f"IP地址不同: {js_asset.address} -> {ip}")
                            
                        # 检查名称是否变化
                        if js_asset.name != name:
                            need_update = True
                            update_reasons.append(f"名称不同: {js_asset.name} -> {name}")
                            
                        # 检查平台类型是否变化
                        js_platform = "Windows" if js_asset.platform == 5 or getattr(js_asset, 'platform', '') == 'Windows' else "Linux"
                        if js_platform.lower() != platform.lower():
                            need_update = True
                            update_reasons.append(f"平台类型不同: {js_platform} -> {platform}")
                            
                        # 检查协议和端口是否变化
                        js_protocol = "rdp" if js_platform.lower() == "windows" else "ssh"
                        js_port = 3389 if js_platform.lower() == "windows" else 22
                        new_protocol = "rdp" if platform.lower() == "windows" else "ssh"
                        new_port = 3389 if platform.lower() == "windows" else 22
                        
                        if js_protocol != new_protocol or getattr(js_asset, 'port', js_port) != new_port:
                            need_update = True
                            update_reasons.append(f"协议或端口变化: {js_protocol}:{getattr(js_asset, 'port', js_port)} -> {new_protocol}:{new_port}")
                        
                        if need_update:
                            self.logger.info(f"更新资产: {js_asset.name} ({ip}), 实例ID: {instance_id}, 原因: {', '.join(update_reasons)}")
                            
                            # 确定平台ID
                            platform_id = 1  # 默认为Linux
                            if platform.lower() == 'windows':
                                platform_id = 5
                                
                            # 确定协议和端口
                            protocol = "ssh"
                            port = 22
                            if platform.lower() == 'windows':
                                protocol = "rdp"
                                port = 3389
                            
                            # 更新资产
                            try:
                                updated_asset = self.asset_manager.update_asset(
                                    asset_id=js_asset.id,
                                    name=name,
                                    address=ip,
                                    platform_id=platform_id,
                                    node_id=node_id,
                                    comment=comment,
                                    protocol=protocol,
                                    port=port
                                )
                                
                                # 更新成功，记录更新信息
                                self.updated_assets.append({
                                    "name": name,
                                    "ip": ip,
                                    "platform": platform,
                                    "instance_id": instance_id,
                                    "update_reasons": update_reasons  # 记录更新原因
                                })
                                result["updated"] += 1
                                self.update_reasons.append({
                                    "asset": name,
                                    "instance_id": instance_id,
                                    "reasons": update_reasons
                                })
                            except Exception as e:
                                self.logger.error(f"更新资产失败: {js_asset.name} ({ip}), 实例ID: {instance_id}, 错误: {str(e)}")
                                result["failed"] += 1
                                # 记录失败原因
                                self.failed_operations.append({
                                    "operation": "update",
                                    "asset_name": name,
                                    "asset_ip": ip,
                                    "instance_id": instance_id,
                                    "error": str(e)
                                })
                                result["errors"].append({
                                    "asset_ip": ip,
                                    "asset_name": name,
                                    "instance_id": instance_id,
                                    "operation": "update",
                                    "message": str(e)
                                })
                        else:
                            self.logger.debug(f"资产无需更新: {js_asset.name} ({ip}), 实例ID: {instance_id}")
                            result["skipped"] += 1
                    else:
                        # 实例ID不存在，需要创建新资产
                        self.logger.info(f"创建新资产: {name} ({ip}), 实例ID: {instance_id}")
                        
                        # 确定平台类型
                        platform_id = 1  # 默认为Linux
                        if platform.lower() == 'windows':
                            platform_id = 5
                            
                        # 确定协议和端口
                        protocol = "ssh"
                        port = 22
                        if platform.lower() == 'windows':
                            protocol = "rdp"
                            port = 3389
                        
                        # 创建资产
                        try:
                            if platform.lower() == 'windows':
                                new_asset = self.asset_manager.create_windows_asset(
                                    name=name,
                                    address=ip,
                                    node_id=node_id,
                                    comment=comment,
                                    port=port
                                )
                            else:
                                new_asset = self.asset_manager.create_linux_asset(
                                    name=name,
                                    address=ip,
                                    node_id=node_id,
                                    comment=comment,
                                    port=port
                                )
                                
                            # 创建成功，记录创建信息
                            self.created_assets.append({
                                "name": name,
                                "ip": ip,
                                "platform": platform,
                                "instance_id": instance_id
                            })
                            result["created"] += 1
                        except Exception as e:
                            self.logger.error(f"创建资产失败: {name} ({ip}), 实例ID: {instance_id}, 错误: {str(e)}")
                            result["failed"] += 1
                            # 记录失败原因
                            self.failed_operations.append({
                                "operation": "create",
                                "asset_name": name,
                                "asset_ip": ip,
                                "instance_id": instance_id,
                                "error": str(e)
                            })
                            result["errors"].append({
                                "asset_ip": ip,
                                "asset_name": name,
                                "instance_id": instance_id,
                                "operation": "create",
                                "message": str(e)
                            })
                except Exception as e:
                    self.logger.error(f"处理资产时发生错误: 实例ID: {instance_id}, 错误: {str(e)}")
                    result["failed"] += 1
                    # 记录失败原因
                    result["errors"].append({
                        "instance_id": instance_id,
                        "operation": "process",
                        "message": str(e)
                    })
                
            # 5. 处理需要删除的资产 - 根据instance_id和IP
            if not no_delete:
                # 获取所有云平台实例ID和IP
                cloud_instance_ids = set(cloud_assets_by_instance_id.keys())
                cloud_ips = set(cloud_assets_by_ip.keys())
                
                # 遍历JumpServer资产，检查哪些需要删除
                for asset in js_assets:
                    # 如果资产已经处理过，跳过
                    if asset.id in processed_js_assets:
                        continue
                        
                    # 从备注中提取实例ID
                    instance_id = self._extract_instance_id_from_comment(asset.comment)
                    
                    # 检查资产是否应该删除
                    should_delete = False
                    delete_reason = ""
                    
                    # 优先检查实例ID
                    if instance_id:
                        if instance_id not in cloud_instance_ids:
                            should_delete = True
                            delete_reason = f"实例ID {instance_id} 在云平台不存在"
                    # 如果没有实例ID，检查IP
                    elif asset.address and asset.address not in cloud_ips:
                        should_delete = True
                        delete_reason = f"IP地址 {asset.address} 在云平台不存在"
                    
                    # 检查是否在受保护的IP列表中
                    if asset.address in protected_ips:
                        self.logger.info(f"跳过受保护资产: {asset.name} ({asset.address})")
                        should_delete = False
                        result["skipped"] += 1
                        continue
                    
                    # 执行删除
                    if should_delete:
                        self.logger.info(f"删除资产: {asset.name} ({asset.address}), 原因: {delete_reason}")
                        try:
                            success = self.asset_manager.delete_asset(asset.id)
                            if success:
                                self.deleted_assets.append({
                                    "name": asset.name,
                                    "ip": asset.address,
                                    "platform": asset.platform,
                                    "instance_id": instance_id,
                                    "reason": delete_reason
                                })
                                result["deleted"] += 1
                            else:
                                self.logger.warning(f"删除资产失败: {asset.name} ({asset.address})")
                                result["failed"] += 1
                                # 记录失败原因
                                self.failed_operations.append({
                                    "operation": "delete",
                                    "asset_name": asset.name,
                                    "asset_ip": asset.address,
                                    "instance_id": instance_id,
                                    "error": "删除操作返回失败"
                                })
                                result["errors"].append({
                                    "asset_ip": asset.address,
                                    "asset_name": asset.name,
                                    "instance_id": instance_id,
                                    "operation": "delete",
                                    "message": "删除操作返回失败"
                                })
                        except Exception as e:
                            self.logger.error(f"删除资产时发生错误: {asset.name} ({asset.address}), 错误: {str(e)}")
                            result["failed"] += 1
                            # 记录失败原因
                            self.failed_operations.append({
                                "operation": "delete",
                                "asset_name": asset.name,
                                "asset_ip": asset.address,
                                "instance_id": instance_id,
                                "error": str(e)
                            })
                            result["errors"].append({
                                "asset_ip": asset.address,
                                "asset_name": asset.name,
                                "instance_id": instance_id,
                                "operation": "delete",
                                "message": str(e)
                            })
            else:
                self.logger.info("禁止删除JumpServer资产")
            
        except Exception as e:
            self.logger.exception(f"同步资产时发生错误: {str(e)}")
            result["failed"] += 1
            result["errors"].append({
                "operation": "sync",
                "message": str(e)
            })
            
        # 计算总耗时
        duration = time.time() - start_time
        result["duration"] = f"{duration:.2f}秒"
        
        # 记录同步结果
        self.logger.info(f"同步完成: 总计={result['total']}个, "
                        f"创建={result['created']}个, "
                        f"更新={result['updated']}个, "
                        f"删除={result['deleted']}个, "
                        f"跳过={result['skipped']}个, "
                        f"失败={result['failed']}个, "
                        f"耗时={result['duration']}")
        
        # 如果有更新，记录更新原因
        if result["updated"] > 0 and self.update_reasons:
            self.logger.info("更新资产原因:")
            for update in self.update_reasons:
                self.logger.info(f"  - {update['asset']} (实例ID: {update['instance_id']}): {', '.join(update['reasons'])}")
        
        # 如果有失败，记录失败原因
        if result["failed"] > 0 and self.failed_operations:
            self.logger.error("失败操作详情:")
            for failure in self.failed_operations:
                self.logger.error(f"  - {failure['operation'].upper()} 失败: {failure.get('asset_name', '')} ({failure.get('asset_ip', '')}), 错误: {failure['error']}")
        
        # 添加更新原因和失败操作到结果中
        result["update_reasons"] = self.update_reasons
        result["failed_operations"] = self.failed_operations
        
        return result
    
    def _extract_instance_id_from_comment(self, comment: str) -> Optional[str]:
        """
        从资产备注中提取实例ID
        
        Args:
            comment: 资产备注
            
        Returns:
            Optional[str]: 提取的实例ID，如果没有找到则返回None
        """
        if not comment:
            return None
            
        # 检查常见的实例ID格式
        if "instance_id:" in comment:
            # 找到实例ID行并提取
            lines = comment.split("\n")
            for line in lines:
                if "instance_id:" in line:
                    parts = line.split("instance_id:", 1)
                    if len(parts) > 1:
                        return parts[1].strip()
        
        return None
    
    def get_sync_status(self) -> Dict[str, List[AssetInfo]]:
        """
        获取同步状态
        
        Returns:
            Dict[str, List[AssetInfo]]: 同步状态
        """
        return {
            "created": self.created_assets,
            "updated": self.updated_assets,
            "deleted": self.deleted_assets,
            "update_reasons": self.update_reasons,  # 添加更新原因
            "failed_operations": self.failed_operations  # 添加失败操作
        }
    
    def reset_sync_status(self):
        """重置同步状态"""
        self.created_assets = []
        self.updated_assets = []
        self.deleted_assets = []
        self.update_reasons = []  # 添加更新原因
        self.failed_operations = []  # 添加失败操作 