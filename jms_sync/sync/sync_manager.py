#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
同步管理器模块，负责协调云平台和JumpServer之间的同步。

主要功能：
- 加载和验证配置
- 初始化JumpServer和云平台客户端
- 协调云平台资产同步到JumpServer
- 记录同步结果和性能指标
"""

import os
import time
import json
import logging
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from jms_sync.config import Config, load_config
from jms_sync.jumpserver.client import JumpServerClient
from jms_sync.jumpserver.models import AssetInfo, NodeInfo, SyncResult
from jms_sync.cloud.aliyun import AliyunCloud
from jms_sync.cloud.huawei import HuaweiCloud
from jms_sync.sync.asset_sync import AssetSyncManager
from jms_sync.utils.exceptions import JmsSyncError, CloudError, JumpServerError
from jms_sync.utils.logger import get_logger, set_global_config
from jms_sync.utils.notifier import NotificationManager

class CloudClientFactory:
    """
    云平台客户端工厂类，用于创建不同类型的云平台客户端
    """
    
    @staticmethod
    def create(cloud_config: Dict[str, Any]) -> Optional["CloudClient"]:
        """
        根据配置创建云平台客户端
        
        Args:
            cloud_config: 云平台配置
            
        Returns:
            CloudClient: 云平台客户端
            
        """
        cloud_type = cloud_config.get('type', '')
        
        if cloud_type == 'aliyun' or cloud_type == '阿里云':
            # 创建阿里云客户端
            return AliyunCloud(
                access_key_id=cloud_config.get('access_key_id', ''),
                access_key_secret=cloud_config.get('access_key_secret', ''),
                region=cloud_config.get('regions', ['cn-hangzhou'])[0]  # 使用第一个区域初始化
            )
        elif cloud_type == 'huawei' or cloud_type == '华为云':
            # 创建华为云客户端
            return HuaweiCloud(
                access_key_id=cloud_config.get('access_key_id', ''),
                access_key_secret=cloud_config.get('access_key_secret', ''),
                project_id=cloud_config.get('project_id', ''),
                region=cloud_config.get('regions', ['cn-north-4'])[0]  # 使用第一个区域初始化
            )
        else:
            raise JmsSyncError(f"不支持的云平台类型: {cloud_type}")


class SyncManager:
    """
    同步管理器类，负责协调云平台和JumpServer之间的同步
    """
    
    DEFAULT_CONFIG = {
        'jumpserver': {
            'base_url': '',
            'access_key_id': '',
            'access_key_secret': '',
            'org_id': '00000000-0000-0000-0000-000000000002',
        },
        'sync_options': {
            'whitelist': [],
            'protected_ips': [],
            'no_delete': False,
        },
        'clouds': []
    }
    
    def __init__(self, config: Union[Dict[str, Any], str], logger = None):
        """
        初始化同步管理器
        
        Args:
            config: 配置信息（可以是配置字典或配置文件路径）
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger(__name__)
        
        # 如果config是字符串，则假定它是配置文件路径，尝试加载配置
        if isinstance(config, str):
            self.logger.debug(f"传入的config是字符串，尝试从文件加载配置: {config}")
            try:
                self.config = load_config(config)
                self.logger.debug(f"成功从文件加载配置: {config}")
                
                # 设置全局配置对象，供其他模块使用
                set_global_config(self.config)
                
            except Exception as e:
                error_msg = f"从配置文件加载配置失败: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise JmsSyncError(error_msg)
        else:
            self.config = config
            
            # 如果传入的是Config对象，设置为全局配置
            if isinstance(self.config, Config):
                set_global_config(self.config)
        
        # 确保config是字典类型或Config类型
        if not isinstance(self.config, (dict, Config)):
            error_msg = f"配置必须是字典类型或Config类型，当前类型: {type(self.config).__name__}"
            self.logger.error(error_msg)
            raise JmsSyncError(error_msg)
        
        # 初始化JumpServer客户端
        js_config = self.config.get('jumpserver', {})
        url = js_config.get('url', '')
        access_key_id = js_config.get('access_key_id', '')
        access_key_secret = js_config.get('access_key_secret', '')
        org_id = js_config.get('org_id', '00000000-0000-0000-0000-000000000002')
        
        self.js_client = JumpServerClient(
            base_url=url,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            org_id=org_id,
            config=js_config
        )
        
        # 获取同步配置
        self.sync_config = self.config.get('sync', {})
        
        # 初始化云平台客户端
        self.clouds = {}  # 云平台客户端字典
        self._init_cloud_clients(self.config.get('clouds', []))
        
        # 初始化通知管理器
        notification_config = self.config.get('notification', {})
        self.notifier = NotificationManager(notification_config)
        
        # 初始化资产同步管理器
        self.asset_sync_manager = AssetSyncManager(self.js_client, logger=self.logger)
        
        self.logger.info("同步管理器初始化完成")
    
    def _init_cloud_clients(self, clouds_config: List[Dict[str, Any]]):
        """
        初始化所有云平台客户端
        """
        for cloud_config in clouds_config:
            if cloud_config.get('enabled', True):
                cloud_type = cloud_config.get('type', '')
                cloud_name = cloud_config.get('name', '')
                self.clouds[f"{cloud_type}-{cloud_name}"] = self._init_cloud_client(cloud_config)
    
    def _init_cloud_client(self, cloud_config: Dict[str, Any]) -> Union[AliyunCloud, HuaweiCloud]:
        """
        初始化云平台客户端
        
        Args:
            cloud_config: 云平台配置
            
        Returns:
            Union[AliyunCloud, HuaweiCloud]: 云平台客户端实例
            
        Raises:
            JmsSyncError: 初始化失败时抛出异常
        """
        try:
            cloud_type = cloud_config.get('type', '')
            cloud_name = cloud_config.get('name', '')
            
            self.logger.info(f"初始化云平台客户端: 类型={cloud_type}, 名称={cloud_name}")
            
            return CloudClientFactory.create(cloud_config)
        except Exception as e:
            error_msg = f"初始化云平台客户端失败: {str(e)}"
            self.logger.error(error_msg)
            raise JmsSyncError(error_msg)
    
    def run(self) -> Dict[str, Any]:
        """
        运行同步管理器，同步所有云平台资产。
        
        Returns:
            Dict[str, Any]: 同步结果
        """
        start_time = time.time()
        self.logger.info("开始同步云平台资产到JumpServer")
        
        # 同步结果
        sync_results = {}
        
        try:
            # 获取需要同步的云平台
            clouds = self.config.get('clouds', [])
            enabled_clouds = [cloud for cloud in clouds if cloud.get('enabled', True)]
            
            if not enabled_clouds:
                self.logger.warning("没有启用的云平台，同步结束")
                return {
                    'success': True,
                    'error': None,
                    'message': "没有启用的云平台",
                    'results': {},
                    'duration': f"{time.time() - start_time:.2f}秒"
                }
            
            # 按类型分组云平台
            platform_types = {}
            for cloud in enabled_clouds:
                cloud_type = cloud.get('type')
                cloud_name = cloud.get('name')
                if not cloud_type or not cloud_name:
                    self.logger.warning(f"跳过配置不完整的云平台: {cloud}")
                    continue
                
                if cloud_type not in platform_types:
                    platform_types[cloud_type] = []
                platform_types[cloud_type].append((cloud_type, cloud_name, cloud))
            
            # 按类型同步云平台资产
            for cloud_type, platforms in platform_types.items():
                self.logger.info(f"同步云平台类型: {cloud_type}，共{len(platforms)}个平台")
                
                for cloud_type, cloud_name, cloud_config in platforms:
                    try:
                        self.logger.info(f"开始同步云平台: {cloud_name}")
                        
                        # 获取云平台资产并同步到JumpServer
                        sync_start = time.time()
                        result = self.sync_cloud_to_jms(cloud_type, cloud_name)
                        sync_end = time.time()
                        
                        # 更新整体结果
                        sync_results[f"{cloud_type}-{cloud_name}"] = result
                        
                    except Exception as e:
                        self.logger.error(f"同步云平台 {cloud_name} 时发生错误: {str(e)}", exc_info=True)
                        sync_results[f"{cloud_type}-{cloud_name}"] = {
                            'success': False,
                            'error': str(e),
                            'created': 0,
                            'updated': 0,
                            'failed': 0
                        }
            
            # 记录总耗时
            total_duration = time.time() - start_time
            
            # 汇总结果
            overall_result = {
                'success': True,
                'error': None,
                'message': "同步完成",
                'results': sync_results,
                'duration': f"{total_duration:.2f}秒"
            }
            
            self.logger.info(f"同步完成，总耗时: {total_duration:.2f}秒")
            return overall_result
            
        except Exception as e:
            self.logger.error(f"同步过程中发生未预期错误: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'message': "同步过程中发生错误",
                'results': sync_results,
                'duration': f"{time.time() - start_time:.2f}秒"
            }
    
    def run_with_retry(self, max_retries: int = 3, retry_interval: int = 5) -> Dict[str, Any]:
        """
        带重试机制的同步
        
        Args:
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            
        Returns:
            Dict[str, Any]: 同步结果
        """
        attempt = 0
        last_error = None
        
        while attempt <= max_retries:
            try:
                if attempt > 0:
                    self.logger.info(f"第 {attempt} 次重试 (最大 {max_retries} 次)")
                
                result = self.run()
                
                # 确保result中的errors字段不为None
                if result.get('errors') is None:
                    result['errors'] = []
                
                # 如果没有错误，返回结果
                if not result.get('errors', []):
                    return result
                
                # 如果只有部分错误，也返回结果
                if result.get('success', 0) > 0:
                    errors = result.get('errors', [])
                    self.logger.warning(f"同步部分成功，有 {len(errors)} 个错误")
                    return result
                
                # 全部失败，继续重试
                last_error = result.get('errors', ["未知错误"])
                if last_error is None:
                    last_error = ["未知错误"]
                
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"同步尝试 {attempt+1} 失败: {last_error}")
            
            attempt += 1
            
            if attempt <= max_retries:
                self.logger.info(f"等待 {retry_interval} 秒后重试")
                time.sleep(retry_interval)
        
        # 所有重试都失败
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "errors": [{"message": f"所有重试都失败: {last_error}"}],
            "duration": "0.00秒"
        }

    def sync_cloud_to_jms(self, cloud_type: str, cloud_name: str) -> SyncResult:
        """
        同步指定云平台的资产到JumpServer
        
        Args:
            cloud_type: 云平台类型
            cloud_name: 云平台名称
            
        Returns:
            SyncResult: 同步结果
        """
        start_time = time.time()
        
        self.logger.info(f"开始同步云平台资产: {cloud_type}/{cloud_name}")
        # 初始化云客户端实例
        cloud_client = self.clouds.get(f"{cloud_type}-{cloud_name}")
        if not cloud_client:
            error_msg = f"云平台客户端不存在: {cloud_type}-{cloud_name}"
            self.logger.error(error_msg)
            return SyncResult(
                success=False,
                total=0,
                created=0,
                updated=0,
                deleted=0,
                duration=0,
                error_message=error_msg
            )
        
        # 同步结果初始化
        sync_result = SyncResult(
            success=True,
            total=0,
            created=0,
            updated=0,
            deleted=0,
            duration=0,
            error_message=""
        )
        
        try:
            # 1. 获取云平台配置
            clouds = self.config.get('clouds', [])
            cloud_config = None
            for cloud in clouds:
                if cloud.get('type') == cloud_type and cloud.get('name') == cloud_name:
                    cloud_config = cloud
                    break
                    
            if not cloud_config:
                error_msg = f"未找到云平台配置: {cloud_type}/{cloud_name}"
                self.logger.error(error_msg)
                sync_result.success = False
                sync_result.error_message = error_msg
                return sync_result
                
            # 2. 获取云平台所有区域实例
            regions = cloud_config.get('regions', [])
            self.logger.info(f"需要同步的区域: {regions}")
            
            # 3. 获取所有区域的实例信息
            all_instances = []
            api_total_count = 0  # 记录API返回的实例总数
            for region in regions:
                try:
                    self.logger.info(f"获取区域 {region} 的实例信息")
                    # 修复：先设置区域，再调用无参数的get_instances()方法
                    if cloud_type == 'aliyun' or cloud_type == '阿里云':
                        # 阿里云客户端需要先切换区域
                        cloud_client.set_region(region)
                        instances = cloud_client.get_instances()
                    elif cloud_type == 'huawei' or cloud_type == '华为云':
                        # 华为云客户端需要先切换区域
                        cloud_client.set_region(region)
                        instances = cloud_client.get_instances()
                    else:
                        self.logger.warning(f"未知的云平台类型: {cloud_type}")
                        instances = []
                        
                    self.logger.info(f"区域 {region} 中发现 {len(instances)} 个实例")
                    
                    # 记录API返回的总数
                    if instances and len(instances) > 0 and 'total_count' in instances[0]:
                        current_total = instances[0].get('total_count', 0)
                        self.logger.debug(f"区域 {region} API返回总数: {current_total}")
                        api_total_count += current_total
                    
                    # 处理每个实例，使其规范化为标准格式
                    processed_instances = []
                    for instance in instances:
                        try:
                            # 处理云平台实例，转换为标准格式的字典
                            processed = self._process_cloud_instance(instance, cloud_type, region)
                            if processed:
                                processed_instances.append(processed)
                            else:
                                self.logger.warning(f"处理实例失败: {instance.get('instance_id', 'unknown')}")
                        except Exception as e:
                            self.logger.error(f"处理实例时发生错误: {str(e)}")
                    
                    all_instances.extend(processed_instances)
                except Exception as e:
                    self.logger.error(f"获取区域 {region} 实例信息失败: {str(e)}")
            
            # 保存处理后的实例总数
            sync_result.total = len(all_instances)
            
            # 检查API返回总数与实际获取数量是否匹配
            if api_total_count > 0 and sync_result.total != api_total_count:
                warning_msg = f"实例数量不匹配，跳过同步操作: API返回总数={api_total_count}, 实际获取数量={sync_result.total}"
                self.logger.warning(warning_msg)
                
                # 设置结果
                sync_result.success = False
                sync_result.error_message = warning_msg
                
                # 添加到结果中
                sync_result.expected_total = api_total_count
                
                # 发送通知
                try:
                    result_dict = sync_result.to_dict()
                    result_dict["update_reasons"] = []
                    self.notifier.notify_asset_changes(
                        sync_result=result_dict,
                        platform=cloud_type,
                        cloud_name=cloud_name,
                        created_assets=[],
                        deleted_assets=[],
                        is_failure=True
                    )
                except Exception as e:
                    self.logger.error(f"发送数量不匹配通知失败: {str(e)}")
                
                # 直接返回结果，不继续同步
                return sync_result
            else:
                sync_result.expected_total = api_total_count
            
            self.logger.info(f"共获取并处理了 {sync_result.total} 个实例 (API返回总数: {api_total_count})")
            
            # 4. 如果没有获取到任何实例，则中止同步
            if not all_instances:
                warning_msg = f"未获取到任何实例信息，中止同步 - 云平台：{cloud_type}/{cloud_name}，区域：{regions}"
                self.logger.warning(warning_msg)
                sync_result.success = True  # 没有实例也视为成功，但不需要进行后续操作
                sync_result.error_message = warning_msg
                
                # 即使没有实例也发送通知，以便管理员了解情况
                try:
                    result_dict = sync_result.to_dict()
                    result_dict["update_reasons"] = []
                    self.notifier.notify_asset_changes(
                        sync_result=result_dict,
                        platform=cloud_type,
                        cloud_name=cloud_name,
                        created_assets=[],
                        deleted_assets=[],
                        is_failure=True  # 将这种情况视为需要通知的"失败"
                    )
                except Exception as e:
                    self.logger.error(f"发送无实例通知失败: {str(e)}")
                
                return sync_result
                
            # 5. 只有在成功获取云平台资产后，才获取或创建JumpServer节点
            node_id = self._get_or_create_cloud_node(cloud_type, cloud_name)
            if not node_id:
                error_msg = f"创建或获取JumpServer节点失败: {cloud_type}/{cloud_name}"
                self.logger.error(error_msg)
                sync_result.success = False
                sync_result.error_message = error_msg
                
                # 即使节点创建失败也发送通知
                try:
                    result_dict = sync_result.to_dict()
                    result_dict["update_reasons"] = []
                    self.notifier.notify_asset_changes(
                        sync_result=result_dict,
                        platform=cloud_type,
                        cloud_name=cloud_name,
                        created_assets=[],
                        deleted_assets=[],
                        is_failure=True
                    )
                except Exception as e:
                    self.logger.error(f"发送节点创建失败通知失败: {str(e)}")
                
                return sync_result
                
            # 6. 同步配置
            sync_options = self.config.get('sync', {})
            no_delete = sync_options.get('no_delete', False)
            protected_ips = sync_options.get('protected_ips', [])
            self.logger.info(f"同步选项: no_delete={no_delete}, 受保护IP数量={len(protected_ips)}")
            
            # 7. 执行资产同步
            assets_result = self.asset_sync_manager.sync_assets(
                cloud_assets=all_instances,
                node_id=node_id,
                cloud_type=cloud_type,
                cloud_name=cloud_name,
                no_delete=no_delete,
                protected_ips=protected_ips
            )
            
            # 8. 整合同步结果
            sync_result.created = assets_result.get('created', 0)
            sync_result.updated = assets_result.get('updated', 0)
            sync_result.deleted = assets_result.get('deleted', 0)
            sync_result.skipped = assets_result.get('skipped', 0)
            sync_result.failed = assets_result.get('failed', 0)
            
            # 获取变更详情
            created_assets = self.asset_sync_manager.created_assets
            updated_assets = self.asset_sync_manager.updated_assets
            deleted_assets = self.asset_sync_manager.deleted_assets
            failed_operations = assets_result.get('errors', [])
            
            if failed_operations:
                sync_result.errors = failed_operations
                
        except Exception as e:
            self.logger.exception(f"同步云平台资产到JumpServer时发生错误: {str(e)}")
            sync_result.success = False
            sync_result.error_message = f"同步过程中发生异常: {str(e)}"
            
        # 计算总耗时
        end_time = time.time()
        duration = end_time - start_time
        sync_result.duration = duration
        sync_result.duration_str = f"{duration:.2f}秒"
        
        # 记录同步结果
        self.logger.info(f"同步完成: 总计={sync_result.total}, "
                       f"创建={sync_result.created}, "
                       f"更新={sync_result.updated}, "
                       f"删除={sync_result.deleted}, "
                       f"跳过={sync_result.skipped}, "
                       f"失败={sync_result.failed}, "
                       f"耗时={sync_result.duration_str}")
        
        # 发送通知
        try:
            # 通知处理完成的结果
            created_assets = self.asset_sync_manager.created_assets
            updated_assets = self.asset_sync_manager.updated_assets
            deleted_assets = self.asset_sync_manager.deleted_assets
            update_reasons = self.asset_sync_manager.update_reasons
            
            # 将更新原因添加到同步结果中
            result_dict = sync_result.to_dict()
            result_dict["update_reasons"] = update_reasons
            
            self.notifier.notify_asset_changes(
                sync_result=result_dict,
                platform=cloud_type,
                cloud_name=cloud_name,
                created_assets=created_assets,
                deleted_assets=deleted_assets,
                is_failure=not sync_result.success
            )
        except Exception as e:
            self.logger.error(f"发送通知失败: {str(e)}")
        
        return sync_result

    def _get_or_create_cloud_node(self, cloud_type: str, cloud_name: str) -> str:
        """
        获取或创建云平台节点，按照文档要求创建三级节点结构
        
        Args:
            cloud_type: 云平台类型（二级节点名称）
            cloud_name: 云平台名称（三级节点名称）
            
        Returns:
            str: 三级节点ID，失败返回空字符串
        """
        try:
            # 通过完整路径获取或创建节点
            path = f"/DEFAULT/{cloud_type}/{cloud_name}"
            self.logger.info(f"获取或创建节点: {path}")
            
            # 使用node_manager管理节点
            if hasattr(self.js_client, 'node_manager'):
                # 初始化节点结构
                self.js_client.node_manager.init_nodes(cloud_type, cloud_name)
                
                # 获取三级节点ID
                node_path = f"/DEFAULT/{cloud_type}/{cloud_name}"
                node = self.js_client.node_manager.get_node_by_path(node_path)
                
                if node:
                    self.logger.info(f"成功获取节点: {node_path}, ID={node['id']}")
                    return node['id']
                else:
                    self.logger.error(f"无法获取节点: {node_path}")
                    return ""
            else:
                self.logger.error("JumpServer客户端没有node_manager属性")
                return ""
                
        except Exception as e:
            self.logger.error(f"获取或创建云平台节点失败: {e}", exc_info=True)
            return ""
            
    def _process_cloud_instance(self, instance: Dict[str, Any], cloud_type: str, region: str) -> Optional[Dict[str, Any]]:
        """
        处理云平台实例，转换为标准格式
        
        Args:
            instance: 云平台实例
            cloud_type: 云平台类型
            region: 区域
            
        Returns:
            Optional[Dict[str, Any]]: 处理后的实例信息，失败返回None
        """
        try:
            # 提取实例ID
            instance_id = self._extract_instance_id(instance)
            if not instance_id:
                self.logger.warning("无法获取实例ID，跳过")
                return None
                
            # 提取IP地址
            ip = self._extract_instance_ip(instance)
            if not ip:
                self.logger.warning(f"实例 {instance_id} 没有可用的IP地址，跳过")
                return None
                
            # 提取实例名称
            instance_name = self._extract_instance_name(instance)
            if not instance_name:
                instance_name = f"{cloud_type}-{instance_id}"
                
            # 提取操作系统类型
            os_type = self._extract_os_type(instance)
            
            # 构建资产数据
            asset_data = {
                'instance_id': instance_id,
                'instance_name': instance_name,
                'hostname': instance_name,
                'ip': ip,
                'address': ip,
                'os_type': os_type,
                'region': region,
                'cloud_type': cloud_type,
            }
            
            # 提取额外信息
            vpc_id = self._extract_vpc_id(instance)
            if vpc_id:
                asset_data['vpc_id'] = vpc_id
                
            instance_type = self._extract_instance_type(instance)
            if instance_type:
                asset_data['instance_type'] = instance_type
                
            return asset_data
            
        except Exception as e:
            self.logger.error(f"处理云平台实例失败: {e}")
            return None
            
    def _extract_instance_id(self, instance: Dict[str, Any]) -> str:
        """
        提取实例ID
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例ID
        """
        # 尝试从不同字段获取实例ID
        if 'instance_id' in instance:
            return instance['instance_id']
        elif 'id' in instance:
            return instance['id']
        elif 'InstanceId' in instance:
            return instance['InstanceId']
            
        # 无法获取实例ID
        return ""
        
    def _extract_instance_ip(self, instance: Dict[str, Any]) -> str:
        """
        提取实例IP地址
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例IP地址
        """
        # 尝试从不同字段获取IP地址
        if 'ip' in instance:
            return instance['ip']
        elif 'private_ip' in instance:
            return instance['private_ip']
        elif 'address' in instance:
            return instance['address']
            
        # 处理不同云平台的特殊字段
        for field_name in ['PrivateIpAddress', 'InnerIpAddress', 'VpcAttributes']:
            if field_name in instance:
                if field_name == 'VpcAttributes':
                    # 处理阿里云的VPC属性中的私有IP
                    vpc_attrs = instance[field_name]
                    if isinstance(vpc_attrs, dict) and 'PrivateIpAddress' in vpc_attrs:
                        private_ips = vpc_attrs['PrivateIpAddress']
                        if isinstance(private_ips, dict) and 'IpAddress' in private_ips:
                            ip_list = private_ips['IpAddress']
                            if isinstance(ip_list, list) and ip_list:
                                return ip_list[0]
                else:
                    # 处理其他类型的IP地址字段
                    value = instance[field_name]
                    if isinstance(value, str):
                        return value
                    elif isinstance(value, list) and value:
                        return value[0]
                    elif isinstance(value, dict) and 'IpAddress' in value:
                        ip_list = value['IpAddress']
                        if isinstance(ip_list, list) and ip_list:
                            return ip_list[0]
        
        # 无法获取IP地址
        return ""
        
    def _extract_instance_name(self, instance: Dict[str, Any]) -> str:
        """
        提取实例名称
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例名称
        """
        # 尝试从不同字段获取实例名称
        if 'instance_name' in instance:
            return instance['instance_name']
        elif 'name' in instance:
            return instance['name']
        elif 'hostname' in instance:
            return instance['hostname']
        elif 'InstanceName' in instance:
            return instance['InstanceName']
        elif 'Name' in instance:
            return instance['Name']
            
        # 无法获取实例名称
        return ""
        
    def _extract_os_type(self, instance: Dict[str, Any]) -> str:
        """
        提取操作系统类型
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 操作系统类型 ('Linux' 或 'Windows')
        """
        # 默认为Linux
        default_os = 'Linux'
        
        # 尝试从不同字段获取操作系统类型
        if 'os_type' in instance:
            os_type = instance['os_type']
            if isinstance(os_type, str) and 'windows' in os_type.lower():
                return 'Windows'
        elif 'OSName' in instance:
            os_name = instance['OSName']
            if isinstance(os_name, str) and 'windows' in os_name.lower():
                return 'Windows'
        elif 'OsName' in instance:
            os_name = instance['OsName']
            if isinstance(os_name, str) and 'windows' in os_name.lower():
                return 'Windows'
        elif 'os_name' in instance:
            os_name = instance['os_name']
            if isinstance(os_name, str) and 'windows' in os_name.lower():
                return 'Windows'
                
        # 尝试从实例名称判断操作系统类型
        instance_name = self._extract_instance_name(instance)
        if instance_name and ('windows' in instance_name.lower() or 'win' in instance_name.lower()):
            return 'Windows'
            
        # 使用默认操作系统类型
        return default_os
        
    def _extract_vpc_id(self, instance: Dict[str, Any]) -> str:
        """
        提取VPC ID
        
        Args:
            instance: 实例数据
            
        Returns:
            str: VPC ID
        """
        # 尝试从不同字段获取VPC ID
        if 'vpc_id' in instance:
            return instance['vpc_id']
        elif 'VpcId' in instance:
            return instance['VpcId']
        elif 'VpcAttributes' in instance:
            vpc_attrs = instance['VpcAttributes']
            if isinstance(vpc_attrs, dict) and 'VpcId' in vpc_attrs:
                return vpc_attrs['VpcId']
                
        # 无法获取VPC ID
        return ""
        
    def _extract_instance_type(self, instance: Dict[str, Any]) -> str:
        """
        提取实例类型
        
        Args:
            instance: 实例数据
            
        Returns:
            str: 实例类型
        """
        # 尝试从不同字段获取实例类型
        if 'instance_type' in instance:
            return instance['instance_type']
        elif 'InstanceType' in instance:
            return instance['InstanceType']
        elif 'flavor' in instance:
            flavor = instance['flavor']
            if isinstance(flavor, dict) and 'id' in flavor:
                return flavor['id']
            elif hasattr(flavor, 'id'):
                return flavor.id
                
        # 无法获取实例类型
        return "" 