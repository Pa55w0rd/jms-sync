#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
同步操作模块，负责云平台资产同步到JumpServer的具体操作�

主要功能�
- 从云平台获取资产信息
- 将资产信息同步到JumpServer
- 处理同步过程中的错误和异�
"""

import os
import time
import uuid
import logging
import threading
import re  # 添加正则表达式模块
from typing import Dict, List, Tuple, Any, Optional, Union
from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from jms_sync.jumpserver.models import AssetInfo, NodeInfo, SyncResult
from jms_sync.utils.exceptions import JmsSyncError
from jms_sync.utils.logger import get_logger

# 定义资产元组类型
AssetTuple = Tuple[str, Dict[str, Any]]  # (ip, asset_data)

class ProgressReporter:
    """
    进度报告器，用于报告同步进度
    """
    
    def __init__(self, total: int, logger, interval: int = 5):
        """
        初始化进度报告器
        
        Args:
            total: 总任务数
            logger: 日志记录�
            interval: 报告间隔（秒�
        """
        self.total = total
        self.current = 0
        self.logger = logger
        self.interval = interval
        self.start_time = time.time()
        self.last_report_time = self.start_time
        self.lock = threading.RLock()
        
    def update(self, increment: int = 1):
        """
        更新进度
        
        Args:
            increment: 增量
        """
        with self.lock:
            self.current += increment
            current_time = time.time()
            
            # 检查是否需要报告进�
            if (current_time - self.last_report_time >= self.interval or 
                self.current == self.total):
                self._report_progress(current_time)
                self.last_report_time = current_time
                
    def _report_progress(self, current_time: float):
        """
        报告进度
        
        Args:
            current_time: 当前时间
        """
        elapsed = current_time - self.start_time
        percentage = (self.current / self.total) * 100 if self.total > 0 else 0
        
        # 计算估计的剩余时间
        if self.current > 0 and self.current < self.total:
            items_per_sec = self.current / elapsed
            remaining_items = self.total - self.current
            estimated_remaining_time = remaining_items / items_per_sec if items_per_sec > 0 else 0
            eta_msg = f", 预计剩余时间: {estimated_remaining_time:.1f}秒"
        else:
            eta_msg = ""
            
        self.logger.info(
            f"进度: {self.current}/{self.total} ({percentage:.1f}%), "
            f"用时: {elapsed:.1f}秒{eta_msg}"
        )

class CloudAssetOperation:
    """
    云平台资产操作类，负责获取和处理云平台资�
    """
    
    def __init__(self, cloud_client, js_client, config: Dict[str, Any], cache_ttl: int = 3600, logger=None):
        """
        初始化云平台资产操作�
        
        Args:
            cloud_client: 云平台客户端
            js_client: JumpServer客户�
            config: 云平台配�
            cache_ttl: 缓存过期时间
            logger: 日志记录�
        """
        self.cloud_client = cloud_client
        self.js_client = js_client
        self.cloud_config = config
        self.cloud_type = config.get('type', 'unknown')
        self.domain_id = config.get('domain_id', '')
        self.cache_ttl = cache_ttl
        self.assets_cache = None
        self.cache_time = 0
        
        # 添加线程锁，用于确保节点创建的原子�
        self._lock = threading.Lock()
        
        self.logger = logger or logging.getLogger(__name__)
        
        # 兼容单个region或region列表
        regions = config.get('regions', [])
        if isinstance(regions, str):
            self.regions = [regions]
        elif isinstance(regions, list):
            self.regions = regions
        else:
            self.regions = []
            
        # 确保至少有一个region
        if not self.regions and config.get('region'):
            self.regions = [config.get('region')]
            
        # 初始化VPC映射
        self.vpc_map = {}
        
    def get_cloud_assets(self) -> List[Dict]:
        """
        获取云平台的资产列表
        
        Returns:
            List[Dict]: 资产列表，每个元素为完整的资产字�
        """
        assets = []
        
        # 记录开始时�
        start_time = time.time()
        
        # 处理不同区域
        for region in self.regions:
            try:
                self.logger.info(f"开始获取云平台 {self.cloud_type} 区域 {region} 的资产")
                
                # 根据云平台类型获取实例
                instances = []
                if self.cloud_type == 'aliyun' or self.cloud_type == '阿里云':
                    # 阿里云客户端已经在创建时绑定了区域，无需传递region参数
                    instances = self.cloud_client.get_instances()
                elif self.cloud_type == 'huawei' or self.cloud_type == '华为云':
                    # 华为云客户端已经在创建时绑定了区域，无需传递region参数
                    instances = self.cloud_client.get_instances()
                elif self.cloud_type == 'tencent' or self.cloud_type == '腾讯云':
                    # 腾讯云客户端可能需要区域参数
                    instances = self.cloud_client.get_instances(region)
                elif self.cloud_type == 'aws':
                    # AWS客户端可能需要区域参数
                    instances = self.cloud_client.get_instances(region)
                else:
                    self.logger.warning(f"未知的云平台类型: {self.cloud_type}")
                    instances = []
                
                self.logger.info(f"从云平台 {self.cloud_type} 区域 {region} 获取到 {len(instances)} 个实例")
                
                # 处理实例
                region_assets = []
                for instance in instances:
                    # 处理实例数据
                    processed_data = self._process_instance_data(instance, region)
                    
                    # 如果处理成功，获取IP并添加到资产列表
                    if processed_data:
                        ip = self._get_instance_ip(instance)
                        if ip:
                            # 添加IP到处理后的数据
                            processed_data['ip'] = ip
                            region_assets.append(processed_data)
                        else:
                            self.logger.warning(f"实例 {processed_data.get('instance_id', 'unknown')} 没有可用IP，跳过")
                
                self.logger.info(f"区域 {region} 处理成功，获取到 {len(region_assets)} 个可用资产")
                assets.extend(region_assets)
            except Exception as e:
                self.logger.error(f"获取区域 {region} 资产失败: {str(e)}", exc_info=True)
        
        self.logger.info(f"云平台 {self.cloud_type} 资产获取完成，总计 {len(assets)} 个资产，耗时: {time.time() - start_time:.2f}秒")
        
        return assets
        
    def _process_instance_data(self, instance: Dict[str, Any], region: str) -> Optional[Dict[str, Any]]:
        """
        处理实例数据，提取关键信�
        
        Args:
            instance: 实例数据
            region: 区域
            
        Returns:
            Optional[Dict[str, Any]]: 处理后的实例数据，如果无法处理则返回None
        """
        try:
            # 获取实例ID
            instance_id = self._extract_instance_id(instance)
            if not instance_id:
                self.logger.warning(f"无法获取实例ID: {instance}")
                return None
            
            # 获取实例名称
            instance_name = self._extract_instance_name(instance)
            if not instance_name:
                instance_name = f"{self.cloud_type}-{instance_id}"
                # 记录更详细的日志，包括可用的字段
                instance_fields = {k: v for k, v in instance.items() if k in ['name', 'InstanceName', 'instance_name', 'Name', 'hostname', 'InstanceId', 'instance_id']}
                self.logger.warning(f"无法获取实例名称，使用默认名� {instance_name}，可用字� {instance_fields}")
            
            # 获取操作系统类型
            os_type = self._extract_os_type(instance)
            
            # 添加详细日志记录操作系统类型信息
            self.logger.debug(f"实例 {instance_id}({instance_name}) 的操作系统类型: {os_type}")
            if 'os_type' in instance:
                self.logger.debug(f"实例原始 os_type 字段值: {instance.get('os_type')}")
            
            # 构建主机名（以实例名称为基础
            hostname = instance_name
            
            # 构建资产数据
            asset_data = {
                'instance_id': instance_id,
                'instance_name': instance_name,
                'hostname': hostname,
                'region': region,
                'os_type': os_type,
                'cloud_type': self.cloud_type
            }
            
            # 添加额外信息
            self._add_extra_instance_info(instance, asset_data)
            
            # 尝试获取公网IP
            try:
                if self.cloud_type == 'aliyun':
                    public_ip = self._get_aliyun_public_ip(instance)
                elif self.cloud_type == 'huawei':
                    public_ip = instance.get('publicIp', '')
                else:
                    public_ip = ''
                    
                if public_ip:
                    asset_data['public_ip'] = public_ip
            except Exception as e:
                self.logger.warning(f"获取实例 {instance_id} 的公网IP失败: {e}")
            
            return asset_data
        except Exception as e:
            self.logger.error(f"处理实例数据时出� {str(e)}", exc_info=True)
            return None

    def _extract_instance_id(self, instance: Dict[str, Any]) -> Optional[str]:
        """
        提取实例ID
        
        Args:
            instance: 实例数据
            
        Returns:
            Optional[str]: 实例ID，如果无法提取则返回None
        """
        # 直接使用instance_id字段
        if "instance_id" in instance:
            return instance["instance_id"]
        
        # 使用id字段作为实例ID
        if "id" in instance:
            return instance["id"]
            
        # 处理不同云平台的命名差异
        if self.cloud_type == 'aliyun':
            # 阿里云实例ID可能在InstanceId字段
            return instance.get("InstanceId")
        elif self.cloud_type == 'huawei':
            # 华为云实例ID可能在id字段
            return instance.get("id")
        elif self.cloud_type == 'tencent':
            # 腾讯云实例ID可能在InstanceId字段
            return instance.get("InstanceId")
        elif self.cloud_type == 'aws':
            # AWS实例ID可能在InstanceId字段
            return instance.get("InstanceId")
            
        # 尝试其他常见字段�
        for key in ["InstanceId", "Id", "VmId", "ResourceId", "HostId"]:
            if key in instance:
                return instance[key]
                
        # 记录无法提取ID的情�
        self.logger.warning(f"无法提取实例ID，实例数� {instance}")
        return None

    def _extract_instance_name(self, instance: Dict[str, Any]) -> Optional[str]:
        """
        提取实例名称
        
        Args:
            instance: 实例数据
            
        Returns:
            Optional[str]: 实例名称
        """
        # 处理不同云平台的实例名称
        if self.cloud_config.get('type') == 'aliyun':
            # 尝试不同的可能字段名来获取实例名�
            for key in ['name', 'InstanceName', 'instance_name', 'Name']:
                if key in instance and instance[key]:
                    return instance[key]
                
            # 如果实例名称为空，检查是否有实例ID
            instance_id = instance.get('instance_id') or instance.get('InstanceId')
            if instance_id:
                return f"ecs-{instance_id}"
            return None
        elif self.cloud_config.get('type') == 'huawei':
            return instance.get('name')
        elif self.cloud_config.get('type') == 'tencent':
            return instance.get('InstanceName')
        elif self.cloud_config.get('type') == 'aws':
            # AWS可能在Tags中存储Name
            if 'Tags' in instance:
                for tag in instance['Tags']:
                    if tag.get('Key') == 'Name':
                        return tag.get('Value')
            return instance.get('InstanceId')  # 如果没有名称，使用ID
        else:
            # 通用处理
            for key in ['name', 'Name', 'instance_name', 'instanceName', 'InstanceName']:
                if key in instance and instance[key]:
                    return instance[key]
        return None

    def _extract_os_type(self, instance: Dict[str, Any]) -> str:
        """
        提取操作系统类型
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 操作系统类型
        """
        # 默认为Linux
        os_type = 'Linux'
        
        # 首先直接检查os_type字段
        direct_os_type = instance.get('os_type', '')
        if isinstance(direct_os_type, str) and 'windows' in direct_os_type.lower():
            os_type = 'Windows'
            self.logger.debug(f"直接从os_type字段检测到Windows: {direct_os_type}")
            return os_type
            
        # 处理不同云平台的操作系统类型
        if self.cloud_config.get('type') == 'aliyun' or self.cloud_config.get('type') == '阿里云':
            os_name = instance.get('OSName', '').lower()
            if 'windows' in os_name:
                os_type = 'Windows'
                self.logger.debug(f"检测到阿里云Windows实例: {instance.get('InstanceName', '')}, OSName: {instance.get('OSName', '')}")
        elif self.cloud_config.get('type') == 'huawei' or self.cloud_config.get('type') == '华为云':
            metadata = instance.get('metadata', {})
            os_type = metadata.get('os_type', 'Linux')
            image_name = instance.get('image', {}).get('name', '').lower()
            
            # 检查元数据和镜像名称中是否包含Windows关键字
            if os_type.lower() == 'windows' or 'windows' in image_name:
                os_type = 'Windows'
                self.logger.debug(f"检测到华为云Windows实例: {instance.get('name', '')}, OS类型: {os_type}, 镜像: {image_name}")
        elif self.cloud_config.get('type') == 'tencent' or self.cloud_config.get('type') == '腾讯云':
            os_name = instance.get('OsName', '').lower()
            if 'windows' in os_name:
                os_type = 'Windows'
                self.logger.debug(f"检测到腾讯云Windows实例: {instance.get('InstanceName', '')}, OsName: {instance.get('OsName', '')}")
        elif self.cloud_config.get('type') == 'aws':
            platform = instance.get('Platform', '').lower()
            if platform == 'windows':
                os_type = 'Windows'
                self.logger.debug(f"检测到AWS Windows实例: {instance.get('InstanceId', '')}, Platform: {platform}")
        
        # 通用检查：检查实例名称或其他字段是否包含Windows关键字
        instance_name = self._extract_instance_name(instance) or ''
        if 'windows' in instance_name.lower():
            os_type = 'Windows'
            self.logger.debug(f"通过实例名称检测到Windows实例: {instance_name}")
            
        # 检查其他可能的字段
        os_version = instance.get('os_version', '').lower()
        if os_version and 'windows' in os_version:
            os_type = 'Windows'
            self.logger.debug(f"通过os_version字段检测到Windows实例: {os_version}")
            
        image_name = instance.get('image_name', '')
        if isinstance(image_name, str) and 'windows' in image_name.lower():
            os_type = 'Windows'
            self.logger.debug(f"通过image_name字段检测到Windows实例: {image_name}")
            
        description = instance.get('description', '')
        if isinstance(description, str) and 'windows' in description.lower():
            os_type = 'Windows'
            self.logger.debug(f"通过description字段检测到Windows实例: {description}")
        
        # 记录最终识别的操作系统类型
        instance_id = self._extract_instance_id(instance) or 'unknown'
        self.logger.debug(f"实例 {instance_id} 的操作系统类型: {os_type}")
        
        return os_type

    def _add_extra_instance_info(self, instance: Dict[str, Any], asset_data: Dict[str, Any]) -> None:
        """
        添加额外的实例信息
        
        Args:
            instance: 实例数据
            asset_data: 资产数据
        """
        # 添加VPC信息
        if self.cloud_config.get('type') == 'aliyun' or self.cloud_config.get('type') == '阿里云':
            asset_data['vpc_id'] = instance.get('VpcAttributes', {}).get('VpcId')
        elif self.cloud_config.get('type') == 'huawei' or self.cloud_config.get('type') == '华为云':
            asset_data['vpc_id'] = instance.get('vpc_id')
        elif self.cloud_config.get('type') == 'tencent' or self.cloud_config.get('type') == '腾讯云':
            asset_data['vpc_id'] = instance.get('VirtualPrivateCloud', {}).get('VpcId')
        elif self.cloud_config.get('type') == 'aws':
            asset_data['vpc_id'] = instance.get('VpcId')
        
        # 添加实例类型
        if self.cloud_config.get('type') == 'aliyun' or self.cloud_config.get('type') == '阿里云':
            asset_data['instance_type'] = instance.get('InstanceType')
        elif self.cloud_config.get('type') == 'huawei' or self.cloud_config.get('type') == '华为云':
            asset_data['instance_type'] = instance.get('flavor', {}).get('id')
        elif self.cloud_config.get('type') == 'tencent' or self.cloud_config.get('type') == '腾讯云':
            asset_data['instance_type'] = instance.get('InstanceType')
        elif self.cloud_config.get('type') == 'aws':
            asset_data['instance_type'] = instance.get('InstanceType')

    def _get_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取实例IP地址
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 添加调试日志
        self.logger.debug(f"获取实例IP，实例数据: {instance}")
        
        # 根据云平台类型选择不同的IP获取方法
        cloud_type = self.cloud_config.get('type', '')
        
        if cloud_type == 'aliyun' or cloud_type == '阿里云':
            ip = self._get_aliyun_instance_ip(instance)
            self.logger.debug(f"阿里云实例IP获取结果: {ip}")
            return ip
        elif cloud_type == 'huawei' or cloud_type == '华为云':
            ip = self._get_huawei_instance_ip(instance)
            self.logger.debug(f"华为云实例IP获取结果: {ip}")
            return ip
        elif cloud_type == 'tencent' or cloud_type == '腾讯云':
            return self._get_tencent_instance_ip(instance)
        elif cloud_type == 'aws':
            return self._get_aws_instance_ip(instance)
        else:
            # 通用处理
            return self._get_generic_instance_ip(instance)

    def _get_aliyun_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取阿里云实例IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 优先使用实例数据中的private_ip
        if instance.get('private_ip'):
            return instance['private_ip']
            
        # 如果没有private_ip，尝试使用public_ip
        if instance.get('public_ip'):
            return instance['public_ip']
            
        # 如果上面都没有，尝试从其他字段获�
        # 检查VPC属性中的私有IP
        vpc_attrs = instance.get('VpcAttributes', {})
        private_ip_address = vpc_attrs.get('PrivateIpAddress', {}).get('IpAddress', [])
        
        if private_ip_address and isinstance(private_ip_address, list) and len(private_ip_address) > 0:
            return private_ip_address[0]
        
        # 检查网络接口中的私有IP
        network_interfaces = instance.get('NetworkInterfaces', {}).get('NetworkInterface', [])
        if network_interfaces and len(network_interfaces) > 0:
            primary_ip = network_interfaces[0].get('PrimaryIpAddress', '')
            if primary_ip:
                return primary_ip
        
        # 检查内网IP字段
        inner_ip = instance.get('InnerIpAddress', {}).get('IpAddress', [])
        if inner_ip and isinstance(inner_ip, list) and len(inner_ip) > 0:
            return inner_ip[0]
            
        # 检查公网IP地址
        public_ip_address = instance.get('PublicIpAddress', {}).get('IpAddress', [])
        if public_ip_address and isinstance(public_ip_address, list) and len(public_ip_address) > 0:
            return public_ip_address[0]
        
        # 检查弹性公网IP
        eip_address = instance.get('EipAddress', {}).get('IpAddress', '')
        if eip_address:
            return eip_address
        
        return ""

    def _get_aliyun_public_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取阿里云实例公网IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 公网IP地址
        """
        # 检查公网IP地址
        public_ip_address = instance.get('PublicIpAddress', {}).get('IpAddress', [])
        if public_ip_address and isinstance(public_ip_address, list) and len(public_ip_address) > 0:
            return public_ip_address[0]
        
        # 检查弹性公网IP
        eip_address = instance.get('EipAddress', {}).get('IpAddress', '')
        if eip_address:
            return eip_address
        
        return ""

    def _get_huawei_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取华为云实例IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 优先使用实例数据中的private_ip
        if instance.get('private_ip'):
            return instance['private_ip']
            
        # 如果没有private_ip，尝试使用public_ip
        if instance.get('public_ip'):
            return instance['public_ip']
            
        # 如果上面都没有，尝试从其他字段获�
        # 优先使用私有IP
        addresses = instance.get('addresses', {})
        if addresses:
            for network_name, ips in addresses.items():
                for ip_info in ips:
                    if ip_info.get('OS-EXT-IPS:type') == 'fixed':
                        return ip_info.get('addr', '')
        
        # 如果没有找到私有IP，尝试其他方�
        if 'addresses' in instance:
            for network_name, ips in instance['addresses'].items():
                if ips and len(ips) > 0:
                    return ips[0].get('addr', '')
        
        # 检查metadata中的内网IP
        metadata = instance.get('metadata', {})
        private_ip = metadata.get('private_ip', '')
        if private_ip:
            return private_ip
        
        return ""

    def _get_tencent_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取腾讯云实例IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 优先使用私有IP
        private_ip = ""
        vpc = instance.get('VirtualPrivateCloud', {})
        private_ips = vpc.get('PrivateIpAddresses', [])
        if private_ips and len(private_ips) > 0:
            private_ip = private_ips[0]
        
        if private_ip:
            return private_ip
        
        # 如果没有私有IP，尝试使用公网IP
        public_ip = instance.get('PublicIpAddresses', [])
        if public_ip and len(public_ip) > 0:
            return public_ip[0]
        
        return ""

    def _get_aws_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取AWS实例IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 优先使用私有IP
        private_ip = instance.get('PrivateIpAddress', '')
        if private_ip:
            return private_ip
        
        # 如果没有私有IP，尝试使用公网IP
        public_ip = instance.get('PublicIpAddress', '')
        if public_ip:
            return public_ip
        
        return ""

    def _get_generic_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        获取通用实例IP
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP
        """
        # 尝试从不同字段获取IP
        for ip_field in ['ip', 'IP', 'privateIp', 'PrivateIp', 'private_ip', 'PrivateIpAddress', 'privateIpAddress']:
            if ip_field in instance:
                return instance[ip_field]
                
        # 尝试从网络接口获取IP
        if 'NetworkInterfaces' in instance:
            interfaces = instance['NetworkInterfaces']
            if interfaces and isinstance(interfaces, list) and len(interfaces) > 0:
                interface = interfaces[0]
                if 'PrivateIpAddress' in interface:
                    return interface['PrivateIpAddress']
                elif 'privateIpAddress' in interface:
                    return interface['privateIpAddress']
                    
        # 如果没有找到IP，返回空字符�
        return ""

class AssetSynchronizer:
    """资产同步器类，处理资产同步相关的操作"""
    
    def __init__(
        self,
        js_client: "JumpServerClient",
        parallel_workers: int = 5,
        batch_size: int = 50,
        logger: Optional[logging.Logger] = None,
        cloud_config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化资产同步器
        
        Args:
            js_client: JumpServer客户端
            parallel_workers: 并行工作线程数
            batch_size: 批处理大小
            logger: 日志记录器
            cloud_config: 云平台配置
        """
        self.js_client = js_client
        self.parallel_workers = parallel_workers
        self.batch_size = batch_size
        self.logger = logger or logging.getLogger(__name__)
        self.cloud_config = cloud_config or {}
        
        # 初始化结果指标
        self.metrics = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "failed": 0,
            "total": 0
        }
        
        # 添加资产变更记录
        self.created_assets = []  # 记录新创建的资产
        self.deleted_assets = []  # 记录删除的资产
        
        # 线程锁用于安全计数
        self._lock = threading.Lock()
        
        # 初始化缓存
        self._jumpserver_assets_cache = {}
        self._platform_nodes = {}
        self._node_cache = {}  # 节点缓存: {node_key: node_obj}
        
        # 从配置中获取用户选项
        self.whitelist = self.cloud_config.get('whitelist', [])
        self.protected_ips = self.cloud_config.get('protected_ips', [])
        self.no_delete = self.cloud_config.get('no_delete', False)
        if 'no_delete' in self.cloud_config:
            self.no_delete = self.cloud_config['no_delete']
        
        # 获取账号模板配置
        self.js_config = js_client.config
        self.account_templates = self.js_config.get('account_templates', {})
        
        # 确保基础节点存在
        self._ensure_basic_nodes()
        
    def _ensure_basic_nodes(self):
        """确保基本节点存在，使用父子层级结构 DEFAULT/类型/名称"""
        # 获取云平台信息
        cloud_type = self.cloud_config.get('type', '')
        cloud_name = self.cloud_config.get('name', 'default')
        if not cloud_type:
            self.logger.warning("云平台类型未指定，将在首次使用时按需获取节点")
            return
            
        # 构建缓存键
        cache_key = f"{cloud_type}_{cloud_name}"
        
        self.logger.info(f"准备云平台节点: DEFAULT/{cloud_type}/{cloud_name}")
        
        # 查找或创建三级结构
        platform_node = self._get_node_by_path(f"DEFAULT/{cloud_type}/{cloud_name}")
        if platform_node:
            self._platform_nodes[cache_key] = platform_node
            return
            
        # 如果无法获取完整路径，退回到父节点
        self.logger.warning(f"无法获取完整路径 DEFAULT/{cloud_type}/{cloud_name}，将尝试获取父路径")
        platform_node = self._get_node_by_path(f"DEFAULT/{cloud_type}")
        if platform_node:
            self._platform_nodes[cache_key] = platform_node
            return
            
        # 最后使用根节点
        platform_node = self._get_node_by_path("DEFAULT")
        if platform_node:
            self._platform_nodes[cache_key] = platform_node
            return
            
        self.logger.error("无法获取或创建任何节点，同步将失败")
        
    def _get_node_by_path(self, path):
        """获取或创建指定路径的节点，支持多级路径"""
        from jms_sync.jumpserver.models import NodeInfo
        
        # 如果路径已缓存，直接返回
        if path in self._node_cache:
            node = self._node_cache[path]
            self.logger.debug(f"使用缓存的节点: {path} (ID: {node.id})")
            return node
            
        # 解析路径
        path_parts = path.split('/')
        if not path_parts:
            self.logger.error(f"无效的节点路径: {path}")
            return None
            
        # 获取所有节点
        try:
            all_nodes = self.js_client.get_nodes()
            self.logger.debug(f"获取到{len(all_nodes)}个节点")
        except Exception as e:
            self.logger.error(f"获取节点列表失败: {str(e)}")
            return None
            
        # 在现有节点中查找或创建路径
        parent_id = None
        current_path = ""
        current_node = None
        
        for i, part in enumerate(path_parts):
            if not part:
                continue
                
            # 更新当前路径
            if current_path:
                current_path += f"/{part}"
            else:
                current_path = part
                
            # 检查当前路径是否已缓存
            if current_path in self._node_cache:
                current_node = self._node_cache[current_path]
                parent_id = current_node.id
                continue
                
            # 查找当前级别的节点
            found = False
            for node in all_nodes:
                # 优先使用 node.name，如果不存在或为空则使用 node.value
                cand_name = ''
                if hasattr(node, 'name') and node.name:
                    cand_name = node.name.lower()
                elif hasattr(node, 'value') and node.value:
                    cand_name = node.value.lower()

                if cand_name == part.lower():
                    # 对于根节点，不检查父节点关系
                    if i == 0 or parent_id is None:
                        found = True
                        current_node = node
                        parent_id = node.id
                        self._node_cache[current_path] = node
                        self.logger.info(f"找到根节点: {part} (ID: {node.id})")
                        break

                    # 检查父节点关系
                    if hasattr(node, 'parent'):
                        node_parent = node.parent
                        if isinstance(node_parent, dict) and 'id' in node_parent:
                            node_parent = node_parent.get('id')
                        
                        # 如果父节点等于期望的 parent_id 或者候选节点没有父节点信息，则认为匹配
                        if node_parent == parent_id or not node_parent:
                            found = True
                            current_node = node
                            parent_id = node.id
                            self._node_cache[current_path] = node
                            self.logger.info(f"找到子节点: {part} (父节点信息: {node_parent})")
                            break
            
            # 如果未找到，创建这一级节点
            if not found:
                try:
                    self.logger.info(f"未找到节点 {part}，尝试创建 (父节点ID: {parent_id})")
                    node_info = NodeInfo(
                        value=part,
                        key=part.lower(),
                        parent=parent_id if parent_id else ""
                    )
                    
                    # 根据是否有父节点决定创建方式
                    if parent_id:
                        # 检查是否已存在同名节点，避免重复创建
                        same_name_exists = False
                        for existing_node in all_nodes:
                            if (hasattr(existing_node, 'name') and 
                                existing_node.name.lower() == part.lower() and
                                hasattr(existing_node, 'parent') and
                                isinstance(existing_node.parent, dict) and
                                'id' in existing_node.parent and
                                existing_node.parent['id'] == parent_id):
                                same_name_exists = True
                                current_node = existing_node
                                parent_id = existing_node.id
                                self._node_cache[current_path] = existing_node
                                self.logger.info(f"发现已存在的节点: {part} (ID: {existing_node.id})")
                                break
                                
                        if not same_name_exists:
                            original_parent_id = parent_id
                            new_node = self.js_client.create_node(node_info)
                            if new_node:
                                current_node = new_node
                                parent_id = new_node.id
                                self._node_cache[current_path] = new_node
                                self.logger.info(f"成功创建子节点: {part} (新节点ID: {new_node.id}, 创建时父节点ID: {original_parent_id})")
                            else:
                                self.logger.error(f"创建子节点 {part} 失败")
                                return None
                    else:
                        # 根节点创建
                        new_node = self.js_client.create_node(node_info)
                        if new_node:
                            current_node = new_node
                            parent_id = new_node.id
                            self._node_cache[current_path] = new_node
                            self.logger.info(f"成功创建根节点: {part} (ID: {new_node.id})")
                        else:
                            self.logger.error(f"创建根节点 {part} 失败")
                            return None
                except Exception as e:
                    self.logger.error(f"创建节点 {part} 失败: {str(e)}")
                    
                    # 创建失败，重新获取节点列表再次检查
                    try:
                        all_nodes = self.js_client.get_nodes()
                        for node in all_nodes:
                            if hasattr(node, 'name') and node.name.lower() == part.lower():
                                if i == 0 or parent_id is None:
                                    current_node = node
                                    parent_id = node.id
                                    self._node_cache[current_path] = node
                                    self.logger.info(f"创建失败后找到根节点: {part} (ID: {node.id})")
                                    found = True
                                    break
                                    
                                # 检查父节点
                                if hasattr(node, 'parent'):
                                    node_parent = node.parent
                                    if isinstance(node_parent, dict) and 'id' in node_parent:
                                        node_parent = node_parent.get('id')
                                        
                                    if node_parent == parent_id:
                                        current_node = node
                                        parent_id = node.id
                                        self._node_cache[current_path] = node
                                        self.logger.info(f"创建失败后找到子节点: {part} (ID: {node.id})")
                                        found = True
                                        break
                    except Exception:
                        pass
                        
                    if not found:
                        self.logger.error(f"无法在路径 {current_path} 创建节点")
                        # 返回已创建部分的节点
                        return current_node
        
        # 返回最后找到或创建的节点
        return current_node
        
    def _ensure_platform_node(self, platform: str, region: Optional[str] = None) -> 'NodeInfo':
        """确保平台节点存在并返回，使用三级结构: DEFAULT/类型/名称
        
        Args:
            platform: 云平台名称（如aliyun, huawei等）
            region: 区域名称（弃用参数，保留兼容性）
            
        Returns:
            NodeInfo: 节点信息对象
        """
        # 获取云平台配置信息
        cloud_type = self.cloud_config.get('type', platform)
        cloud_name = self.cloud_config.get('name', 'default')
        
        # 构建缓存键
        cache_key = f"{cloud_type}_{cloud_name}"
        
        # 检查缓存
        if cache_key in self._platform_nodes:
            return self._platform_nodes[cache_key]
            
        self.logger.info(f"获取平台节点: DEFAULT/{cloud_type}/{cloud_name}")
        
        # 查找或创建完整路径
        name_node = self._get_node_by_path(f"DEFAULT/{cloud_type}/{cloud_name}")
        if name_node:
            self.logger.info(f"使用完整路径节点: DEFAULT/{cloud_type}/{cloud_name} (ID: {name_node.id})")
            self._platform_nodes[cache_key] = name_node
            return name_node
            
        # 退一步使用类型节点
        type_node = self._get_node_by_path(f"DEFAULT/{cloud_type}")
        if type_node:
            self.logger.info(f"使用次级路径节点: DEFAULT/{cloud_type} (ID: {type_node.id})")
            self._platform_nodes[cache_key] = type_node
            return type_node
            
        # 最后使用默认节点
        default_node = self._get_node_by_path("DEFAULT")
        if default_node:
            self.logger.info(f"使用DEFAULT节点 (ID: {default_node.id})")
            self._platform_nodes[cache_key] = default_node
            return default_node
            
        self.logger.error("无法获取或创建任何平台节点")
        return None

    def sync_assets(self, assets: List[Dict], platform: str) -> SyncResult:
        """
        同步资产到JumpServer
        
        Args:
            assets: 资产列表
            platform: 云平台名
            
        Returns:
            SyncResult: 同步结果
        """
        if not assets:
            self.logger.info(f"没有需要同步的资产")
            return SyncResult(
                success=True,
                created=0,
                updated=0,
                deleted=0,
                failed=0,
                duration=0
            )
        
        start_time = time.time()
        self.logger.info(f"开始同步{len(assets)} 个资产到JumpServer")
        
        # 重置指标
        self.metrics = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "failed": 0,
            "total": len(assets)
        }
        
        try:
            # 确保平台节点存在
            platform_node = self._ensure_platform_node(platform)
            if not platform_node:
                self.logger.error(f"无法获取或创建平台节点 {platform}")
                return SyncResult(success=False, created=0, updated=0, deleted=0, failed=1, duration=0)
            
            self.logger.info(f"使用平台节点: {platform_node.value} (ID: {platform_node.id})")
            
            # 预处理云平台资产，创建索引
            cloud_assets_by_ip = {}
            cloud_assets_by_instance_id = {}
            
            # 确保所有键都是字符串类型
            for asset in assets:
                ip = asset.get("ip")
                instance_id = asset.get("instance_id")
                
                if ip and isinstance(ip, str):  # 确保IP是字符串类型
                    cloud_assets_by_ip[ip] = asset
                elif ip:
                    self.logger.warning(f"发现非字符串类型的IP: {type(ip)}, 尝试转换")
                    try:
                        ip_str = str(ip)
                        cloud_assets_by_ip[ip_str] = asset
                    except Exception as e:
                        self.logger.error(f"无法将IP转换为字符串: {e}")
                
                if instance_id and isinstance(instance_id, str):  # 确保实例ID是字符串类型
                    cloud_assets_by_instance_id[instance_id] = asset
                elif instance_id:
                    self.logger.warning(f"发现非字符串类型的实例ID: {type(instance_id)}, 尝试转换")
                    try:
                        instance_id_str = str(instance_id)
                        cloud_assets_by_instance_id[instance_id_str] = asset
                    except Exception as e:
                        self.logger.error(f"无法将实例ID转换为字符串: {e}")
            
            # 直接使用安全的集合构建方式
            try:
                cloud_ips = set()
                for ip in cloud_assets_by_ip.keys():
                    if isinstance(ip, (str, int, float, bool, tuple)):
                        cloud_ips.add(ip)
                    else:
                        self.logger.warning(f"跳过不可哈希的IP类型: {type(ip)}")
                        
                cloud_instance_ids = set()
                for instance_id in cloud_assets_by_instance_id.keys():
                    if isinstance(instance_id, (str, int, float, bool, tuple)):
                        cloud_instance_ids.add(instance_id)
                    else:
                        self.logger.warning(f"跳过不可哈希的实例ID类型: {type(instance_id)}")
                        
                self.logger.debug(f"收集到云平台资产IP: {len(cloud_ips)}个，实例ID: {len(cloud_instance_ids)}个")
            except Exception as e:
                self.logger.error(f"构建集合时出错: {e}")
                # 使用空集合作为备选方案
                cloud_ips = set()
                cloud_instance_ids = set()
            
            # 只获取当前节点下的JumpServer资产，并按节点、IP和实例ID进行索引
            self._cache_jumpserver_assets(platform_node.id)
            
            # 处理需要删除的资产（在JumpServer中存在但在云平台中不存在的资产）
            node_assets = self._js_assets_cache.get(platform_node.id, [])
            assets_to_delete = []  # 初始化变量，避免未定义错误
            
            if node_assets:
                self.logger.debug(f"开始查找需要删除的资产，当前节点 {platform_node.value} 下有 {len(node_assets)} 个资产")
                try:
                    assets_to_delete = self._get_assets_to_delete(
                        node_assets, 
                        cloud_ips,
                        cloud_instance_ids,
                        platform
                    )
                except Exception as e:
                    self.logger.error(f"获取需要删除的资产时出错: {e}")
                    assets_to_delete = []  # 发生异常时重置为空列表
            
            # 执行删除资产操作
            if assets_to_delete:
                self.logger.info(f"在节点 {platform_node.value} 下发现 {len(assets_to_delete)} 个需要删除的资产")
                try:
                    self._delete_assets(assets_to_delete)
                except Exception as e:
                    self.logger.error(f"删除资产时出错: {e}")
            
            # 根据缓存的资产信息，判断需要创建的资产
            assets_to_create = []
            skipped_count = 0  # 记录跳过的资产数量
            
            for asset in assets:
                ip = asset.get("ip")
                instance_id = asset.get("instance_id")
                
                if not ip:
                    continue
                    
                normalized_ip = str(ip).strip()
                
                # 原始资产名称
                original_asset_name = (asset.get("hostname") or asset.get("instance_name") or "").strip()
                
                # 直接使用原始资产名称，不进行任何清理
                cleaned_asset_name = ""  # 不再需要清理后的名称
                
                # 通过IP判断是否存在
                exists_by_ip = normalized_ip in self._js_assets_by_ip
                
                # 通过主机名判断是否存在（仅使用原始名称）
                exists_by_name = False
                hostname_lower = original_asset_name.lower() if original_asset_name else ""
                
                js_hostnames_lower = {name.lower() for name in self._js_assets_by_hostname.keys()}
                
                if hostname_lower and hostname_lower in js_hostnames_lower:
                    exists_by_name = True
                    self.logger.debug(f"通过原始名称匹配到资产: {original_asset_name}")
                
                # 通过实例ID判断是否存在
                exists_by_instance_id = False
                if instance_id:
                    exists_by_instance_id = instance_id in self._js_assets_by_instance_id
                    if exists_by_instance_id:
                        self.logger.debug(f"通过实例ID匹配到资产: {instance_id}")
                
                # 综合判断是否需要创建资产
                if not (exists_by_ip or exists_by_name or exists_by_instance_id):
                    # 资产不存在，需要创建
                    assets_to_create.append(asset)
                    self.logger.info(f"资产 {original_asset_name} (IP: {normalized_ip}, 实例ID: {instance_id}) 将被创建")
                else:
                    # 资产已存在，记录日志
                    skipped_count += 1
                    if exists_by_ip:
                        match_type = "IP匹配"
                    elif exists_by_name:
                        match_type = "名称匹配"
                    elif exists_by_instance_id:
                        match_type = "实例ID匹配"
                    else:
                        match_type = "未知匹配"
                    self.logger.info(f"资产 {original_asset_name} (IP: {normalized_ip}, 实例ID: {instance_id}) 已存在({match_type})，跳过创建")
            
            self.logger.info(f"需要创建的资产数: {len(assets_to_create)}，跳过的资产数: {skipped_count}")
            
            # 批量处理资产创建
            if assets_to_create:
                self._process_assets_creation(assets_to_create, platform)
            
            duration = time.time() - start_time
            # 重新计算实际处理的资产总数
            total_processed = self.metrics["created"] + self.metrics["updated"] + self.metrics["deleted"]
            
            success_rate = (self.metrics["created"] + self.metrics["updated"]) / total_processed * 100 if total_processed > 0 else 0
                
            self.logger.info(
                f"同步完成，共处理 {total_processed} 个资产，"
                f"创建: {self.metrics['created']}，"
                f"删除: {self.metrics['deleted']}，"
                f"失败: {self.metrics['failed']}，"
                f"跳过: {skipped_count}，"
                f"成功率: {success_rate:.1f}%，"
                f"耗时: {duration:.2f}秒"
            )
            
            return SyncResult(
                success=True,
                total=total_processed,  # 指定实际处理的资产总数
                created=self.metrics["created"],
                updated=self.metrics["updated"],
                deleted=self.metrics["deleted"],
                failed=self.metrics["failed"],
                duration=duration
            )
            
        except Exception as e:
            self.logger.error(f"同步资产过程中发生错误 {e}")
            # 在异常情况下也计算实际处理的资产总数
            total_processed = self.metrics["created"] + self.metrics["updated"] + self.metrics["deleted"]
            return SyncResult(
                success=False,
                total=total_processed,  # 指定实际处理的资产总数
                created=self.metrics["created"],
                updated=self.metrics["updated"],
                deleted=self.metrics["deleted"],
                failed=self.metrics["failed"],
                duration=time.time() - start_time
            )
    
    def _process_assets_batch(self, assets_batch: List[Dict], platform: str) -> None:
        """
        处理一批资产
        
        Args:
            assets_batch: 资产批次
            platform: 云平台名
        """
        self.logger.warning("_process_assets_batch方法已废弃，请使用_create_assets_batch方法")
    
    def _sync_single_asset(self, asset: Dict, platform: str) -> None:
        """
        同步单个资产 (已废
        
        Args:
            asset: 资产信息
            platform: 云平台名
        """
        self.logger.warning("_sync_single_asset方法已废弃，请使用新的资产同步逻辑")
    
    def _create_assets_batch(self, assets_batch: List[Dict], platform: str) -> None:
        """
        批量创建资产
        
        Args:
            assets_batch: 资产批次
            platform: 云平台名
        """
        if not assets_batch:
            return
            
        self.logger.info(f"开始批量创建 {len(assets_batch)} 个资产")
        
        # 确保平台节点存在
        platform_node = self._ensure_platform_node(platform)
        if not platform_node:
            self.logger.error(f"无法获取或创建平台节点 {platform}")
            return
        
        # 构建资产对象
        asset_list = []
        for asset_data in assets_batch:
            asset_info = self._build_asset_info(asset_data, platform)
            if asset_info:
                # 确保主机名信息被保留
                if not asset_data.get('hostname') and asset_info.name:
                    asset_data['hostname'] = asset_info.name
                asset_list.append((asset_info, asset_data))
        
        if not asset_list:
            self.logger.warning("没有有效资产信息，跳过创建")
            return
            
        # 逐个创建资产
        successful_assets = []
        for asset_info, asset_data in asset_list:
            try:
                # 获取主机名和IP用于日志记录
                hostname = asset_data.get("hostname") or asset_data.get("instance_name", asset_info.name or "unknown")
                ip = asset_data.get("ip", asset_info.ip or "unknown")
                
                self.logger.info(f"创建资产: {hostname} ({ip})")
                result = self.js_client.create_asset(asset_info)
                
                if result:
                    with self._lock:
                        self.metrics["created"] += 1
                        # 记录创建成功的资产用于通知，确保包含主机名信息
                        asset_data_for_notification = asset_data.copy()
                        # 将AssetInfo对象的name属性添加到通知数据中
                        if asset_info.name and not asset_data_for_notification.get('hostname'):
                            asset_data_for_notification['hostname'] = asset_info.name
                        self.created_assets.append(asset_data_for_notification)
                    
                    successful_assets.append(result)
                else:
                    self.logger.warning(f"创建资产可能成功，但返回结果为空: {hostname} ({ip})")
                    with self._lock:
                        self.metrics["created"] += 1
                        # 记录创建成功的资产用于通知
                        asset_data_for_notification = asset_data.copy()
                        if asset_info.name and not asset_data_for_notification.get('hostname'):
                            asset_data_for_notification['hostname'] = asset_info.name
                        self.created_assets.append(asset_data_for_notification)
            except Exception as e:
                hostname = asset_data.get("hostname") or asset_data.get("instance_name", "unknown")
                ip = asset_data.get("ip", "unknown")
                self.logger.error(f"创建资产失败: {hostname} ({ip}), 错误: {e}")
                with self._lock:
                    self.metrics["failed"] += 1
        
        self.logger.info(f"成功创建 {len(successful_assets)} 个资产")
    
    def _build_asset_info(self, asset: Dict[str, Any], platform: str) -> AssetInfo:
        """
        根据资产数据构建AssetInfo对象
        
        Args:
            asset: 资产数据
            platform: 平台类型
            
        Returns:
            AssetInfo: 资产信息对象
        """
        # 确保平台节点存在
        node = self._ensure_platform_node(platform)
        
        # 获取主机名 - 按优先级尝试不同的字段
        # 先尝试直接使用名称字段
        hostname = None
        for key in ['name', 'hostname', 'instance_name']:
            if key in asset and asset[key]:
                hostname = asset[key]
                break
                
        if not hostname:
            # 如果没有名称，使用随机字符串
            hostname = f"unknown-{str(uuid.uuid4())[:8]}"
            self.logger.warning(f"无法从资产数据中获取主机名，使用随机名称: {hostname}，可用字段 {asset.keys()}")
        
        # 保留原始主机名，不进行任何修改
        self.logger.debug(f"使用原始资产名称: '{hostname}'")
        
        # 获取IP地址
        ip = asset.get('private_ip') or asset.get('ip')
        if not ip:
            self.logger.warning(f"资产 {hostname} 没有IP地址")
            ip = "0.0.0.0"  # 使用一个默认IP
        
        # 获取公网IP
        public_ip = asset.get('public_ip') or ""
        
        # 确定平台类型
        if 'os_type' in asset and asset['os_type']:
            platform_type = asset['os_type'].lower()
            # 标准化操作系统类型
            if 'win' in platform_type:
                platform_type = 'windows'
            else:
                platform_type = 'linux'
            self.logger.debug(f"使用资产中的操作系统类型: {platform_type}")
        else:
            # 使用备选方法判断平台类型
            platform_type = self._determine_platform_type(asset)
            self.logger.debug(f"通过辅助判断确定操作系统类型: {platform_type}")
        
        # 确定协议和端口
        if platform_type == 'windows':
            protocol = "rdp"
            port = 3389
        else:
            protocol = "ssh"
            port = 22
            
        self.logger.info(f"资产 {hostname} 平台类型: {platform_type}, 将使用协议: {protocol}, 端口: {port}")
        
        # 添加注释
        comment_parts = [f"由JMS-Sync同步{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        
        for key in ["instance_id", "instance_type", "region", "vpc_id"]:
            if asset.get(key):
                comment_parts.append(f"{key}: {asset.get(key)}")
        
        comment = "\n".join(comment_parts)
        
        # 获取domain_id
        domain_id = self.cloud_config.get('domain_id') if hasattr(self, 'cloud_config') and self.cloud_config else None
        
        # 添加日志，记录domain_id的获取情况
        if domain_id:
            self.logger.debug(f"从cloud_config获取到domain_id: {domain_id}")
        else:
            self.logger.debug("未找到domain_id或cloud_config不存在")
            
        # 根据平台类型选择不同的账号模板
        accounts = []
        if platform_type == 'windows':
            # Windows系统账号模板
            jumpserver_config = self.js_client.config if hasattr(self.js_client, 'config') else {}
            account_templates = jumpserver_config.get('account_templates', {})
            windows_template = account_templates.get('windows')
            if windows_template:
                accounts = [{
                    "template": windows_template,
                    "name": "Windows",
                    "username": "",
                    "secret_type": "password",
                    "privileged": False,
                    "secret": ""
                }]
                self.logger.debug(f"使用Windows账号模板: {windows_template}")
            else:
                self.logger.warning("未找到Windows账号模板配置，将创建无账号资产")
        else:
            # Linux系统账号模板
            jumpserver_config = self.js_client.config if hasattr(self.js_client, 'config') else {}
            account_templates = jumpserver_config.get('account_templates', {})
            linux_template = account_templates.get('linux')
            if linux_template:
                accounts = [{
                    "template": linux_template,
                    "name": "ROOT",
                    "username": "root",
                    "secret_type": "password",
                    "privileged": True,
                    "secret": ""
                }]
                self.logger.debug(f"使用Linux账号模板: {linux_template}")
            else:
                self.logger.warning("未找到Linux账号模板配置，将创建无账号资产")
            
        # 创建AssetInfo对象
        asset_info = AssetInfo(
            name=hostname,
            ip=ip,
            platform=platform_type,
            protocol=protocol,
            port=port,
            is_active=True,
            public_ip=public_ip,
            node_id=node.id,
            comment=comment,
            domain_id=domain_id,
            accounts=accounts  # 添加accounts字段
        )
        
        # 记录最终创建的AssetInfo对象信息
        self.logger.debug(f"构建资产信息: 名称={hostname}, IP={ip}, 平台={platform_type}, 协议={protocol}, 端口={port}, domain_id={domain_id}")
        
        # 记录实例ID信息（如果有）
        if asset.get('instance_id'):
            self.logger.debug(f"资产实例ID: {asset.get('instance_id')}")
        
        return asset_info
    
    def _cache_jumpserver_assets(self, node_id: str) -> None:
        """
        缓存JumpServer资产，按节点、IP、主机名和实例ID进行索引
        
        Args:
            node_id: 节点ID
        """
        # 获取特定节点下的资产，而不是所有资产
        self.logger.info(f"获取节点 {node_id} 下的JumpServer资产")
        js_assets = self.js_client.get_assets_by_node(node_id)
        self.logger.debug(f"获取到节点 {node_id} 下的资产: {len(js_assets)}个")
        
        # 清空缓存
        self._js_assets_cache = {}
        self._js_assets_by_ip = {}
        self._js_assets_by_hostname = {}
        self._js_assets_by_instance_id = {}
        
        # 按节点ID索引资产
        indexed_assets_count = 0
        for asset in js_assets:
            # 获取资产节点ID，兼容 dict 或对象
            if isinstance(asset, dict):
                asset_node_id = asset.get('node') or asset.get('node_id')
            else:
                asset_node_id = getattr(asset, 'node', None) or getattr(asset, 'node_id', None)
            
            # 如果 asset_node_id 是 dict 类型，则转换为字符串
            if asset_node_id and isinstance(asset_node_id, dict):
                asset_node_id = str(asset_node_id)
            
            if not asset_node_id:
                continue
            
            # 按节点缓存资产
            if asset_node_id not in self._js_assets_cache:
                self._js_assets_cache[asset_node_id] = []
            self._js_assets_cache[asset_node_id].append(asset)
            indexed_assets_count += 1
            
            # 按IP缓存资产，确保 key 为 hashable 类型，兼容 dict 或对象
            if isinstance(asset, dict):
                ip_value = asset.get('ip')
            else:
                ip_value = getattr(asset, 'ip', None)

            if ip_value:
                if isinstance(ip_value, dict):
                    ip_value = str(ip_value)
                self._js_assets_by_ip[ip_value] = asset
            
            # 按主机名缓存资产，兼容 dict 或对象
            if isinstance(asset, dict):
                name_value = asset.get('name')
            else:
                name_value = getattr(asset, 'name', None)

            if name_value:
                # 简单地缓存资产名称，不进行任何推断或转换
                self._js_assets_by_hostname[name_value] = asset
                
                # 不再尝试推断原始名称或添加变体
                
            # 提取实例ID并按实例ID缓存资产
            if isinstance(asset, dict):
                comment_value = asset.get('comment')
            else:
                comment_value = getattr(asset, 'comment', None)

            if comment_value:
                instance_id = self._extract_instance_id_from_comment(comment_value)
                if instance_id:
                    self._js_assets_by_instance_id[instance_id] = asset
        
        self.logger.debug(f"成功索引 {indexed_assets_count} 个资产")
        self.logger.debug(f"IP索引: {len(self._js_assets_by_ip)}个, 名称索引: {len(self._js_assets_by_hostname)}个, 实例ID索引: {len(self._js_assets_by_instance_id)}个")
    
    def _extract_instance_id_from_comment(self, comment: str) -> Optional[str]:
        """
        从资产注释中提取实例ID
        
        Args:
            comment: 资产注释
            
        Returns:
            Optional[str]: 实例ID，如果没有则返回None
        """
        if not comment:
            return None
            
        # 匹配更多可能的实例ID格式
        for line in comment.split("\n"):
            # 匹配以下格式：
            # instance_id: i-xxxxxx
            # instance_id：i-xxxxxx (中文冒号)
            # instance id: i-xxxxxx
            # 实例ID: i-xxxxxx
            if any(pattern in line.lower() for pattern in ["instance_id:", "instance_id：", "instance id:", "实例id:", "实例id："]):
                parts = re.split(r'[:]', line, 1)
                if len(parts) > 1:
                    instance_id = parts[1].strip()
                    self.logger.debug(f"从注释中提取到实例ID: {instance_id}")
                    return instance_id
        
        return None
    
    def _get_assets_to_delete(self, js_assets: List[Any], cloud_ips: set, cloud_instance_ids: set, platform: str) -> List[Any]:
        """
        获取需要删除的资产列表
        
        Args:
            js_assets: JumpServer资产列表
            cloud_ips: 云平台资产IP集合
            cloud_instance_ids: 云平台资产实例ID集合
            platform: 云平台名称
            
        Returns:
            List[Any]: 需要删除的资产列表
        """
        assets_to_delete = []
        
        # 确保cloud_ips和cloud_instance_ids是集合类型
        if not isinstance(cloud_ips, set):
            self.logger.warning("cloud_ips不是集合类型，尝试转换")
            try:
                cloud_ips = set(cloud_ips)
            except Exception as e:
                self.logger.error(f"转换cloud_ips为集合类型失败: {e}")
                cloud_ips = set()
                
        if not isinstance(cloud_instance_ids, set):
            self.logger.warning("cloud_instance_ids不是集合类型，尝试转换")
            try:
                cloud_instance_ids = set(cloud_instance_ids)
            except Exception as e:
                self.logger.error(f"转换cloud_instance_ids为集合类型失败: {e}")
                cloud_instance_ids = set()
        
        for js_asset in js_assets:
            try:
                # 检查资产注释中是否包含平台信息
                asset_comment = js_asset.comment if hasattr(js_asset, 'comment') else ""
                if platform.lower() not in asset_comment.lower() and f"{platform}云".lower() not in asset_comment.lower():
                    continue  # 注释中不包含平台信息，可能不是由本系统创建的资产
                
                # 检查资产是否在云平台中存在（通过IP和实例ID）
                asset_ip = js_asset.ip if hasattr(js_asset, 'ip') else ""
                if asset_ip and isinstance(asset_ip, str):
                    asset_ip = asset_ip.strip()
                
                # 提取实例ID
                instance_id = self._extract_instance_id_from_comment(asset_comment)
                
                # 转换为字符串并检查类型，避免不可哈希的问题
                if isinstance(asset_ip, dict) or isinstance(instance_id, dict):
                    self.logger.warning(f"发现不可哈希的类型: asset_ip={type(asset_ip)}, instance_id={type(instance_id)}")
                    # 尝试转换为字符串
                    if isinstance(asset_ip, dict):
                        asset_ip = str(asset_ip)
                    if isinstance(instance_id, dict):
                        instance_id = str(instance_id)
                
                # 如果既不匹配IP也不匹配实例ID，则需要删除
                try:
                    ip_in_set = asset_ip in cloud_ips
                except Exception as e:
                    self.logger.error(f"检查IP是否在集合中时出错: {e}")
                    ip_in_set = False
                    
                try:
                    id_in_set = instance_id in cloud_instance_ids if instance_id else False
                except Exception as e:
                    self.logger.error(f"检查实例ID是否在集合中时出错: {e}")
                    id_in_set = False
                
                if not ip_in_set and (not instance_id or not id_in_set):
                    assets_to_delete.append(js_asset)
                    self.logger.info(f"资产{js_asset.name} (IP: {asset_ip})不在云平台中，将被删除")
            except Exception as e:
                asset_id = js_asset.id if hasattr(js_asset, 'id') else "未知"
                self.logger.error(f"检查资产是否需要删除时出错，资产ID: {asset_id}, 错误: {e}")
                # 继续检查下一个资产
        
        return assets_to_delete
    
    def _delete_assets(self, assets: List[Any]) -> None:
        """
        删除资产
        
        Args:
            assets: 资产列表
        """
        if not assets:
            return
            
        self.logger.info(f"发现 {len(assets)} 个需要删除的资产")
        
        # 检查assets参数是否为列表
        if not isinstance(assets, list):
            self.logger.warning(f"assets参数不是列表类型: {type(assets)}")
            try:
                assets = list(assets)
                self.logger.info(f"成功将assets转换为列表，包含{len(assets)}个元素")
            except Exception as e:
                self.logger.error(f"将assets转换为列表失败: {e}")
                return
        
        # 记录要删除的资产
        with self._lock:
            self.deleted_assets = assets.copy()
        
        # 逐个删除资产
        for asset in assets:
            try:
                asset_id = asset.id if hasattr(asset, 'id') else asset.get("id")
                asset_name = asset.name if hasattr(asset, 'name') else asset.get("name")
                asset_ip = asset.ip if hasattr(asset, 'ip') else asset.get("ip")
                
                if not asset_id:
                    self.logger.warning(f"无法删除资产，找不到资产ID: {asset_name} ({asset_ip})")
                    continue
                    
                self.logger.info(f"删除资产: {asset_name} ({asset_ip})")
                self.js_client.delete_asset(asset_id)
                with self._lock:
                    self.metrics["deleted"] += 1
            except Exception as e:
                try:
                    asset_name = getattr(asset, 'name', None) if hasattr(asset, '__dict__') else None
                    if asset_name is None and isinstance(asset, dict):
                        asset_name = asset.get("name", "未知")
                    else:
                        asset_name = "未知"
                        
                    asset_ip = getattr(asset, 'ip', None) if hasattr(asset, '__dict__') else None
                    if asset_ip is None and isinstance(asset, dict):
                        asset_ip = asset.get("ip", "未知")
                    else:
                        asset_ip = "未知"
                    
                    self.logger.error(f"删除资产失败: {asset_name} ({asset_ip}), 错误: {e}")
                except Exception as inner_e:
                    self.logger.error(f"处理删除资产错误信息时出错: {inner_e}，原始错误: {e}")
                
                with self._lock:
                    self.metrics["failed"] += 1
    
    def _process_assets_creation(self, assets: List[Dict], platform: str) -> None:
        """
        批量处理资产创建
        
        Args:
            assets: 资产列表
            platform: 云平台名
        """
        self.logger.info(f"开始创建{len(assets)} 个资产")
        
        # 如果资产数量较少，直接创建
        if len(assets) <= self.batch_size:
            self._create_assets_batch(assets, platform)
        else:
            # 分批处理资产创建
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                futures = []
                
                # 按批次提交任务
                for i in range(0, len(assets), self.batch_size):
                    batch = assets[i:i+self.batch_size]
                    future = executor.submit(self._create_assets_batch, batch, platform)
                    futures.append(future)
                
                # 等待所有任务完成
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        self.logger.error(f"创建资产批次时出错: {e}")
                        with self._lock:
                            self.metrics["failed"] += 1
                