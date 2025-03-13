#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JumpServer 数据模型模块，定义与JumpServer交互的数据结构。
"""

from typing import Dict, List, Optional, Any, Set, Union
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class AssetInfo:
    """资产信息数据类"""
    id: Optional[str] = None
    name: str = ""
    ip: str = ""
    platform: str = "Linux"  # "Linux" 或 "Windows"
    protocol: str = "ssh"    # "ssh" 或 "rdp"
    port: int = 22
    is_active: bool = True
    public_ip: Optional[str] = None
    domain: Optional[str] = None
    domain_id: Optional[str] = None
    admin_user: Optional[str] = None
    admin_user_id: Optional[str] = None
    node: Optional[str] = None
    node_id: Optional[str] = None
    comment: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)
    accounts: List[Dict[str, Any]] = field(default_factory=list)  # 添加accounts字段支持账号模板
    
    def __hash__(self) -> int:
        """
        计算哈希值，使AssetInfo可以作为字典的键或集合的元素
        使用id作为唯一标识，如果id为None则使用ip和name组合
        
        Returns:
            int: 哈希值
        """
        if self.id:
            return hash(self.id)
        # 如果没有id，使用ip和name的组合
        return hash((self.ip, self.name))
    
    def __eq__(self, other) -> bool:
        """
        判断两个AssetInfo是否相等
        
        Args:
            other: 另一个对象
            
        Returns:
            bool: 是否相等
        """
        if not isinstance(other, AssetInfo):
            return False
        
        # 如果两者都有id，比较id
        if self.id and other.id:
            return self.id == other.id
        
        # 如果没有id，比较ip和name
        return self.ip == other.ip and self.name == other.name
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典，用于API请求。
        
        Returns:
            Dict[str, Any]: 资产信息字典
        """
        data = {
            "name": self.name,
            "ip": self.ip,
            "platform": self.platform,
            "protocol": self.protocol,
            "port": self.port,
            "is_active": self.is_active
        }
        
        # 添加可选字段
        if self.id:
            data["id"] = self.id
        if self.public_ip:
            data["public_ip"] = self.public_ip
        if self.domain_id:
            data["domain"] = self.domain_id
        if self.admin_user_id:
            data["admin_user"] = self.admin_user_id
        if self.node_id:
            data["nodes"] = [self.node_id]
        if self.comment:
            data["comment"] = self.comment
        if self.attrs:
            data["attrs"] = self.attrs
        if hasattr(self, 'accounts') and self.accounts:
            data["accounts"] = self.accounts
            
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AssetInfo':
        """
        从字典创建资产信息对象。
        
        Args:
            data: 资产信息字典
            
        Returns:
            AssetInfo: 资产信息对象
        """
        asset = cls(
            id=data.get("id"),
            name=data.get("name", ""),
            ip=data.get("ip", ""),
            platform=data.get("platform", "Linux"),
            protocol=data.get("protocol", "ssh"),
            port=data.get("port", 22),
            is_active=data.get("is_active", True),
            public_ip=data.get("public_ip"),
            comment=data.get("comment")
        )
        
        # 处理关系字段
        if "domain" in data:
            asset.domain_id = data["domain"]
        
        if "admin_user" in data:
            asset.admin_user_id = data["admin_user"]
        
        # 处理节点，JumpServer API中节点是一个列表
        nodes = data.get("nodes", [])
        if nodes and isinstance(nodes, list) and len(nodes) > 0:
            asset.node_id = nodes[0]
        
        # 处理属性字段
        asset.attrs = data.get("attrs", {})
        
        # 处理账号信息字段
        if "accounts" in data:
            asset.accounts = data["accounts"]
        
        return asset


@dataclass
class NodeInfo:
    """节点信息数据类"""
    id: Optional[str] = None
    name: str = ""
    key: str = ""
    value: str = ""
    parent: Optional[str] = None
    parent_key: Optional[str] = None
    assets_amount: int = 0
    full_value: Optional[str] = None
    
    def __hash__(self) -> int:
        """
        计算哈希值，使NodeInfo可以作为字典的键或集合的元素
        使用id作为唯一标识，如果id为None则使用value和key组合
        
        Returns:
            int: 哈希值
        """
        if self.id:
            return hash(self.id)
        # 如果没有id，使用value和key的组合
        return hash((self.value, self.key))
    
    def __eq__(self, other) -> bool:
        """
        判断两个NodeInfo是否相等
        
        Args:
            other: 另一个对象
            
        Returns:
            bool: 是否相等
        """
        if not isinstance(other, NodeInfo):
            return False
        
        # 如果两者都有id，比较id
        if self.id and other.id:
            return self.id == other.id
        
        # 如果没有id，比较value和key
        return self.value == other.value and self.key == other.key
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典，用于API请求。
        
        Returns:
            Dict[str, Any]: 节点信息字典
        """
        data = {
            "value": self.value,
        }
        
        # 添加可选字段
        if self.id:
            data["id"] = self.id
        if self.key:
            data["key"] = self.key
        if self.parent:
            data["parent"] = self.parent
            
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeInfo':
        """
        从字典创建节点信息对象。
        
        Args:
            data: 节点信息字典
            
        Returns:
            NodeInfo: 节点信息对象
        """
        node = cls(
            id=data.get("id"),
            name=data.get("name", ""),
            key=data.get("key", ""),
            value=data.get("value", ""),
            parent=data.get("parent"),
            assets_amount=data.get("assets_amount", 0)
        )
        
        # 处理父节点key
        if "parent_key" in data:
            node.parent_key = data["parent_key"]
        
        # 处理完整路径
        if "full_value" in data:
            node.full_value = data["full_value"]
            
        return node


@dataclass
class SyncResult:
    """同步结果数据类"""
    total: int = 0
    success: bool = True
    failed: int = 0
    skipped: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration: float = 0.0
    
    def __hash__(self) -> int:
        """
        计算哈希值，使SyncResult可以作为字典的键或集合的元素
        
        Returns:
            int: 哈希值
        """
        # 使用不可变属性计算哈希值
        return hash((
            self.total, 
            self.success, 
            self.failed, 
            self.skipped, 
            self.created, 
            self.updated, 
            self.deleted, 
            self.duration
        ))
    
    def __eq__(self, other) -> bool:
        """
        判断两个SyncResult是否相等
        
        Args:
            other: 另一个对象
            
        Returns:
            bool: 是否相等
        """
        if not isinstance(other, SyncResult):
            return False
        
        # 比较关键属性
        return (
            self.total == other.total and
            self.success == other.success and
            self.failed == other.failed and
            self.skipped == other.skipped and
            self.created == other.created and
            self.updated == other.updated and
            self.deleted == other.deleted and
            self.duration == other.duration
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典。
        
        Returns:
            Dict[str, Any]: 同步结果字典
        """
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "errors": self.errors,
            "duration": f"{self.duration:.2f}秒"
        }
    
    def add_error(self, asset_ip: str, error_message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        添加错误信息。
        
        Args:
            asset_ip: 资产IP
            error_message: 错误消息
            details: 错误详情
        """
        error = {
            "asset_ip": asset_ip,
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        
        if details:
            error["details"] = details
            
        self.errors.append(error)
        self.failed += 1 