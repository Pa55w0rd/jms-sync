#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
缓存工具模块，提供内存缓存和文件缓存功能。

特性：
- 支持内存缓存和文件缓存
- 支持TTL（生存时间）
- 支持键前缀
- 线程安全
- 支持缓存统计
"""

import os
import json
import time
import pickle
import hashlib
import logging
import threading
import functools
from typing import Dict, Any, Optional, Callable, TypeVar, Generic, Union, List, Tuple, cast

from jms_sync.utils.logger import get_logger

# 类型变量
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])

logger = get_logger(__name__)


class Cache:
    """
    缓存基类，定义缓存的基本接口。
    """
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值。
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            Any: 缓存值或默认值
        """
        raise NotImplementedError("子类必须实现get方法")
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存值。
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 生存时间（秒）
        """
        raise NotImplementedError("子类必须实现set方法")
    
    def delete(self, key: str) -> bool:
        """
        删除缓存值。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 删除是否成功
        """
        raise NotImplementedError("子类必须实现delete方法")
    
    def clear(self) -> None:
        """
        清除所有缓存。
        """
        raise NotImplementedError("子类必须实现clear方法")
    
    def has(self, key: str) -> bool:
        """
        检查键是否存在于缓存中。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 键是否存在
        """
        raise NotImplementedError("子类必须实现has方法")
    
    def stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息。
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        raise NotImplementedError("子类必须实现stats方法")


class MemoryCache(Cache):
    """
    内存缓存实现。
    
    使用示例:
    ```python
    cache = MemoryCache(prefix="my_app")
    cache.set("user:123", user_data, ttl=3600)  # 缓存1小时
    user = cache.get("user:123")
    ```
    """
    
    def __init__(self, prefix: str = "", default_ttl: Optional[int] = None):
        """
        初始化内存缓存。
        
        Args:
            prefix: 键前缀
            default_ttl: 默认生存时间（秒）
        """
        self.prefix = prefix
        self.default_ttl = default_ttl
        self.cache: Dict[str, Tuple[Any, Optional[float]]] = {}  # 值和过期时间
        self.lock = threading.RLock()  # 可重入锁
        self.hits = 0
        self.misses = 0
    
    def _make_key(self, key: str) -> str:
        """
        生成带前缀的键。
        
        Args:
            key: 原始键
            
        Returns:
            str: 带前缀的键
        """
        return f"{self.prefix}:{key}" if self.prefix else key
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值。
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            Any: 缓存值或默认值
        """
        prefixed_key = self._make_key(key)
        
        with self.lock:
            if prefixed_key in self.cache:
                value, expires_at = self.cache[prefixed_key]
                
                # 检查是否已过期
                if expires_at is not None and time.time() > expires_at:
                    # 已过期，删除并返回默认值
                    del self.cache[prefixed_key]
                    self.misses += 1
                    return default
                
                # 未过期，返回值
                self.hits += 1
                return value
            
            # 键不存在
            self.misses += 1
            return default
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存值。
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 生存时间（秒），如果为None则使用默认TTL
        """
        prefixed_key = self._make_key(key)
        ttl_value = ttl if ttl is not None else self.default_ttl
        
        with self.lock:
            if ttl_value is not None:
                expires_at = time.time() + ttl_value
            else:
                expires_at = None
            
            self.cache[prefixed_key] = (value, expires_at)
    
    def delete(self, key: str) -> bool:
        """
        删除缓存值。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 删除是否成功
        """
        prefixed_key = self._make_key(key)
        
        with self.lock:
            if prefixed_key in self.cache:
                del self.cache[prefixed_key]
                return True
            return False
    
    def clear(self) -> None:
        """
        清除所有缓存。
        """
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def has(self, key: str) -> bool:
        """
        检查键是否存在于缓存中且未过期。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 键是否存在且未过期
        """
        prefixed_key = self._make_key(key)
        
        with self.lock:
            if prefixed_key in self.cache:
                _, expires_at = self.cache[prefixed_key]
                
                # 检查是否已过期
                if expires_at is not None and time.time() > expires_at:
                    # 已过期，删除并返回False
                    del self.cache[prefixed_key]
                    return False
                
                # 未过期
                return True
            
            # 键不存在
            return False
    
    def cleanup(self) -> int:
        """
        清理过期的缓存项。
        
        Returns:
            int: 清理的缓存项数量
        """
        now = time.time()
        count = 0
        
        with self.lock:
            expired_keys = [
                key for key, (_, expires_at) in self.cache.items()
                if expires_at is not None and now > expires_at
            ]
            
            for key in expired_keys:
                del self.cache[key]
                count += 1
        
        return count
    
    def stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息。
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        with self.lock:
            total = self.hits + self.misses
            hit_ratio = self.hits / total if total > 0 else 0
            
            return {
                'type': 'memory',
                'size': len(self.cache),
                'hits': self.hits,
                'misses': self.misses,
                'hit_ratio': hit_ratio,
                'prefix': self.prefix
            }


class FileCache(Cache):
    """
    文件缓存实现，将缓存数据持久化到文件系统。
    
    使用示例:
    ```python
    cache = FileCache('/tmp/my_cache', prefix="my_app")
    cache.set("user:123", user_data, ttl=3600)  # 缓存1小时
    user = cache.get("user:123")
    ```
    """
    
    def __init__(self, cache_dir: str, prefix: str = "", default_ttl: Optional[int] = None):
        """
        初始化文件缓存。
        
        Args:
            cache_dir: 缓存目录
            prefix: 键前缀
            default_ttl: 默认生存时间（秒）
        """
        self.cache_dir = cache_dir
        self.prefix = prefix
        self.default_ttl = default_ttl
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        
        # 确保缓存目录存在
        os.makedirs(cache_dir, exist_ok=True)
    
    def _make_key(self, key: str) -> str:
        """
        根据键生成文件名。
        
        Args:
            key: 缓存键
            
        Returns:
            str: 文件路径
        """
        # 使用MD5哈希避免文件名问题
        prefixed_key = f"{self.prefix}:{key}" if self.prefix else key
        hashed_key = hashlib.md5(prefixed_key.encode()).hexdigest()
        return os.path.join(self.cache_dir, hashed_key)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值。
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            Any: 缓存值或默认值
        """
        file_path = self._make_key(key)
        
        if not os.path.exists(file_path):
            self.misses += 1
            return default
        
        try:
            with open(file_path, 'rb') as f:
                data = pickle.load(f)
            
            # 检查过期时间
            if 'expires_at' in data and data['expires_at'] is not None:
                if time.time() > data['expires_at']:
                    # 已过期，删除文件并返回默认值
                    os.remove(file_path)
                    self.misses += 1
                    return default
            
            # 未过期，返回值
            self.hits += 1
            return data['value']
        except (IOError, pickle.PickleError, KeyError) as e:
            logger.error(f"获取缓存失败: {str(e)}")
            self.misses += 1
            return default
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存值。
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 生存时间（秒），如果为None则使用默认TTL
        """
        file_path = self._make_key(key)
        ttl_value = ttl if ttl is not None else self.default_ttl
        
        data = {
            'key': key,
            'value': value,
            'created_at': time.time()
        }
        
        if ttl_value is not None:
            data['expires_at'] = time.time() + ttl_value
        else:
            data['expires_at'] = None
        
        try:
            with open(file_path, 'wb') as f:
                pickle.dump(data, f)
        except (IOError, pickle.PickleError) as e:
            logger.error(f"设置缓存失败: {str(e)}")
    
    def delete(self, key: str) -> bool:
        """
        删除缓存值。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 删除是否成功
        """
        file_path = self._make_key(key)
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                return True
            except IOError as e:
                logger.error(f"删除缓存失败: {str(e)}")
                return False
        
        return False
    
    def clear(self) -> None:
        """
        清除所有缓存。
        """
        try:
            # 遍历缓存目录，删除所有文件
            for filename in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            
            self.hits = 0
            self.misses = 0
        except IOError as e:
            logger.error(f"清除缓存失败: {str(e)}")
    
    def has(self, key: str) -> bool:
        """
        检查键是否存在于缓存中且未过期。
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 键是否存在且未过期
        """
        file_path = self._make_key(key)
        
        if not os.path.exists(file_path):
            return False
        
        try:
            with open(file_path, 'rb') as f:
                data = pickle.load(f)
            
            # 检查过期时间
            if 'expires_at' in data and data['expires_at'] is not None:
                if time.time() > data['expires_at']:
                    # 已过期，删除文件并返回False
                    os.remove(file_path)
                    return False
            
            # 未过期
            return True
        except (IOError, pickle.PickleError, KeyError):
            return False
    
    def cleanup(self) -> int:
        """
        清理过期的缓存文件。
        
        Returns:
            int: 清理的缓存文件数量
        """
        count = 0
        now = time.time()
        
        try:
            for filename in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, filename)
                
                if not os.path.isfile(file_path):
                    continue
                
                try:
                    with open(file_path, 'rb') as f:
                        data = pickle.load(f)
                    
                    # 检查过期时间
                    if 'expires_at' in data and data['expires_at'] is not None:
                        if now > data['expires_at']:
                            os.remove(file_path)
                            count += 1
                except (IOError, pickle.PickleError):
                    # 文件损坏，删除
                    os.remove(file_path)
                    count += 1
        except IOError as e:
            logger.error(f"清理缓存失败: {str(e)}")
        
        return count
    
    def stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息。
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        try:
            files = [f for f in os.listdir(self.cache_dir) if os.path.isfile(os.path.join(self.cache_dir, f))]
            total = self.hits + self.misses
            hit_ratio = self.hits / total if total > 0 else 0
            
            return {
                'type': 'file',
                'directory': self.cache_dir,
                'size': len(files),
                'hits': self.hits,
                'misses': self.misses,
                'hit_ratio': hit_ratio,
                'prefix': self.prefix
            }
        except IOError as e:
            logger.error(f"获取缓存统计失败: {str(e)}")
            return {
                'type': 'file',
                'directory': self.cache_dir,
                'error': str(e)
            }


def cached(cache: Cache, key: Optional[str] = None, ttl: Optional[int] = None) -> Callable[[F], F]:
    """
    函数结果缓存装饰器。
    
    使用示例:
    ```python
    cache = MemoryCache()
    
    @cached(cache, ttl=60)
    def fetch_user(user_id):
        # 从数据库获取用户...
        return user_data
    ```
    
    Args:
        cache: 缓存对象
        key: 缓存键模板，可以包含{参数名}占位符
        ttl: 缓存生存时间
    
    Returns:
        装饰函数
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            if key is not None:
                # 使用提供的键模板
                cache_key = key.format(*args, **kwargs)
            else:
                # 使用函数名和参数生成键
                arg_values = [str(arg) for arg in args]
                kwarg_values = [f"{k}={v}" for k, v in sorted(kwargs.items())]
                args_str = ",".join(arg_values + kwarg_values)
                cache_key = f"{func.__module__}.{func.__qualname__}({args_str})"
            
            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 存入缓存
            cache.set(cache_key, result, ttl)
            
            return result
        
        return cast(F, wrapper)
    
    return decorator 