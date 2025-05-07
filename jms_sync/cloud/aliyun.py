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

from jms_sync.utils.exceptions import AliyunError
from jms_sync.utils.logger import get_logger

class AliyunCloud:
    """阿里云客户端类"""
    
    def __init__(self, access_key_id: str, access_key_secret: str, region: str):
        """
        初始化阿里云客户端
        
        Args:
            access_key_id: 访问密钥ID
            access_key_secret: 访问密钥密钥
            region: 区域ID
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.region = region
        self.logger = get_logger(self.__class__.__name__)
        self.logger.info(f"初始化阿里云客户端: 区域={region}")
        self.client = self.get_client()
        
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
            self.logger.info(f"获取阿里云ECS实例列表: 区域={self.region}")
            # 设置分页大小为25
            page_size = 25
            request = ecs_models.DescribeInstancesRequest(
                region_id=self.region,
                page_size=page_size  # 每页数量设置为25
            )
            
            # 创建运行时选项
            runtime = util_models.RuntimeOptions()
            
            # 获取实例总数
            self.logger.debug(f"获取阿里云ECS实例总数: 区域={self.region}")
            total_count = 0
            try:
                response = self.client.describe_instances_with_options(request, runtime)
                total_count = response.body.total_count
                self.logger.debug(f"阿里云ECS实例总数: {total_count}")
            except TeaException as e:
                # 处理API错误
                self.logger.error(f"获取阿里云ECS实例总数失败: {e.message}")
                if "Throttling" in e.message or "QPS" in e.message:
                    # 限流错误，等待后重试
                    self.logger.warning("阿里云API限流，等待5秒后重试")
                    time.sleep(5)
                    try:
                        response = self.client.describe_instances_with_options(request, runtime)
                        total_count = response.body.total_count
                    except Exception as retry_e:
                        self.logger.error(f"重试获取阿里云ECS实例总数失败: {str(retry_e)}")
                        return []  # 返回空列表
                else:
                    self.logger.error(f"获取阿里云ECS实例总数失败，无法继续: {e.message}")
                    return []  # 返回空列表
            except Exception as e:
                self.logger.error(f"获取阿里云ECS实例总数时发生未知错误: {str(e)}")
                return []  # 返回空列表
            
            # 计算分页数量
            page_count = (total_count + page_size - 1) // page_size if total_count > 0 else 0
            self.logger.debug(f"阿里云ECS实例分页数量: {page_count}")
            
            # 如果总数为0，直接返回空列表
            if total_count == 0 or page_count == 0:
                self.logger.warning(f"阿里云区域 {self.region} 没有任何实例")
                return []
            
            # 获取所有实例
            all_instances = []
            for page_num in range(1, page_count + 1):
                retry_count = 0
                max_retries = 3
                while retry_count < max_retries:
                    try:
                        self.logger.debug(f"获取阿里云ECS实例列表: 区域={self.region}, 页码={page_num}/{page_count}, 每页数量={page_size}")
                        request.page_number = page_num
                        response = self.client.describe_instances_with_options(request, runtime)
                        instances = response.body.instances.instance
                        
                        current_batch = len(instances)
                        self.logger.debug(f"获取到阿里云ECS实例: 区域={self.region}, 页码={page_num}, 当前批次数量={current_batch}, 累计数量={len(all_instances) + current_batch}")
                        
                        # 将实例添加到列表中
                        for instance in instances:
                            try:
                                # 获取私有IP
                                private_ip = None
                                if hasattr(instance, 'vpc_attributes') and hasattr(instance.vpc_attributes, 'private_ip_address') and instance.vpc_attributes.private_ip_address and instance.vpc_attributes.private_ip_address.ip_address:
                                    private_ip = instance.vpc_attributes.private_ip_address.ip_address[0]
                                
                                # 获取公网IP
                                public_ip = None
                                if hasattr(instance, 'public_ip_address') and instance.public_ip_address and instance.public_ip_address.ip_address:
                                    public_ip = instance.public_ip_address.ip_address[0]
                                
                                # 转换为字典
                                instance_dict = {
                                    'instance_id': getattr(instance, 'instance_id', ''),
                                    'name': getattr(instance, 'instance_name', ''),
                                    'hostname': getattr(instance, 'host_name', ''),
                                    'status': getattr(instance, 'status', ''),
                                    'vpc_id': getattr(instance.vpc_attributes, 'vpc_id', '') if hasattr(instance, 'vpc_attributes') else '',
                                    'private_ip': private_ip,
                                    'public_ip': public_ip,
                                    'ip': private_ip or public_ip,  # 优先使用私有IP
                                    'os_name': getattr(instance, 'os_name', ''),
                                    'os_type': 'Windows' if 'windows' in getattr(instance, 'os_name', '').lower() else 'Linux',
                                    'region': getattr(instance, 'region_id', self.region),
                                    'zone': getattr(instance, 'zone_id', ''),
                                    'instance_type': getattr(instance, 'instance_type', ''),
                                    'creation_time': getattr(instance, 'creation_time', ''),
                                    'total_count': total_count  # 添加总数信息
                                }
                                
                                # 实例ID是必须的，如果没有则跳过
                                instance_id = instance_dict.get('instance_id', '')
                                if not instance_id:
                                    self.logger.warning(f"跳过没有ID的实例")
                                    continue
                                
                                # 如果没有IP，跳过
                                if not instance_dict.get('ip'):
                                    self.logger.warning(f"实例 {instance_id} 没有可用的IP地址，跳过")
                                    continue
                                    
                                all_instances.append(instance_dict)
                            except Exception as e:
                                instance_id = getattr(instance, 'instance_id', 'unknown') if hasattr(instance, 'instance_id') else 'unknown'
                                self.logger.error(f"处理阿里云实例信息失败: {str(e)}, 实例ID: {instance_id}")
                                continue
                                
                        # 分页请求之间添加适当的延迟，避免触发限流
                        if page_num < page_count:
                            time.sleep(0.5)
                            
                        # 成功获取数据，跳出重试循环
                        break
                    except TeaException as e:
                        retry_count += 1
                        # 处理API错误
                        self.logger.warning(f"获取阿里云ECS实例列表失败(第{retry_count}次重试): 区域={self.region}, 页码={page_num}, 错误={e.message}")
                        if "Throttling" in e.message or "QPS" in e.message:
                            # 限流错误，等待后重试
                            wait_time = 5 * retry_count
                            self.logger.warning(f"阿里云API限流，等待{wait_time}秒后重试")
                            time.sleep(wait_time)
                        elif retry_count < max_retries:
                            # 其他错误，等待后重试
                            time.sleep(2 * retry_count)
                        else:
                            # 达到最大重试次数
                            self.logger.error(f"获取阿里云ECS实例列表达到最大重试次数: 区域={self.region}, 页码={page_num}")
                            # 继续下一页，尽可能获取更多数据
                            break
                    except Exception as e:
                        retry_count += 1
                        self.logger.warning(f"获取阿里云ECS实例列表失败(第{retry_count}次重试): 区域={self.region}, 页码={page_num}, 错误={str(e)}")
                        if retry_count < max_retries:
                            time.sleep(2 * retry_count)
                        else:
                            # 达到最大重试次数
                            self.logger.error(f"获取阿里云ECS实例列表达到最大重试次数: 区域={self.region}, 页码={page_num}")
                            # 继续下一页，尽可能获取更多数据
                            break
            
            self.logger.info(f"阿里云ECS实例列表获取完成: 区域={self.region}, 实例数量={len(all_instances)}")
            return all_instances
        except Exception as e:
            error_msg = f"获取阿里云ECS实例列表失败: 区域={self.region}, 错误={str(e)}"
            self.logger.error(error_msg)
            # 返回空列表而不是抛出异常，以便后续处理可以继续
            return []