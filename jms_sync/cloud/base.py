#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
云平台基类 - 定义云平台客户端的通用接口
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any, Optional

from jms_sync.utils.logger import get_logger

class CloudBase(ABC):
    """云平台基类"""
    
    def __init__(self, access_key_id: str, access_key_secret: str, region: str):
        """
        初始化云平台基类
        
        Args:
            access_key_id: 访问密钥ID
            access_key_secret: 访问密钥密钥
            region: 区域ID
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.region = region
        self.logger = get_logger(self.__class__.__name__)
        self.logger.info(f"初始化云平台客户端: {region}")
        
    @abstractmethod
    def get_client(self) -> Any:
        """
        获取云平台客户端
        
        Returns:
            Any: 云平台客户端
        """
        pass
    
    def set_region(self, region: str) -> None:
        """
        设置区域
        
        Args:
            region: 区域ID
        """
        if region != self.region:
            self.logger.info(f"切换区域: {self.region} -> {region}")
            self.region = region
            # 重新初始化客户端
            self.client = self.get_client()
        
    @abstractmethod
    def get_instances(self) -> List[Dict[str, Any]]:
        """
        获取指定区域的实例列表
        
        Returns:
            List[Dict[str, Any]]: 实例列表
        """
        pass
        
    def determine_os_type(self, instance: Dict[str, Any]) -> str:
        """
        根据实例信息确定操作系统类型
        
        Args:
            instance: 实例信息
            
        Returns:
            str: 操作系统类型，'Windows' 或 'Linux'
        """
        # 默认为Linux
        os_type = 'Linux'
        
        # 尝试从实例名称判断
        instance_name = instance.get('name', '').lower()
        if 'win' in instance_name:
            return 'Windows'
            
        # 尝试从操作系统信息判断
        os_name = instance.get('os_name', '').lower()
        if 'windows' in os_name:
            return 'Windows'
            
        # 尝试从操作系统类型判断
        os_type_field = instance.get('os_type', '').lower()
        if 'windows' in os_type_field or os_type_field == 'windows':
            return 'Windows'
            
        return os_type 