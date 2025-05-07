#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
华为云客户端 - 负责与华为云API交互，使用华为云SDK获取主机信息
"""

import logging
import json
import time
from typing import Dict, List, Tuple, Any, Optional

# 导入华为云SDK
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkecs.v2 import *

from jms_sync.utils.exceptions import HuaweiError
from jms_sync.utils.logger import get_logger

class HuaweiCloud:
    """华为云客户端类"""
    
    def __init__(self, access_key_id: str, access_key_secret: str, project_id: str, region: str):
        """
        初始化华为云客户端
        
        Args:
            access_key_id: 访问密钥ID (AK)
            access_key_secret: 访问密钥密钥 (SK)
            project_id: 项目ID
            region: 区域ID
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.project_id = project_id
        self.region = region
        self.logger = get_logger(self.__class__.__name__)
        self.logger.info(f"初始化华为云客户端: 区域={region}, 项目ID={project_id}")
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
        获取华为云ECS客户端
        
        Returns:
            EcsClient: 华为云ECS客户端
            
        Raises:
            HuaweiError: 获取客户端失败时抛出异常
        """
        try:
            # 创建认证
            self.logger.debug(f"创建华为云认证: AK={self.access_key_id[:4]}***, 区域={self.region}, 项目ID={self.project_id}")
            
            # 使用AK/SK和project_id创建认证对象
            credentials = BasicCredentials(
                ak=self.access_key_id,
                sk=self.access_key_secret,
                project_id=self.project_id
            )
            
            # 尝试使用标准区域方式创建客户端
            try:
                # 创建ECS客户端实例
                self.logger.debug(f"创建华为云ECS客户端: 区域={self.region}")
                
                # 使用区域对象
                client = EcsClient.new_builder() \
                    .with_credentials(credentials) \
                    .with_region(EcsRegion.value_of(self.region)) \
                    .build()
            except Exception as e:
                self.logger.warning(f"使用标准区域方式创建客户端失败: {str(e)}，将使用直接构造方式")
                
                # 使用直接构造方式
                endpoint = f"https://ecs.{self.region}.myhuaweicloud.com"
                self.logger.debug(f"使用直接构造方式创建华为云ECS客户端: 区域={self.region}, 端点={endpoint}")
                
                client = EcsClient.new_builder() \
                    .with_credentials(credentials) \
                    .with_endpoint(endpoint) \
                    .build()
                
            return client
        except exceptions.ClientRequestException as e:
            error_msg = f"创建华为云ECS客户端失败: {e.error_msg}, 状态码: {e.status_code}, 错误码: {e.error_code}"
            self.logger.error(error_msg)
            raise HuaweiError(error_msg)
        except Exception as e:
            error_msg = f"创建华为云ECS客户端失败: {str(e)}"
            self.logger.error(error_msg)
            raise HuaweiError(error_msg)
            
    def get_instances(self) -> List[Dict]:
        """
        获取指定区域的所有实例
        
        Returns:
            List[Dict]: 实例列表
            
        Raises:
            HuaweiError: 获取实例失败时抛出异常
        """
        try:
            self.logger.info(f"获取华为云ECS实例列表: 区域={self.region}")
            
            # 设置分页大小为25（合理值，减少请求次数但不会太大）
            page_size = 25
            
            # 获取实例数据并进行分页处理
            all_instances = []
            offset = 1
            
            while True:
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries:
                    try:
                        # 创建请求对象
                        request = ListServersDetailsRequest(
                            limit=page_size,
                            offset=offset
                        )
                        
                        self.logger.debug(f"请求华为云ECS实例: 区域={self.region}, 页码={offset}, 页大小={page_size}")
                        
                        # 调用API获取实例列表
                        response = self.client.list_servers_details(request)
                        
                        # 解析返回数据
                        total_count = getattr(response, 'count', 0)
                        servers = getattr(response, 'servers', [])
                        
                        self.logger.debug(f"华为云ECS实例总数: {total_count}")
                        # 总页数
                        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
                        self.logger.debug(f"华为云ECS实例预估总页数: {total_pages}")
                        
                        # 如果没有数据或返回为空，退出循环
                        if not servers:
                            self.logger.debug(f"当前页无实例数据，获取完成")
                            break
                            
                        self.logger.debug(f"获取到实例数据: 页码={offset}, 当前页数量={len(servers)}, 已获取总数={len(all_instances) + len(servers)}")
                        
                        # 处理实例数据
                        for server in servers:
                            try:
                                # 将server对象转换为字典
                                server_dict = {}
                                for attr in dir(server):
                                    if not attr.startswith('_') and not callable(getattr(server, attr)):
                                        try:
                                            server_dict[attr] = getattr(server, attr)
                                        except Exception:
                                            pass
                                
                                # 获取网络信息 - 优先提取私有IP
                                private_ip = None
                                public_ip = None
                                addresses = server_dict.get('addresses', {})
                                
                                for network_name, address_list in addresses.items():
                                    for address in address_list:
                                        if isinstance(address, dict):
                                            addr_type = address.get('OS-EXT-IPS:type', '')
                                            addr = address.get('addr', '')
                                            if addr_type == "fixed" or not addr_type:
                                                # 如果是固定IP或没有类型，判断是否是私有IP
                                                if addr and (addr.startswith('10.') or addr.startswith('172.') or addr.startswith('192.168.')):
                                                    private_ip = addr
                                                elif not private_ip:  # 没有明确是私有IP，但也没有其他私有IP
                                                    private_ip = addr
                                            elif addr_type == "floating":
                                                public_ip = addr
                                        else:
                                            # 处理对象格式
                                            addr_type = getattr(address, 'OS-EXT-IPS:type', '')
                                            addr = getattr(address, 'addr', '')
                                            if addr_type == "fixed" or not addr_type:
                                                if addr and (addr.startswith('10.') or addr.startswith('172.') or addr.startswith('192.168.')):
                                                    private_ip = addr
                                                    
                                # 添加区域信息
                                server_dict['region'] = self.region
                                
                                # 标准化实例ID和名称
                                server_dict['instance_id'] = server_dict.get('id', '')
                                server_dict['instance_name'] = server_dict.get('name', '')
                                
                                # 标准化操作系统类型
                                os_name = ''
                                if 'metadata' in server_dict and isinstance(server_dict['metadata'], dict):
                                    os_name = server_dict['metadata'].get('os_type', '')
                                
                                if not os_name and 'metadata' in server_dict and isinstance(server_dict['metadata'], dict):
                                    image_name = server_dict['metadata'].get('image_name', '').lower()
                                    if 'windows' in image_name:
                                        os_name = 'Windows'
                                    elif any(linux_name in image_name for linux_name in ['linux', 'ubuntu', 'centos', 'debian']):
                                        os_name = 'Linux'
                                
                                if not os_name:
                                    # 从名称中判断
                                    instance_name = server_dict.get('name', '').lower()
                                    if 'win' in instance_name:
                                        os_name = 'Windows'
                                    else:
                                        # 默认为Linux
                                        os_name = 'Linux'
                                
                                server_dict['os_type'] = os_name
                                
                                # 添加IP信息
                                if private_ip:
                                    server_dict['private_ip'] = private_ip
                                    server_dict['ip'] = private_ip  # 使用标准字段名
                                    server_dict['address'] = private_ip  # 使用标准字段名
                                if public_ip:
                                    server_dict['public_ip'] = public_ip
                                    # 如果没有私有IP则使用公有IP
                                    if not private_ip:
                                        server_dict['ip'] = public_ip
                                        server_dict['address'] = public_ip
                                
                                # 如果没有获取到IP，记录并跳过
                                if not private_ip and not public_ip:
                                    instance_id = server_dict.get('id', 'unknown')
                                    self.logger.warning(f"实例 {instance_id} 没有可用的IP地址，跳过")
                                    continue
                                
                                all_instances.append(server_dict)
                            except Exception as e:
                                instance_id = getattr(server, 'id', 'unknown') if hasattr(server, 'id') else 'unknown'
                                self.logger.error(f"处理实例数据失败: 实例ID={instance_id}, 错误={str(e)}")
                                # 继续处理下一个实例，不抛出异常
                        
                        # 请求成功，跳出重试循环
                        break
                    except exceptions.ClientRequestException as e:
                        retry_count += 1
                        self.logger.warning(f"请求华为云ECS实例失败(第{retry_count}次尝试): 区域={self.region}, 页码={offset}, 错误={e.error_msg}, 状态码={e.status_code}")
                        if retry_count >= max_retries:
                            self.logger.error(f"请求华为云ECS实例达到最大重试次数: 区域={self.region}, 页码={offset}")
                            # 不抛出异常，继续下一页，尽量获取更多数据
                            break
                        time.sleep(2 * retry_count)  # 指数退避
                    except Exception as e:
                        retry_count += 1
                        self.logger.warning(f"请求华为云ECS实例失败(第{retry_count}次尝试): 区域={self.region}, 页码={offset}, 错误={str(e)}")
                        if retry_count >= max_retries:
                            self.logger.error(f"请求华为云ECS实例达到最大重试次数: 区域={self.region}, 页码={offset}")
                            # 不抛出异常，继续下一页，尽量获取更多数据
                            break
                        time.sleep(2 * retry_count)  # 指数退避
                
                # 处理下一页
                offset += 1
                
                # 如果当前页没有数据或已经获取完所有页，退出循环
                if not servers or (total_count > 0 and len(all_instances) >= total_count):
                    self.logger.debug(f"已获取所有实例数据，总数: {len(all_instances)}")
                    break
            
            self.logger.info(f"华为云ECS实例列表获取完成: 区域={self.region}, 实例数量={len(all_instances)}")
            
            # 添加总计信息
            for instance in all_instances:
                instance['total_count'] = total_count
            
            return all_instances
            
        except Exception as e:
            error_msg = f"获取华为云ECS实例列表失败: 区域={self.region}, 错误={str(e)}"
            self.logger.error(error_msg)
            # 返回空列表而不是抛出异常，以便后续处理可以继续
            return []