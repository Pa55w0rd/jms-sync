#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置验证器，负责验证配置文件的有效性。
"""

import logging
from typing import Dict, Any, List, Optional, Set, Tuple, Union

from jms_sync.utils.exceptions import ConfigError
from jms_sync.utils.logger import get_logger

logger = get_logger(__name__)

class ConfigValidator:
    """
    配置验证器类。
    
    提供配置文件的各项验证功能，确保配置文件包含所需的所有必要字段，
    并且字段的值符合预期的格式和范围。
    """
    
    def __init__(self):
        """初始化配置验证器"""
        pass
        
    def validate(self, config: Dict[str, Any]) -> None:
        """
        验证配置文件的有效性。
        
        Args:
            config: 配置数据
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        # 验证顶级配置项
        self._validate_top_level(config)
        
        # 验证JumpServer配置
        self._validate_jumpserver(config.get('jumpserver', {}))
        
        # 验证云平台配置
        self._validate_clouds(config.get('clouds', []))
        
        # 验证同步配置
        if 'sync' in config:
            sync_config = config['sync']
            if not isinstance(sync_config, dict):
                raise ConfigError("sync配置应为字典类型")
            
            # 验证whitelist
            whitelist = sync_config.get('whitelist')
            if whitelist is not None and not isinstance(whitelist, list):
                raise ConfigError("whitelist选项应为列表类型")
            
            # 验证protected_ips
            protected_ips = sync_config.get('protected_ips')
            if protected_ips is not None and not isinstance(protected_ips, list):
                raise ConfigError("protected_ips选项应为列表类型")
            
            # 验证no_delete
            no_delete = sync_config.get('no_delete')
            if no_delete is not None and not isinstance(no_delete, bool):
                raise ConfigError("no_delete选项应为布尔类型")
        
        # 验证日志配置
        self._validate_log(config.get('log', {}))
        
        logger.debug("配置验证成功")
    
    def _validate_top_level(self, config: Dict[str, Any]) -> None:
        """
        验证顶级配置项。
        
        Args:
            config: 配置数据
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        required_sections = ['jumpserver', 'clouds']
        for section in required_sections:
            if not config.get(section):
                raise ConfigError(f"配置缺少必要的{section}部分")
    
    def _validate_jumpserver(self, js_config: Dict[str, Any]) -> None:
        """
        验证JumpServer配置。
        
        Args:
            js_config: JumpServer配置数据
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        # 验证必要的字段
        required_fields = ['url', 'access_key_id', 'access_key_secret']
        for field in required_fields:
            if not js_config.get(field):
                raise ConfigError(f"JumpServer配置缺少必要字段: {field}")
        
        # 验证URL格式
        url = js_config.get('url', '')
        if url and not url.startswith(('http://', 'https://')):
            raise ConfigError(f"JumpServer URL格式无效: {url}, 应以http://或https://开头")
            
        # 验证verify_ssl选项
        verify_ssl = js_config.get('verify_ssl')
        if verify_ssl is not None and not isinstance(verify_ssl, bool):
            raise ConfigError("verify_ssl选项应为布尔类型")
        
        # 验证protocols配置
        protocols = js_config.get('protocols', {})
        if protocols:
            if not isinstance(protocols, dict):
                raise ConfigError(
                    "JumpServer protocols 配置应为字典类型"
                )
            
            # 验证协议端口
            port_keys = ['ssh_port', 'rdp_port']
            for key in port_keys:
                if key in protocols:
                    port = protocols[key]
                    if not isinstance(port, int) or port < 1 or port > 65535:
                        raise ConfigError(
                            f"JumpServer {key} 端口配置无效: {port}, 应为1-65535之间的整数"
                        )
    
    def _validate_clouds(self, clouds: List[Dict[str, Any]]) -> None:
        """
        验证云平台配置。
        
        Args:
            clouds: 云平台配置列表
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        if not clouds:
            raise ConfigError("云平台配置列表为空")
        
        cloud_names = set()
        
        for i, cloud in enumerate(clouds):
            # 验证必要的字段
            if not cloud.get('type'):
                raise ConfigError(f"云平台配置缺少type字段")
            
            if not cloud.get('name'):
                raise ConfigError(f"云平台配置缺少name字段")
            
            # 检查云平台名称是否重复
            cloud_name = cloud.get('name')
            if cloud_name in cloud_names:
                raise ConfigError(f"云平台名称重复: {cloud_name}")
            cloud_names.add(cloud_name)
            
            # 根据云平台类型验证特定字段
            cloud_type = cloud.get('type', '')
            
            # 如果云平台未启用，跳过进一步验证
            if not cloud.get('enabled', True):
                logger.info(f"云平台 {cloud_type} {cloud_name} 未启用，跳过验证")
                continue
            
            # 公共必要字段验证
            common_fields = ['access_key_id', 'access_key_secret', 'regions']
            for field in common_fields:
                if not cloud.get(field):
                    raise ConfigError(f"云平台{cloud_name}配置缺少{field}字段")
            
            # 验证regions格式
            regions = cloud.get('regions', [])
            if not isinstance(regions, list) or not regions:
                raise ConfigError(f"云平台{cloud_name}的regions应为非空列表")
            
            # 根据云平台类型验证特定字段
            if cloud_type == '阿里云':
                self._validate_aliyun_cloud(cloud, i)
            elif cloud_type == '华为云':
                self._validate_huawei_cloud(cloud, i)
            else:
                raise ConfigError(
                    f"不支持的云平台类型: {cloud_type}"
                )
    
    def _validate_aliyun_cloud(self, cloud: Dict[str, Any], index: int) -> None:
        """
        验证阿里云配置。
        
        Args:
            cloud: 云平台配置
            index: 云平台索引
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        # 阿里云特定验证，暂无额外需要验证的字段
        pass
    
    def _validate_huawei_cloud(self, cloud: Dict[str, Any], index: int) -> None:
        """
        验证华为云配置。
        
        Args:
            cloud: 云平台配置
            index: 云平台索引
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        # 验证华为云特有的project_id字段
        if not cloud.get('project_id'):
            raise ConfigError(f"华为云{cloud.get('name', '')}配置缺少project_id字段")
    
    def _validate_log(self, log_config: Dict[str, Any]) -> None:
        """
        验证日志配置。
        
        Args:
            log_config: 日志配置
            
        Raises:
            ConfigError: 配置无效时抛出异常
        """
        # 验证日志级别
        level = log_config.get('level', 'INFO')
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if level and level not in valid_levels:
            raise ConfigError(f"日志级别无效: {level}，有效值为: {', '.join(valid_levels)}")
        
        # 验证日志文件路径
        file_path = log_config.get('file')
        if file_path and not isinstance(file_path, str):
            raise ConfigError("日志文件路径应为字符串类型")
            
        # 验证其他日志选项
        max_size = log_config.get('max_size')
        if max_size is not None:
            if not isinstance(max_size, int) or max_size <= 0:
                raise ConfigError("max_size选项应为正整数")
                
        backup_count = log_config.get('backup_count')
        if backup_count is not None:
            if not isinstance(backup_count, int) or backup_count < 0:
                raise ConfigError("backup_count选项应为非负整数") 