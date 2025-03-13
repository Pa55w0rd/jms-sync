#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置加载器，负责加载和管理配置文件。
"""

import os
import yaml
import json
import logging
from typing import Dict, Any, List, Optional, Union, Set, TypeVar, Generic, cast
from pathlib import Path

from jms_sync.utils.exceptions import ConfigError
from jms_sync.utils.logger import get_logger
from jms_sync.config.validator import ConfigValidator

logger = get_logger(__name__)

T = TypeVar('T')

class Config:
    """
    配置类，用于加载、验证和管理配置。
    
    提供以下功能：
    - 从YAML文件加载配置
    - 支持环境变量替换
    - 配置验证
    - 字典形式的访问方式
    - 配置保存
    
    使用示例:
    ```python
    config = Config('config.yaml')
    jumpserver_url = config['jumpserver']['base_url']
    ```
    """
    
    def __init__(self, config_file: str):
        """
        初始化配置类。
        
        Args:
            config_file: 配置文件路径，支持绝对路径和相对路径
        
        Raises:
            ConfigError: 配置文件不存在或加载失败
        """
        self.config_file = config_file
        self.validator = ConfigValidator()
        self.config_data = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件。
        
        Returns:
            Dict[str, Any]: 加载并处理后的配置数据
        
        Raises:
            ConfigError: 配置文件不存在或格式错误
        """
        if not os.path.exists(self.config_file):
            raise ConfigError(f"配置文件不存在: {self.config_file}")
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                raise ConfigError(f"配置文件为空: {self.config_file}")
            
            # 验证配置
            self.validator.validate(config)
            
            # 处理环境变量
            config = self._process_env_vars(config)
            
            logger.debug(f"成功加载配置文件: {self.config_file}")
            return config
            
        except yaml.YAMLError as e:
            raise ConfigError(f"配置文件格式错误: {str(e)}", original_exception=e)
        except ConfigError:
            # 直接传递ConfigError
            raise
        except Exception as e:
            raise ConfigError(f"加载配置文件失败: {str(e)}", original_exception=e)
    
    def _process_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理配置中的环境变量引用。
        
        支持格式: ${ENV_NAME} 或 ${ENV_NAME:default_value}
        
        Args:
            config: 原始配置数据
            
        Returns:
            Dict[str, Any]: 处理环境变量后的配置数据
        """
        def _process_value(value: Any) -> Any:
            """处理单个值"""
            if isinstance(value, str) and '${' in value and '}' in value:
                # 处理 ${ENV_NAME} 或 ${ENV_NAME:default_value}
                start = value.find('${')
                end = value.find('}', start)
                if start != -1 and end != -1:
                    env_str = value[start+2:end]
                    if ':' in env_str:
                        env_name, default = env_str.split(':', 1)
                    else:
                        env_name, default = env_str, ""
                    
                    env_value = os.environ.get(env_name, default)
                    return value[:start] + env_value + value[end+1:]
            return value
        
        def _process_dict(d: Dict[str, Any]) -> Dict[str, Any]:
            """递归处理字典"""
            result = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    result[k] = _process_dict(v)
                elif isinstance(v, list):
                    result[k] = _process_list(v)
                else:
                    result[k] = _process_value(v)
            return result
        
        def _process_list(l: List[Any]) -> List[Any]:
            """递归处理列表"""
            result = []
            for item in l:
                if isinstance(item, dict):
                    result.append(_process_dict(item))
                elif isinstance(item, list):
                    result.append(_process_list(item))
                else:
                    result.append(_process_value(item))
            return result
        
        return _process_dict(config)
    
    def get(self, key: str, default: T = None) -> Union[Any, T]:
        """
        获取配置值，支持使用点号分隔的键路径。
        
        Args:
            key: 配置键路径，例如 "jumpserver.base_url"
            default: 默认值，如果键不存在则返回此值
            
        Returns:
            配置值或默认值
        """
        try:
            return self[key]
        except KeyError:
            return default
    
    def __getitem__(self, key: str) -> Any:
        """
        通过[]操作符获取配置值，支持使用点号分隔的键路径。
        
        Args:
            key: 配置键路径，例如 "jumpserver.base_url"
            
        Returns:
            Any: 配置值
            
        Raises:
            KeyError: 键不存在
        """
        if '.' in key:
            parts = key.split('.')
            value = self.config_data
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    raise KeyError(f"配置键 '{key}' 不存在")
            return value
        elif key in self.config_data:
            return self.config_data[key]
        else:
            raise KeyError(f"配置键 '{key}' 不存在")
    
    def __contains__(self, key: str) -> bool:
        """
        检查配置键是否存在。
        
        Args:
            key: 配置键路径，例如 "jumpserver.base_url"
            
        Returns:
            bool: 键是否存在
        """
        try:
            self[key]
            return True
        except KeyError:
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典。
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self.config_data
    
    def save(self, file_path: Optional[str] = None) -> None:
        """
        保存配置到文件。
        
        Args:
            file_path: 文件路径，如果为None则使用初始化时的路径
            
        Raises:
            ConfigError: 保存失败
        """
        try:
            path = file_path or self.config_file
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, allow_unicode=True)
                
            logger.debug(f"配置已保存到: {path}")
        except Exception as e:
            raise ConfigError(f"保存配置失败: {str(e)}", cause=e)

def load_config(config_file: str) -> Config:
    """
    加载配置文件的便捷函数。
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        Config: 配置对象
    """
    return Config(config_file) 