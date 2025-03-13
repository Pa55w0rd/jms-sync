#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
阿里云客户端 - 负责与阿里云API交互，使用阿里云SDK获取主机信息
"""

import logging
import json
import time
from typing import Dict, List, Tuple, Any, Optional

# 导入阿里云SDK
from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient
from Tea.exceptions import TeaException

from jms_sync.cloud.base import CloudBase
from jms_sync.utils.exceptions import AliyunError

class AliyunCloud(CloudBase):
    """阿里云客户端类"""
    
    def __init__(self, access_key_id: str, access_key_secret: str, region: str):
        """
        初始化阿里云客户端
        
        Args:
            access_key_id: 访问密钥ID
            access_key_secret: 访问密钥密钥
            region: 区域ID
        """
        super().__init__(access_key_id, access_key_secret, region)
        self.logger.info(f"初始化阿里云客户端: 区域={region}")
        self.client = self.get_client()
        
    def get_client(self) -> EcsClient:
        """
        获取阿里云ECS客户端
        
        Returns:
            EcsClient: 阿里云ECS客户端
            
        Raises:
            AliyunError: 获取客户端失败时抛出异常
        """
        try:
            # 创建配置
            self.logger.debug(f"创建阿里云配置: AK={self.access_key_id[:4]}***, 区域={self.region}")
            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret
            )
            # 设置区域端点
            endpoint = f'ecs.{self.region}.aliyuncs.com'
            self.logger.debug(f"设置阿里云区域端点: {endpoint}")
            config.endpoint = endpoint
            
            # 创建客户端
            self.logger.debug(f"创建阿里云ECS客户端")
            return EcsClient(config)
        except TeaException as e:
            error_msg = f"创建阿里云ECS客户端失败: {e.message}"
            self.logger.error(error_msg)
            raise AliyunError(error_msg)
        except Exception as e:
            error_msg = f"创建阿里云ECS客户端失败: {str(e)}"
            self.logger.error(error_msg)
            raise AliyunError(error_msg)
    
    def get_instances(self) -> List[Dict]:
        """
        获取指定区域的所有实例
        
        Returns:
            List[Dict]: 实例列表
            
        Raises:
            AliyunError: 获取实例失败时抛出异常
        """
        try:
            # 创建请求
            self.logger.debug(f"创建阿里云ECS实例列表请求: 区域={self.region}")
            request = ecs_models.DescribeInstancesRequest(
                region_id=self.region,
                page_size=100  # 每页最大数量
            )
            
            # 创建运行时选项
            runtime = util_models.RuntimeOptions()
            
            # 获取实例总数
            self.logger.debug(f"获取阿里云ECS实例总数: 区域={self.region}")
            response = self.client.describe_instances_with_options(request, runtime)
            total_count = response.body.total_count
            self.logger.debug(f"阿里云ECS实例总数: {total_count}")
            
            # 计算分页数量
            page_count = (total_count + 99) // 100
            self.logger.debug(f"阿里云ECS实例分页数量: {page_count}")
            
            # 获取所有实例
            all_instances = []
            for page_num in range(1, page_count + 1):
                self.logger.debug(f"获取阿里云ECS实例列表: 区域={self.region}, 页码={page_num}/{page_count}")
                request.page_number = page_num
                response = self.client.describe_instances_with_options(request, runtime)
                instances = response.body.instances.instance
                
                self.logger.debug(f"获取到阿里云ECS实例: 区域={self.region}, 页码={page_num}, 数量={len(instances)}")
                
                # 将实例添加到列表中
                for instance in instances:
                    try:
                        # 转换为字典
                        instance_dict = {
                            'instance_id': getattr(instance, 'instance_id', ''),
                            'name': getattr(instance, 'instance_name', ''),
                            'status': getattr(instance, 'status', ''),
                            'vpc_id': getattr(instance.vpc_attributes, 'vpc_id', '') if hasattr(instance, 'vpc_attributes') else '',
                            'private_ip': instance.vpc_attributes.private_ip_address.ip_address[0] if hasattr(instance, 'vpc_attributes') and hasattr(instance.vpc_attributes, 'private_ip_address') and instance.vpc_attributes.private_ip_address and instance.vpc_attributes.private_ip_address.ip_address else None,
                            'public_ip': instance.public_ip_address.ip_address[0] if hasattr(instance, 'public_ip_address') and instance.public_ip_address and instance.public_ip_address.ip_address else None,
                            'os_name': getattr(instance, 'os_name', ''),
                            'os_type': getattr(instance, 'os_type', ''),
                            'region': getattr(instance, 'region_id', self.region),
                            'zone': getattr(instance, 'zone_id', ''),
                            'instance_type': getattr(instance, 'instance_type', ''),
                            'creation_time': getattr(instance, 'creation_time', '')
                        }
                        all_instances.append(instance_dict)
                    except Exception as e:
                        self.logger.warning(f"处理阿里云实例信息失败: {str(e)}, 实例ID: {getattr(instance, 'instance_id', 'unknown')}")
                        continue
            
            self.logger.info(f"获取阿里云ECS实例成功: 区域={self.region}, 总数={len(all_instances)}")
            return all_instances
        except TeaException as e:
            error_msg = f"获取阿里云实例失败: Error: {e.code} code: {e.status_code}, {e.message} request id: {e.request_id} Response: {e.data}"
            self.logger.error(error_msg)
            raise AliyunError(error_msg)
        except Exception as e:
            error_msg = f"获取阿里云实例失败: {str(e)}"
            self.logger.error(error_msg)
            raise AliyunError(error_msg)
    
    def determine_os_type(self, instance: Dict) -> str:
        """
        根据实例信息确定操作系统类型
        
        Args:
            instance: 实例信息
            
        Returns:
            str: 操作系统类型，'Windows' 或 'Linux'
        """
        # 首先检查os_type字段
        os_type = instance.get('os_type', '').lower()
        if os_type == 'windows':
            return 'Windows'
        
        # 然后检查os_name字段
        os_name = instance.get('os_name', '').lower()
        if 'windows' in os_name:
            return 'Windows'
        
        # 最后检查实例名称
        instance_name = instance.get('name', '').lower()
        if 'win' in instance_name:
            return 'Windows'
        
        # 默认为Linux
        return 'Linux' 