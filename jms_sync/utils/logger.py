#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志模块，提供日志记录功能。

特性：
- 统一的日志格式和级别
- 支持结构化日志记录
- 支持日志轮转机制
- 支持按不同级别记录到不同文件
- 提供日志装饰器用于记录函数调用
- 支持JSON格式化的日志输出
"""

import os
import sys
import json
import time
import logging
import logging.handlers
import functools
import threading
import inspect
from datetime import datetime
from typing import Optional, Dict, Any, Union, List, Callable, TypeVar, cast
import uuid

# 类型变量定义
F = TypeVar('F', bound=Callable[..., Any])

# 日志格式常量
DEFAULT_LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s'
DETAILED_LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] [%(threadName)s] - %(message)s'
JSON_LOG_FORMAT = '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "line": %(lineno)d, "message": %(message)s}'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 日志级别映射
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# 默认的日志轮转设置
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_BACKUP_COUNT = 5

# 上下文跟踪
class LogContext:
    """日志上下文，用于跟踪请求或任务"""
    _local = threading.local()
    
    @classmethod
    def get_context(cls) -> Dict[str, Any]:
        """获取当前线程的上下文"""
        if not hasattr(cls._local, 'context'):
            cls._local.context = {
                'trace_id': str(uuid.uuid4()),
                'start_time': datetime.now().isoformat()
            }
        return cls._local.context
    
    @classmethod
    def set_context_value(cls, key: str, value: Any) -> None:
        """设置上下文值"""
        context = cls.get_context()
        context[key] = value
    
    @classmethod
    def get_context_value(cls, key: str, default: Any = None) -> Any:
        """获取上下文值"""
        context = cls.get_context()
        return context.get(key, default)
    
    @classmethod
    def clear_context(cls) -> None:
        """清除当前线程的上下文"""
        if hasattr(cls._local, 'context'):
            del cls._local.context

# 结构化日志格式化器
class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器"""
    
    def __init__(self, fmt=None, datefmt=None, style='%', include_context=True):
        """
        初始化格式化器
        
        Args:
            fmt: 日志格式
            datefmt: 日期格式
            style: 格式化样式
            include_context: 是否包含上下文
        """
        super().__init__(fmt, datefmt, style)
        self.include_context = include_context
    
    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录
        
        Args:
            record: 日志记录
            
        Returns:
            str: 格式化后的日志
        """
        # 获取基本日志内容
        msg = super().format(record)
        
        # 获取额外数据
        extras = {}
        for key, value in record.__dict__.items():
            if key.startswith('_') or key in ('args', 'asctime', 'created', 'exc_info', 'exc_text', 
                                           'filename', 'funcName', 'id', 'levelname', 'levelno', 
                                           'lineno', 'module', 'msecs', 'message', 'msg', 'name', 
                                           'pathname', 'process', 'processName', 'relativeCreated', 
                                           'stack_info', 'thread', 'threadName'):
                continue
            extras[key] = value
        
        # 添加上下文
        if self.include_context:
            context = LogContext.get_context()
            if context:
                extras.update(context)
        
        # 如果有额外数据，附加到日志
        if extras:
            json_extras = json.dumps(extras, ensure_ascii=False, default=str)
            return f"{msg} {json_extras}"
        
        return msg

def setup_logger(
    log_level: str = 'INFO',
    log_file: Optional[str] = None,
    log_format: str = DEFAULT_LOG_FORMAT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    detailed: bool = False,
    json_format: bool = False,
    separate_error_log: bool = False
) -> logging.Logger:
    """
    设置日志记录器。

    Args:
        log_level: 日志级别，可选值：DEBUG, INFO, WARNING, ERROR, CRITICAL
        log_file: 日志文件路径，如果为None则只输出到控制台
        log_format: 日志格式
        max_bytes: 日志文件最大大小，超过后将轮转
        backup_count: 保留的日志文件数量
        detailed: 是否使用详细日志格式（包含线程信息）
        json_format: 是否使用JSON格式输出日志
        separate_error_log: 是否将ERROR及以上级别的日志单独记录到一个文件

    Returns:
        logging.Logger: 日志记录器
    """
    # 获取根日志记录器
    logger = logging.getLogger()
    
    # 设置日志级别
    level = LOG_LEVEL_MAP.get(log_level.upper(), logging.INFO)
    logger.setLevel(level)
    
    # 清除已有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 选择日志格式
    if json_format:
        log_format = JSON_LOG_FORMAT
    elif detailed:
        log_format = DETAILED_LOG_FORMAT
    
    # 创建格式化器
    if json_format:
        formatter = StructuredLogFormatter(
            fmt=f"%(asctime)s {log_format}",
            datefmt=LOG_DATE_FORMAT
        )
    else:
        formatter = logging.Formatter(log_format, LOG_DATE_FORMAT)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 如果指定了日志文件，添加文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 使用RotatingFileHandler进行日志轮转
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 如果需要单独的错误日志文件
        if separate_error_log:
            # 创建错误日志文件路径
            error_log_file = os.path.splitext(log_file)[0] + '_error.log'
            
            # 创建只接收ERROR及以上级别的日志处理器
            error_handler = logging.handlers.RotatingFileHandler(
                error_log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            error_handler.setFormatter(formatter)
            error_handler.setLevel(logging.ERROR)
            logger.addHandler(error_handler)
    
    return logger


def get_logger(name: str, log_level: Optional[str] = None) -> logging.Logger:
    """
    获取指定名称的日志记录器。

    Args:
        name: 日志记录器名称
        log_level: 可选的日志级别，如果指定则覆盖默认级别

    Returns:
        logging.Logger: 日志记录器
    """
    logger = logging.getLogger(name)
    
    # 如果指定了日志级别，则设置
    if log_level:
        level = LOG_LEVEL_MAP.get(log_level.upper(), None)
        if level is not None:
            logger.setLevel(level)
    
    return logger


class StructuredLogger:
    """
    结构化日志记录器，提供额外的上下文信息记录功能。
    
    使用示例:
    ```python
    logger = StructuredLogger("my_module")
    logger.info("用户登录", user_id=123, ip="192.168.1.1")
    logger.error("操作失败", operation="delete", error_code=404)
    ```
    """
    
    def __init__(self, name: str):
        """
        初始化结构化日志记录器。
        
        Args:
            name: 日志记录器名称
        """
        self.logger = logging.getLogger(name)
        self.context = {}  # 全局上下文
    
    def add_context(self, **kwargs) -> None:
        """
        添加全局上下文信息，这些信息将出现在所有后续的日志记录中。
        
        Args:
            **kwargs: 上下文键值对
        """
        self.context.update(kwargs)
    
    def remove_context(self, *keys) -> None:
        """
        从全局上下文中移除指定的键。
        
        Args:
            *keys: 要移除的上下文键
        """
        for key in keys:
            self.context.pop(key, None)
    
    def clear_context(self) -> None:
        """清除所有全局上下文信息。"""
        self.context.clear()
    
    def _format_structured_message(self, message: str, **kwargs) -> str:
        """
        格式化结构化消息。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        
        Returns:
            str: 格式化后的结构化消息
        """
        # 合并全局上下文和当前上下文
        data = {**self.context, **kwargs}
        
        if not data:
            return message
            
        # 格式化为JSON
        json_part = json.dumps(data, ensure_ascii=False)
        return f"{message} {json_part}"
    
    def debug(self, message: str, **kwargs) -> None:
        """
        记录DEBUG级别的结构化日志。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(self._format_structured_message(message, **kwargs))
    
    def info(self, message: str, **kwargs) -> None:
        """
        记录INFO级别的结构化日志。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(self._format_structured_message(message, **kwargs))
    
    def warning(self, message: str, **kwargs) -> None:
        """
        记录WARNING级别的结构化日志。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.WARNING):
            self.logger.warning(self._format_structured_message(message, **kwargs))
    
    def error(self, message: str, **kwargs) -> None:
        """
        记录ERROR级别的结构化日志。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.ERROR):
            self.logger.error(self._format_structured_message(message, **kwargs))
    
    def critical(self, message: str, **kwargs) -> None:
        """
        记录CRITICAL级别的结构化日志。
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.CRITICAL):
            self.logger.critical(self._format_structured_message(message, **kwargs))
    
    def exception(self, message: str, exc_info: bool = True, **kwargs) -> None:
        """
        记录带异常信息的ERROR级别结构化日志。
        
        Args:
            message: 日志消息
            exc_info: 是否包含异常信息
            **kwargs: 结构化数据
        """
        if self.logger.isEnabledFor(logging.ERROR):
            formatted_message = self._format_structured_message(message, **kwargs)
            self.logger.exception(formatted_message)


class LoggerMixin:
    """
    日志混入类，为类提供日志记录功能。
    
    使用示例:
    ```python
    class MyClass(LoggerMixin):
        def __init__(self):
            super().__init__()
            self.logger.info("初始化完成")
    ```
    """
    
    def __init__(self):
        """初始化日志记录器。"""
        # 使用类的模块名和类名作为日志记录器名称
        self.logger = get_logger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        # 也可以使用结构化日志记录器
        self.structured_logger = StructuredLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
    
    def log_method_call(self, method_name: str, *args, **kwargs) -> None:
        """
        记录方法调用信息。

        Args:
            method_name: 方法名称
            *args: 位置参数
            **kwargs: 关键字参数
        """
        self.logger.debug(f"调用方法 {method_name} - 参数: {args}, 关键字参数: {kwargs}")
    
    def log_execution_time(self, method_name: str, start_time: float, end_time: float) -> None:
        """
        记录方法执行时间。

        Args:
            method_name: 方法名称
            start_time: 开始时间
            end_time: 结束时间
        """
        execution_time = end_time - start_time
        self.logger.debug(f"方法 {method_name} 执行时间: {execution_time:.4f}秒")


def log_function(level: str = 'DEBUG', log_args: bool = True, log_result: bool = False) -> Callable[[F], F]:
    """
    记录函数调用的装饰器。
    
    Args:
        level: 日志级别
        log_args: 是否记录函数参数
        log_result: 是否记录函数返回值
    
    Returns:
        函数装饰器
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger_name = f"{func.__module__}.{func.__qualname__}"
            logger = get_logger(logger_name)
            log_method = getattr(logger, level.lower())
            
            # 记录函数调用
            if log_args:
                args_str = ", ".join([str(arg) for arg in args])
                kwargs_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
                params = f"{args_str}{', ' if args_str and kwargs_str else ''}{kwargs_str}"
                log_method(f"调用函数 {func.__name__}({params})")
            else:
                log_method(f"调用函数 {func.__name__}")
            
            # 记录执行时间
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                
                # 记录函数返回值
                if log_result:
                    log_method(f"函数 {func.__name__} 返回值: {result}")
                
                # 记录执行时间
                execution_time = end_time - start_time
                log_method(f"函数 {func.__name__} 执行时间: {execution_time:.4f}秒")
                
                return result
            except Exception as e:
                end_time = time.time()
                execution_time = end_time - start_time
                logger.exception(f"函数 {func.__name__} 执行异常: {str(e)}, 执行时间: {execution_time:.4f}秒")
                raise
        
        return cast(F, wrapper)
    
    return decorator


def log_dict(logger: logging.Logger, message: str, data: Dict[str, Any], level: str = 'INFO') -> None:
    """
    记录字典数据，格式化输出。

    Args:
        logger: 日志记录器
        message: 日志消息
        data: 要记录的字典数据
        level: 日志级别
    """
    log_func = getattr(logger, level.lower())
    log_func(f"{message}:\n{json.dumps(data, indent=2, ensure_ascii=False)}")


def log_exception(logger: logging.Logger, exc: Exception, message: str = "发生异常") -> None:
    """
    记录异常信息。

    Args:
        logger: 日志记录器
        exc: 异常对象
        message: 日志消息前缀
    """
    import traceback
    logger.error(f"{message}: {exc.__class__.__name__}: {str(exc)}")
    logger.debug(f"异常详情:\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")


def init_default_logging():
    """初始化默认日志配置"""
    setup_logger(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file=os.environ.get("LOG_FILE"),
        structured=True
    ) 