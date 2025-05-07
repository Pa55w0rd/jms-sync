#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
异常模块 - 定义项目中使用的所有异常类型和异常处理工具
"""

import sys
import logging
import traceback
from typing import Type, Dict, Any, List, Union, Optional, Callable, TypeVar, cast
from functools import wraps

# 基础异常类
class JmsSyncError(Exception):
    """JMS-Sync 基础异常类"""
    
    def __init__(self, message: str = "", code: str = "", details: Any = None):
        """
        初始化异常
        
        Args:
            message: 异常消息
            code: 错误代码
            details: 详细信息
        """
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将异常转换为字典
        
        Returns:
            Dict[str, Any]: 异常字典
        """
        result = {
            'error': self.__class__.__name__,
            'message': self.message
        }
        
        if self.code:
            result['code'] = self.code
            
        if self.details:
            result['details'] = self.details
            
        return result


# 配置相关异常
class ConfigError(JmsSyncError):
    """配置错误"""
    pass


class ConfigValidationError(ConfigError):
    """配置验证错误"""
    pass


class ConfigFileError(ConfigError):
    """配置文件错误"""
    pass


# API相关异常
class APIError(JmsSyncError):
    """API错误"""
    
    def __init__(self, message: str = "", code: str = "", details: Any = None, 
                 status_code: int = None, response: Any = None):
        """
        初始化API异常
        
        Args:
            message: 异常消息
            code: 错误代码
            details: 详细信息
            status_code: HTTP状态码
            response: API响应
        """
        super().__init__(message, code, details)
        self.status_code = status_code
        self.response = response
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将异常转换为字典
        
        Returns:
            Dict[str, Any]: 异常字典
        """
        result = super().to_dict()
        
        if self.status_code:
            result['status_code'] = self.status_code
            
        return result


# JumpServer相关异常
class JumpServerError(APIError):
    """JumpServer API错误"""
    pass


class JumpServerAuthError(JumpServerError):
    """JumpServer认证错误"""
    pass


class JumpServerAPIError(JumpServerError):
    """JumpServer API操作错误"""
    pass


class JumpServerResourceNotFound(JumpServerError):
    """JumpServer资源不存在"""
    pass


# 云平台相关异常
class CloudError(APIError):
    """云平台API错误"""
    pass


class CloudAuthError(CloudError):
    """云平台认证错误"""
    pass


class CloudAPIError(CloudError):
    """云平台API操作错误"""
    pass


class CloudResourceNotFound(CloudError):
    """云平台资源不存在"""
    pass


# 平台异常
class AliyunError(CloudError):
    """阿里云错误"""
    pass


class HuaweiError(CloudError):
    """华为云错误"""
    pass


# 同步相关异常
class SyncError(JmsSyncError):
    """同步错误"""
    pass


class AssetSyncError(SyncError):
    """资产同步错误"""
    pass


# 异常分类
RETRYABLE_EXCEPTIONS = (
    # 网络相关临时错误
    ConnectionError,
    TimeoutError,
    # 云服务临时错误
    CloudAPIError,
    # JumpServer临时错误
    JumpServerAPIError
)

NON_RETRYABLE_EXCEPTIONS = (
    # 认证错误
    JumpServerAuthError,
    CloudAuthError,
    # 配置错误
    ConfigError,
    # 资源不存在
    JumpServerResourceNotFound,
    CloudResourceNotFound
)

# 异常处理工具
def is_retryable_exception(exc: Exception) -> bool:
    """
    判断异常是否可重试
    
    Args:
        exc: 异常对象
        
    Returns:
        bool: 是否可重试
    """
    # 检查是否是可重试的异常类型
    for exc_type in RETRYABLE_EXCEPTIONS:
        if isinstance(exc, exc_type):
            return True
    
    # 检查是否是不可重试的异常类型
    for exc_type in NON_RETRYABLE_EXCEPTIONS:
        if isinstance(exc, exc_type):
            return False
    
    # 默认情况下，未知异常不可重试
    return False


def handle_exception(exc: Exception, logger: logging.Logger) -> Dict[str, Any]:
    """
    统一处理异常，记录日志并返回错误信息
    
    Args:
        exc: 异常对象
        logger: 日志记录器
        
    Returns:
        Dict[str, Any]: 包含错误信息的字典
    """
    # 获取错误类型和信息
    exc_type = type(exc).__name__
    exc_msg = str(exc)
    
    # 记录异常堆栈信息
    stack_trace = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # 如果是自定义异常类型，记录错误码和详情
    if isinstance(exc, JmsSyncError):
        result = exc.to_dict()
        log_msg = f"{exc_type}[{exc.code if hasattr(exc, 'code') and exc.code else 'N/A'}]: {exc_msg}"
    else:
        result = {
            'error': exc_type,
            'message': exc_msg
        }
        log_msg = f"{exc_type}: {exc_msg}"
    
    # 记录日志
    if isinstance(exc, (JmsSyncError, APIError)):
        logger.error(log_msg)
        logger.debug(f"异常详情: {stack_trace}")
    else:
        # 未知异常，记录完整堆栈
        logger.exception(log_msg)
    
    # 添加堆栈信息（仅在DEBUG级别）
    if logger.isEnabledFor(logging.DEBUG):
        result['traceback'] = stack_trace.split('\n')
    
    return result


F = TypeVar('F', bound=Callable[..., Any])


def with_error_handling(error_handler: Optional[Callable[[Exception], Any]] = None,
                         default_return: Any = None) -> Callable[[F], F]:
    """
    带错误处理的装饰器，用于自动处理函数中的异常
    
    使用示例:
    ```python
    @with_error_handling(default_return={'success': False})
    def my_function():
        # 函数内容
    ```
    
    Args:
        error_handler: 错误处理函数，接收异常对象，返回处理结果
        default_return: 发生异常时的默认返回值
        
    Returns:
        Callable: 装饰器函数
    """
    def decorator(func: F) -> F:
        logger = logging.getLogger(func.__module__)
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 记录异常
                log_prefix = f"函数 {func.__name__} 执行异常"
                
                if error_handler:
                    # 使用自定义错误处理器
                    try:
                        return error_handler(e)
                    except Exception as handler_error:
                        logger.exception(f"{log_prefix} - 错误处理器也失败了: {str(handler_error)}")
                else:
                    # 使用默认错误处理
                    handle_exception(e, logger)
                
                return default_return
        
        return cast(F, wrapper)
    
    return decorator 