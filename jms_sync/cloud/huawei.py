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

from jms_sync.cloud.base import CloudBase
from jms_sync.utils.exceptions import HuaweiError

class HuaweiCloud(CloudBase):
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
        super().__init__(access_key_id, access_key_secret, region)
        self.project_id = project_id
        self.logger.info(f"初始化华为云客户端: 区域={region}, 项目ID={project_id}")
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
                
            # 测试客户端连接
            self.logger.debug("测试华为云ECS客户端连接")
            try:
                # 发送一个简单的请求来测试连接
                test_request = ListServersDetailsRequest(limit=1)
                client.list_servers_details(test_request)
                self.logger.debug("华为云ECS客户端连接测试成功")
            except exceptions.ClientRequestException as e:
                self.logger.error(f"华为云ECS客户端连接测试失败: {e.error_msg}")
                self.logger.error(f"状态码: {e.status_code}, 请求ID: {e.request_id}, 错误码: {e.error_code}")
                if "project_id" in e.error_msg.lower() or "projectid" in e.error_msg.lower():
                    self.logger.error(f"可能是项目ID与区域不匹配，请检查项目ID: {self.project_id} 和区域: {self.region}")
                raise
                
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
            # 创建请求对象
            self.logger.debug(f"创建华为云ECS实例列表请求: 区域={self.region}")
            request = ListServersDetailsRequest()
            # 设置分页大小
            request.limit = 100
            
            # 获取所有实例
            all_instances = []
            offset = 0
            
            while True:
                # 设置偏移量
                request.offset = offset
            
            # 发送请求
                self.logger.debug(f"发送华为云ECS实例列表请求: 区域={self.region}, 偏移量={offset}")
                try:
                    response = self.client.list_servers_details(request)
                    servers = response.servers
                except exceptions.ClientRequestException as e:
                    self.logger.error(f"获取华为云ECS实例列表失败: {e.error_msg}")
                    self.logger.error(f"状态码: {e.status_code}, 请求ID: {e.request_id}, 错误码: {e.error_code}")
                    # 如果是认证错误，尝试重新创建客户端
                    if "authentication" in e.error_msg.lower() or "token" in e.error_msg.lower():
                        self.logger.info("尝试重新创建华为云ECS客户端")
                        self.client = self.get_client()
                        continue
                    raise
                
                # 如果没有更多实例，退出循环
                if not servers:
                    self.logger.debug(f"华为云ECS实例列表为空或已获取完毕: 区域={self.region}, 偏移量={offset}")
                    break
                
                self.logger.debug(f"获取到华为云ECS实例: 区域={self.region}, 数量={len(servers)}")
                
                # 处理实例信息
                for server in servers:
                    try:
                        # 将server对象转换为字典
                        server_dict = {}
                        for attr in dir(server):
                            if not attr.startswith('_') and not callable(getattr(server, attr)):
                                server_dict[attr] = getattr(server, attr)
                        
                        # 获取网络信息
                        addresses = server_dict.get('addresses', {})
                        private_ip = None
                        public_ip = None
                        
                        # 遍历所有网络
                        for network_name, address_list in addresses.items():
                            for address in address_list:
                                # 判断IP类型
                                if isinstance(address, dict):
                                    # 字典格式
                                    if address.get('OS-EXT-IPS:type') == "fixed":
                                        private_ip = address.get('addr')
                                    elif address.get('OS-EXT-IPS:type') == "floating":
                                        public_ip = address.get('addr')
                                    else:
                                        # 如果没有类型字段，尝试根据地址判断
                                        addr = address.get('addr')
                                        if addr:
                                            if addr.startswith('10.') or addr.startswith('172.') or addr.startswith('192.168.'):
                                                private_ip = addr
                                            else:
                                                public_ip = addr
                                else:
                                    # 对象格式
                                    addr_type = getattr(address, 'OS-EXT-IPS:type', None)
                                    if addr_type == "fixed":
                                        private_ip = getattr(address, 'addr', None)
                                    elif addr_type == "floating":
                                        public_ip = getattr(address, 'addr', None)
                                    else:
                                        # 如果没有类型字段，尝试根据地址判断
                                        addr = getattr(address, 'addr', None)
                                        if addr:
                                            if addr.startswith('10.') or addr.startswith('172.') or addr.startswith('192.168.'):
                                                private_ip = addr
                                            else:
                                                public_ip = addr
                        
                        # 处理flavor信息
                        instance_type = ""
                        if 'flavor' in server_dict:
                            flavor = server_dict['flavor']
                            if isinstance(flavor, dict):
                                instance_type = flavor.get('id', '')
                            else:
                                # 如果flavor是对象，尝试获取id属性
                                instance_type = getattr(flavor, 'id', '')
                        
                        # 构建实例信息
                        instance_dict = {
                            'instance_id': server_dict.get('id', ''),
                            'id': server_dict.get('id', ''),
                            'name': server_dict.get('name', ''),
                            'status': server_dict.get('status', ''),
                            'vpc_id': self._get_vpc_id(server),
                            'private_ip': private_ip,
                            'public_ip': public_ip,
                            'os_name': server_dict.get('OS-EXT-SRV-ATTR:os_type', ''),
                            'os_type': self._determine_os_type(server),
                            'region_id': self.region,
                            'zone_id': server_dict.get('OS-EXT-AZ:availability_zone', ''),
                            'instance_type': instance_type,
                            'creation_time': server_dict.get('created', '')
                        }
                        
                        all_instances.append(instance_dict)
                    except Exception as e:
                        self.logger.warning(f"处理华为云实例信息失败: {str(e)}, 实例ID: {getattr(server, 'id', 'unknown')}")
                        continue
                
                # 更新偏移量
                offset += len(servers)
                
                # 如果返回的实例数量小于请求的数量，说明已经获取了所有实例
                if len(servers) < request.limit:
                    break
            
            self.logger.info(f"获取华为云ECS实例成功: 区域={self.region}, 总数={len(all_instances)}")
            return all_instances
        except exceptions.ClientRequestException as e:
            error_msg = f"获取华为云实例失败: {e.error_msg}, 状态码: {e.status_code}, 错误码: {e.error_code}"
            self.logger.error(error_msg)
            raise HuaweiError(error_msg)
        except Exception as e:
            error_msg = f"获取华为云实例失败: {str(e)}"
            self.logger.error(error_msg)
            raise HuaweiError(error_msg)
            
    def _get_vpc_id(self, server) -> str:
        """
        从服务器信息中获取VPC ID
        
        Args:
            server: 服务器信息
            
        Returns:
            str: VPC ID
        """
        try:
            # 将server对象转换为字典（如果不是字典的话）
            if not isinstance(server, dict):
                server_dict = {}
                for attr in dir(server):
                    if not attr.startswith('_') and not callable(getattr(server, attr)):
                        try:
                            server_dict[attr] = getattr(server, attr)
                        except Exception:
                            # 忽略无法获取的属性
                            pass
            else:
                server_dict = server
                
            # 尝试从metadata中获取VPC ID
            metadata = server_dict.get('metadata', {})
            vpc_id = ''
            
            if isinstance(metadata, dict):
                vpc_id = metadata.get('vpc_id', '')
            else:
                # 如果metadata是对象，尝试获取vpc_id属性
                try:
                    vpc_id = getattr(metadata, 'vpc_id', '')
                except Exception:
                    pass
            
            # 如果metadata中没有VPC ID，尝试从其他属性获取
            if not vpc_id:
                # 尝试从安全组获取
                security_groups = server_dict.get('security_groups', [])
                if isinstance(security_groups, list):
                    for sg in security_groups:
                        if isinstance(sg, dict) and 'vpc-' in sg.get('name', ''):
                            vpc_id = sg.get('name').split('-')[1]
                            break
                else:
                    # 如果security_groups是对象，尝试遍历
                    try:
                        for sg in security_groups:
                            sg_name = getattr(sg, 'name', '')
                            if 'vpc-' in sg_name:
                                vpc_id = sg_name.split('-')[1]
                                break
                    except Exception:
                        pass
            
            # 如果仍然没有VPC ID，使用默认值
            if not vpc_id:
                vpc_id = 'default'
                
            return vpc_id
        except Exception as e:
            self.logger.warning(f"获取VPC ID失败: {str(e)}")
            return 'default'
            
    def _determine_os_type(self, server) -> str:
        """
        从服务器信息中确定操作系统类型
        
        Args:
            server: 服务器信息
            
        Returns:
            str: 操作系统类型，'Windows' 或 'Linux'
        """
        try:
            # 将server对象转换为字典（如果不是字典的话）
            if not isinstance(server, dict):
                server_dict = {}
                for attr in dir(server):
                    if not attr.startswith('_') and not callable(getattr(server, attr)):
                        try:
                            server_dict[attr] = getattr(server, attr)
                        except Exception:
                            # 忽略无法获取的属性
                            pass
            else:
                server_dict = server
                
            # 首先检查metadata中的os_type字段
            metadata = server_dict.get('metadata', {})
            if isinstance(metadata, dict):
                os_type = metadata.get('os_type', '').lower()
                if 'windows' in os_type:
                    return 'Windows'
            else:
                # 如果metadata是对象，尝试获取os_type属性
                try:
                    os_type = getattr(metadata, 'os_type', '').lower()
                    if 'windows' in os_type:
                        return 'Windows'
                except Exception:
                    pass
                
            # 然后检查image_name字段
            image_name = server_dict.get('image_name', '').lower()
            if 'windows' in image_name:
                return 'Windows'
                
            # 然后检查OS-EXT-SRV-ATTR:os_type字段
            os_attr = server_dict.get('OS-EXT-SRV-ATTR:os_type', '').lower()
            if 'windows' in os_attr:
                return 'Windows'
                
            # 最后检查实例名称
            instance_name = server_dict.get('name', '').lower()
            if 'win' in instance_name:
                return 'Windows'
                
            # 默认为Linux
            return 'Linux'
        except Exception as e:
            self.logger.warning(f"确定操作系统类型失败: {str(e)}")
            return 'Linux'
    
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
        
    def ecs_info(self, region: str) -> Tuple[List[str], List[str], Dict[str, str], Dict[str, str]]:
        """
        获取ECS实例信息
        
        Args:
            region: 区域ID
            
        Returns:
            Tuple[List[str], List[str], Dict[str, str], Dict[str, str]]: 
                (IP列表, 资产名称列表, IP到VPC ID的映射, IP到操作系统类型的映射)
        """
        assets_ip_list = []
        assets_name_list = []
        assets_node = {}
        assets_os_type = {}
        
        try:
            # 获取实例列表
            instances = self.get_instances()
            
            # 处理实例信息
            for instance in instances:
                # 获取IP地址（优先使用私有IP，如果没有则使用公网IP）
                ip = instance.get('private_ip') or instance.get('public_ip')
                
                # 如果没有IP地址，跳过该实例
                if not ip:
                    self.logger.warning(f"实例 {instance.get('id')} 没有IP地址，跳过")
                    continue
                    
                # 获取实例名称
                instance_name = instance.get('name')
                if not instance_name:
                    instance_name = instance.get('id')
                
                # 直接使用实例名称，不添加前缀
                asset_name = instance_name
                
                # 获取VPC ID
                vpc_id = instance.get('vpc_id', 'default')
                
                # 确定操作系统类型
                os_type = self.determine_os_type(instance)
                
                # 添加到结果列表
                assets_ip_list.append(ip)
                assets_name_list.append(asset_name)
                assets_node[ip] = vpc_id
                assets_os_type[ip] = os_type
            
            return assets_ip_list, assets_name_list, assets_node, assets_os_type
        except Exception as e:
            error_msg = f"获取华为云ECS实例信息失败: {str(e)}"
            self.logger.error(error_msg)
            raise HuaweiError(error_msg) 