#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
异常类模块 - 定义项目中使用的异常类
"""

import traceback
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class JmsSyncError(Exception):
    """JMS-Sync基础异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        """
        初始化JMS-Sync异常
        
        Args:
            message: 异常消息
            original_exception: 原始异常
        """
        self.message = message
        self.original_exception = original_exception
        
        # 记录详细的错误信息和堆栈跟踪
        if original_exception:
            stack_trace = ''.join(traceback.format_exception(type(original_exception), original_exception, original_exception.__traceback__))
            logger.debug(f"原始异常: {stack_trace}")
            
        super().__init__(self.message)
        
    def __str__(self):
        if self.original_exception:
            return f"{self.message} (原因: {str(self.original_exception)})"
        return self.message

class ConfigError(JmsSyncError):
    """配置错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"配置错误: {message}", original_exception)

class CloudError(JmsSyncError):
    """云平台错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"云平台错误: {message}", original_exception)

class AliyunError(CloudError):
    """阿里云错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"阿里云错误: {message}", original_exception)

class HuaweiError(CloudError):
    """华为云错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"华为云错误: {message}", original_exception)

class JumpServerError(JmsSyncError):
    """JumpServer错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"JumpServer错误: {message}", original_exception)

class JumpServerAuthError(JumpServerError):
    """JumpServer认证错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"认证错误: {message}", original_exception)

class JumpServerAPIError(JumpServerError):
    """JumpServer API错误异常类"""
    
    def __init__(self, message: str, status_code: int = None, response: str = None, original_exception: Exception = None):
        """
        初始化JumpServer API异常
        
        Args:
            message: 异常消息
            status_code: HTTP状态码
            response: 响应内容
            original_exception: 原始异常
        """
        self.status_code = status_code
        self.response = response
        super().__init__(message, original_exception)
        
    def __str__(self):
        if self.original_exception:
            return f"API错误 (状态码: {self.status_code}): {self.message} (原因: {str(self.original_exception)})"
        return f"API错误 (状态码: {self.status_code}): {self.message}"

class SyncError(JmsSyncError):
    """同步错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"同步错误: {message}", original_exception) 