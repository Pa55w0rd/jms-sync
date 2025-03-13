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
import uuid
import logging
import threading
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from dataclasses import dataclass, field
from functools import wraps
from datetime import datetime, timedelta

from jms_sync.config import Config, load_config
from jms_sync.jumpserver.client import JumpServerClient
from jms_sync.jumpserver.models import AssetInfo, NodeInfo, SyncResult
from jms_sync.cloud.aliyun import AliyunCloud
from jms_sync.cloud.huawei import HuaweiCloud
from jms_sync.sync.operations import CloudAssetOperation, AssetSynchronizer
from jms_sync.utils.exceptions import JmsSyncError, CloudError, JumpServerError
from jms_sync.utils.logger import get_logger, StructuredLogger
from jms_sync.utils.notifier import NotificationManager


def timed(func):
    """
    计时装饰器，用于统计函数执行时间
    
    Args:
        func: 待装饰的函数
        
    Returns:
        装饰后的函数
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        # 获取函数名称
        func_name = func.__name__
        
        # 计算执行时间
        elapsed_time = end_time - start_time
        
        # 记录日志
        logging.debug(f"性能: {func_name} 执行时间: {elapsed_time:.2f}秒")
        
        return result
    return wrapper


class CloudClientFactory:
    """
    云平台客户端工厂类，用于创建不同类型的云平台客户端
    """
    
    @staticmethod
    def create(cloud_config: Dict[str, Any], cache_storage=None) -> Optional["CloudClient"]:
        """
        根据配置创建云平台客户端
        
        Args:
            cloud_config: 云平台配置
            cache_storage: 缓存存储
            
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
            'parallel_workers': 5,
            'retry_count': 3,
            'retry_interval': 5,
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
            except Exception as e:
                error_msg = f"从配置文件加载配置失败: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise JmsSyncError(error_msg)
        else:
            self.config = config
        
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
        self.parallel_workers = self.sync_config.get('parallel_workers', 5)
        self.batch_size = self.sync_config.get('batch_size', 20)
        self.cache_ttl = self.sync_config.get('cache_ttl', 3600)
        
        # 获取所有支持的云平台类型
        self.cloud_types = []
        clouds_config = self.config.get('clouds', [])
        
        # 初始化云平台客户端
        self.clouds = {}  # 云平台客户端字典
        self._init_cloud_clients(clouds_config)
        
        # 初始化通知管理器
        notification_config = self.config.get('notification', {})
        self.notifier = NotificationManager(notification_config)
        
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
    
    @timed
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
    
    @timed
    def run(self) -> Dict[str, Any]:
        """
        运行同步管理器，同步所有云平台资产。
        
        Returns:
            Dict[str, Any]: 同步结果
        """
        start_time = time.time()
        self.logger.info("开始同步云平台资产到JumpServer")
        
        # 初始化性能指标
        self.performance_metrics = {
            'cloud_client_init': [],
            'assets_fetch_time': {},
            'sync_time': {},
            'total_duration': 0
        }
        
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
                        
                        # 获取云平台资产
                        cloud_client = self.clouds.get(f"{cloud_type}-{cloud_name}")
                        if not cloud_client:
                            self.logger.error(f"云平台客户端初始化失败: {cloud_type}-{cloud_name}")
                            sync_results[f"{cloud_type}-{cloud_name}"] = {
                                'success': False,
                                'error': "客户端初始化失败",
                                'created': 0,
                                'updated': 0,
                                'failed': 0
                            }
                            continue
                        
                        # 直接同步资产，避免重复获取资产
                        sync_start = time.time()
                        result = self.sync_cloud_to_jms(cloud_type, cloud_name)
                        sync_end = time.time()
                        self.performance_metrics['sync_time'][f"{cloud_type}-{cloud_name}"] = {
                            "duration": sync_end - sync_start,
                            "assets_total": getattr(result, 'total', 0),
                            "created": result.created,
                            "updated": result.updated,
                            "deleted": result.deleted if hasattr(result, 'deleted') else 0
                        }
                        
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
            self.performance_metrics['total_duration'] = time.time() - start_time
            
            # 汇总结果
            overall_result = {
                'success': True,
                'error': None,
                'message': "同步完成",
                'results': sync_results,
                'performance': {
                    'total_duration': f"{self.performance_metrics['total_duration']:.2f}秒",
                    'client_init_avg': self._calculate_avg_duration('cloud_client_init'),
                    'assets_fetch_avg': self._calculate_avg_duration('assets_fetch_time'),
                    'sync_avg': self._calculate_avg_duration('sync_time')
                }
            }
            
            # 输出性能指标
            self._log_performance_metrics()
            
            self.logger.info(f"同步完成，总耗时: {self.performance_metrics['total_duration']:.2f}秒")
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
    
    def _log_performance_metrics(self):
        """
        记录性能指标
        """
        self.logger.info("--- 性能指标 ---")
        
        # 总耗时
        self.logger.info(f"总耗时: {self.performance_metrics['total_duration']:.2f}秒")
        
        # 客户端初始化性能
        for metric in self.performance_metrics.get('cloud_client_init', []):
            duration = metric.get('duration', 0)
            name = metric.get('cloud', '')
            self.logger.info(f"云平台 {name} 客户端初始化: {duration:.2f}秒")
        
        # 资产同步性能（包含获取和处理）
        for cloud_name, metric_data in self.performance_metrics.get('sync_time', {}).items():
            if isinstance(metric_data, dict):
                assets_total = metric_data.get('assets_total', 0)
                duration = metric_data.get('duration', 0)
                created = metric_data.get('created', 0)
                updated = metric_data.get('updated', 0)
                deleted = metric_data.get('deleted', 0)
                speed = assets_total / duration if duration > 0 and assets_total > 0 else 0
                self.logger.info(
                    f"云平台 {cloud_name} 同步: {duration:.2f}秒, "
                    f"共{assets_total}个资产 (创建{created}, 更新{updated}, 删除{deleted}), "
                    f"速率: {speed:.1f}个/秒"
                )
    
    def _calculate_avg_duration(self, metric_name: str) -> str:
        """
        计算平均持续时间
        
        Args:
            metric_name: 指标名称
            
        Returns:
            str: 格式化的平均持续时间
        """
        metrics_dict = self.performance_metrics.get(metric_name, {})
        if not metrics_dict:
            return "0.00秒"
            
        # 从字典中提取duration值
        durations = []
        for key in metrics_dict:
            value = metrics_dict[key]
            # 检查value是否为字典类型
            if isinstance(value, dict):
                durations.append(value.get('duration', 0))
            elif isinstance(value, (int, float)):
                # 如果是数值，直接使用
                durations.append(value)
            else:
                self.logger.warning(f"性能指标中的值类型不正确: {key}={value} (类型: {type(value).__name__})")
                continue
                
        if not durations:
            return "0.00秒"
            
        total_duration = sum(durations)
        avg_duration = total_duration / len(durations)
        return f"{avg_duration:.2f}秒"
    
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

    @timed
    def sync_cloud_to_jms(self, cloud_type: str, cloud_name: str) -> SyncResult:
        """
        将云平台资产同步到JumpServer
        
        Args:
            cloud_type: 云平台类型
            cloud_name: 云平台名称
            
        Returns:
            SyncResult: 同步结果
        """
        # 记录开始时间
        start_time = time.time()
        
        # 获取云平台客户端
        cloud_client = self.clouds.get(f"{cloud_type}-{cloud_name}")
        if not cloud_client:
            error_msg = f"找不到云平台客户端: {cloud_type}-{cloud_name}"
            self.logger.error(error_msg)
            return SyncResult(
                success=False,
                created=0,
                updated=0,
                failed=0,
                duration=time.time() - start_time
            )
        
        # 获取云平台配置
        clouds = self.config.get('clouds', [])
        cloud_config = None
        for cfg in clouds:
            if cfg.get('type') == cloud_type and cfg.get('name') == cloud_name:
                cloud_config = cfg
                break
                
        if not cloud_config:
            error_msg = f"找不到云平台配置: {cloud_type}-{cloud_name}"
            self.logger.error(error_msg)
            return SyncResult(
                success=False,
                created=0,
                updated=0,
                failed=0,
                duration=time.time() - start_time
            )
        
        created_assets = []
        deleted_assets = []
        
        try:
            # 创建资产操作类
            cloud_operator = CloudAssetOperation(
                cloud_client=cloud_client,
                js_client=self.js_client,
                config=cloud_config,
                cache_ttl=self.cache_ttl,
                logger=self.logger
            )
            
            # 获取云平台资产
            self.logger.info(f"开始获取云平台 {cloud_type}-{cloud_name} 资产...")
            cloud_assets = cloud_operator.get_cloud_assets()
            self.logger.info(f"成功获取云平台 {cloud_type}-{cloud_name} 资产: {len(cloud_assets)}个")
            
            # 全量同步
            self.logger.info(f"全量同步: 将同步所有{len(cloud_assets)}个资产")
            
            # 资产同步器 - 资产的创建、更新和删除逻辑由AssetSynchronizer处理
            synchronizer = AssetSynchronizer(
                js_client=self.js_client,
                parallel_workers=self.parallel_workers,
                batch_size=self.batch_size,
                logger=self.logger,
                cloud_config=cloud_config
            )
            
            # 执行同步
            result = synchronizer.sync_assets(cloud_assets, cloud_type)
            
            # 记录资产变更详情用于通知
            created_assets = getattr(synchronizer, 'created_assets', [])
            deleted_assets = getattr(synchronizer, 'deleted_assets', [])
            
            # 记录同步耗时
            end_time = time.time()
            result.duration = end_time - start_time
            
            # 发送通知
            if hasattr(self, 'notifier'):
                self.logger.info("发送资产变更通知...")
                try:
                    success = self.notifier.notify_asset_changes(
                        sync_result=result.to_dict(),
                        platform=cloud_type,
                        cloud_name=cloud_name,
                        created_assets=created_assets,
                        deleted_assets=deleted_assets
                    )
                    if success:
                        self.logger.info("资产变更通知发送成功")
                    else:
                        self.logger.warning("资产变更通知发送失败或没有配置通知")
                except Exception as e:
                    self.logger.error(f"发送资产变更通知时发生错误: {e}", exc_info=True)
            
            return result
            
        except Exception as e:
            # 记录异常
            self.logger.error(f"同步资产时发生错误: {e}", exc_info=True)
            
            # 创建错误结果
            result = SyncResult(
                success=False,
                failed=1,
                created=0,
                updated=0,
                deleted=0,
                duration=time.time() - start_time
            )
            result.add_error("N/A", str(e))
            
            return result 