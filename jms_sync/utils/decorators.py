#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
装饰器模块，提供各种实用的装饰器。
"""

import time
import functools
import hashlib
import json
import logging
import inspect
from datetime import datetime, timedelta
from typing import Callable, Dict, Tuple, Any, Type, Optional, List, Union, Set

logger = logging.getLogger(__name__)

# 缓存存储
_CACHE: Dict[str, Tuple[Any, datetime]] = {}


def deprecated(reason: str):
    """
    标记函数或方法为已弃用。

    Args:
        reason: 弃用原因

    Returns:
        Callable: 装饰器函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger.warning(f"调用已弃用的函数 {func.__name__}: {reason}")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def _generate_cache_key(func: Callable, args: Tuple, kwargs: Dict) -> str:
    """
    生成缓存键。

    Args:
        func: 被装饰的函数
        args: 位置参数
        kwargs: 关键字参数

    Returns:
        str: 缓存键
    """
    # 获取函数的完整限定名称
    func_name = f"{func.__module__}.{func.__qualname__}"
    
    # 序列化参数
    try:
        args_str = json.dumps(args, sort_keys=True)
    except (TypeError, ValueError):
        # 如果参数无法序列化，使用字符串表示
        args_str = str(args)
    
    try:
        kwargs_str = json.dumps(kwargs, sort_keys=True)
    except (TypeError, ValueError):
        # 如果参数无法序列化，使用字符串表示
        kwargs_str = str(kwargs)
    
    # 组合并计算哈希
    key_data = f"{func_name}:{args_str}:{kwargs_str}"
    return hashlib.md5(key_data.encode()).hexdigest()


def cache_result(ttl: int = 300, cache_none: bool = False, cache_errors: bool = False):
    """
    缓存函数结果的装饰器。

    Args:
        ttl: 缓存生存时间（秒）
        cache_none: 是否缓存None结果
        cache_errors: 是否缓存异常结果

    Returns:
        Callable: 装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        """装饰器函数"""
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            """包装函数"""
            # 生成缓存键
            cache_key = _generate_cache_key(func, args, kwargs)
            
            # 检查缓存
            if cache_key in _CACHE:
                result, expiry = _CACHE[cache_key]
                if datetime.now() < expiry:
                    return result
                # 缓存已过期，删除
                del _CACHE[cache_key]
            
            # 执行函数
            try:
                result = func(*args, **kwargs)
                
                # 缓存结果（如果不是None或者允许缓存None）
                if result is not None or cache_none:
                    _CACHE[cache_key] = (result, datetime.now() + timedelta(seconds=ttl))
                
                return result
            except Exception as e:
                if cache_errors:
                    # 缓存异常结果
                    _CACHE[cache_key] = (e, datetime.now() + timedelta(seconds=ttl))
                raise
        
        # 添加清除缓存的方法
        def clear_cache():
            """清除此函数的所有缓存"""
            func_name = f"{func.__module__}.{func.__qualname__}"
            keys_to_delete = [k for k in _CACHE.keys() if k.startswith(func_name)]
            for key in keys_to_delete:
                del _CACHE[key]
        
        wrapper.clear_cache = clear_cache
        return wrapper
    
    return decorator


def retry(
    max_retries: int = 3, 
    retry_interval: int = 2, 
    backoff_factor: float = 1.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    retry_on_result: Optional[Callable[[Any], bool]] = None
):
    """
    重试装饰器，在函数执行失败时自动重试。

    Args:
        max_retries: 最大重试次数
        retry_interval: 初始重试间隔（秒）
        backoff_factor: 重试间隔的增长因子
        exceptions: 需要重试的异常类型
        retry_on_result: 根据结果决定是否重试的函数

    Returns:
        Callable: 装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        """装饰器函数"""
        
        logger = logging.getLogger(func.__module__)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            """包装函数"""
            retry_count = 0
            current_interval = retry_interval
            
            while True:
                try:
                    result = func(*args, **kwargs)
                    
                    # 检查结果是否需要重试
                    if retry_on_result and retry_on_result(result):
                        if retry_count >= max_retries:
                            logger.error(f"函数 {func.__name__} 返回需要重试的结果，已达到最大重试次数")
                            return result
                        
                        retry_count += 1
                        logger.warning(f"函数 {func.__name__} 返回需要重试的结果，将在{current_interval}秒后重试({retry_count}/{max_retries})")
                        time.sleep(current_interval)
                        current_interval *= backoff_factor
                        continue
                    
                    return result
                except exceptions as e:
                    if retry_count >= max_retries:
                        logger.error(f"函数 {func.__name__} 执行失败，已达到最大重试次数: {str(e)}")
                        raise
                    
                    retry_count += 1
                    logger.warning(f"函数 {func.__name__} 执行失败，将在{current_interval}秒后重试({retry_count}/{max_retries}): {str(e)}")
                    time.sleep(current_interval)
                    current_interval *= backoff_factor
        
        return wrapper
    
    return decorator


def log_function(level: str = 'INFO', log_args: bool = True, log_result: bool = False, log_time: bool = True, time_format: str = ':.2f'):
    """
    增强版日志记录装饰器，整合了执行时间记录和参数记录功能。

    Args:
        level: 日志级别
        log_args: 是否记录函数参数
        log_result: 是否记录函数返回值
        log_time: 是否记录执行时间
        time_format: 时间格式化字符串

    Returns:
        Callable: 装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        """装饰器函数"""
        
        logger = logging.getLogger(func.__module__)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            """包装函数"""
            # 记录函数调用
            if log_args:
                args_str = ", ".join([str(arg) for arg in args])
                kwargs_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
                params = f"{args_str}{', ' if args_str and kwargs_str else ''}{kwargs_str}"
                getattr(logger, level.lower())(f"调用函数 {func.__name__}({params})")
            else:
                getattr(logger, level.lower())(f"调用函数 {func.__name__}")
            
            # 记录执行时间
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                
                # 记录函数返回值
                if log_result:
                    getattr(logger, level.lower())(f"函数 {func.__name__} 返回值: {result}")
                
                # 记录执行时间
                if log_time:
                    execution_time = end_time - start_time
                    getattr(logger, level.lower())(f"函数 {func.__name__} 执行时间: {execution_time:{time_format}}秒")
                
                return result
            except Exception as e:
                if log_time:
                    end_time = time.time()
                    execution_time = end_time - start_time
                    logger.exception(f"函数 {func.__name__} 执行异常: {str(e)}, 执行时间: {execution_time:{time_format}}秒")
                else:
                    logger.exception(f"函数 {func.__name__} 执行异常: {str(e)}")
                raise
        
        return wrapper
    
    return decorator


@deprecated("请使用功能更强大的log_function装饰器代替")
def log_execution_time(level: str = 'INFO'):
    """
    记录函数执行时间的装饰器(已弃用)。
    
    请使用功能更强大的log_function装饰器代替，例如:
    @log_function(level='INFO', log_args=False, log_time=True)

    Args:
        level: 日志级别

    Returns:
        Callable: 装饰器函数
    """
    return log_function(level=level, log_args=False, log_result=False, log_time=True)


def validate_params(**param_validators):
    """
    参数验证装饰器，用于验证函数参数。

    Args:
        **param_validators: 参数名和验证函数的映射

    Returns:
        Callable: 装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        """装饰器函数"""
        
        # 获取函数签名
        sig = inspect.signature(func)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """包装函数"""
            # 将位置参数和关键字参数绑定到函数签名
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            # 验证参数
            for param_name, validator in param_validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    if not validator(value):
                        raise ValueError(f"参数 '{param_name}' 验证失败: {value}")
            
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def singleton(cls):
    """
    单例模式装饰器，确保类只有一个实例。

    Args:
        cls: 要装饰的类

    Returns:
        Type: 装饰后的类
    """
    instances = {}
    
    @functools.wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    return get_instance 