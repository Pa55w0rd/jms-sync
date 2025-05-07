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
- 配置文件管理的日志级别控制
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

# 全局配置对象
_config = None


def set_global_config(config):
    """
    设置全局配置对象
    
    Args:
        config: 配置对象
    """
    global _config
    _config = config


def get_global_config():
    """
    获取全局配置对象
    
    Returns:
        配置对象或None
    """
    return _config


# 配置文件环境配置
def is_production() -> bool:
    """
    判断当前是否为生产环境
    
    Returns:
        bool: 是否为生产环境
    """
    config = get_global_config()
    if config:
        # 尝试从配置文件获取环境配置
        env = config.get('environment', {}).get('type', '').upper()
        return env == 'PRODUCTION'
    else:
        # 兼容模式：如果没有配置对象，则从环境变量获取
        return False


def get_environment_log_level() -> str:
    """
    根据环境获取默认日志级别
    
    Returns:
        str: 默认日志级别
    """
    config = get_global_config()
    if config:
        # 先从配置文件获取日志级别
        log_config = config.get('log', {})
        env_level = log_config.get('level', '').upper()
        if env_level in LOG_LEVEL_MAP:
            return env_level
        
        # 如果没有设置或无效，则根据环境类型设置默认级别
        if is_production():
            return 'INFO'
        else:
            return 'DEBUG'
    else:
        # 兼容模式：如果没有配置对象，则使用默认值
        return 'INFO'


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
            try:
                json_extras = json.dumps(extras, ensure_ascii=False, default=str)
                return f"{msg} {json_extras}"
            except Exception:
                # 如果JSON序列化失败，仅添加trace_id
                trace_id = LogContext.get_context_value('trace_id', 'N/A')
                return f"{msg} [trace_id={trace_id}]"
        
        return msg


def setup_logger(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_format: str = DEFAULT_LOG_FORMAT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    detailed: bool = False,
    json_format: bool = False,
    separate_error_log: bool = False,
    env_aware: bool = True
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
        env_aware: 是否根据环境自动调整日志级别

    Returns:
        logging.Logger: 日志记录器
    """
    # 获取根日志记录器
    logger = logging.getLogger()
    
    # 设置日志级别 - 环境感知
    if env_aware:
        default_level = get_environment_log_level()
        level = LOG_LEVEL_MAP.get(log_level or default_level, logging.INFO)
    else:
        level = LOG_LEVEL_MAP.get(log_level or 'INFO', logging.INFO)
    
    logger.setLevel(level)
    
    # 清除已有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 选择日志格式
    if is_production() and not detailed and not json_format:
        # 生产环境使用简洁格式
        log_format = '%(asctime)s [%(levelname)s] - %(message)s'
    elif json_format:
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
    
    # 特殊处理：减少某些库的日志输出
    if is_production():
        # 在生产环境中，调高一些库的日志级别，减少无用日志
        for lib_logger_name in ['urllib3', 'requests', 'chardet', 'botocore', 'paramiko', 'alibabacloud', 'tea', 'huaweicloud']:
            lib_logger = logging.getLogger(lib_logger_name)
            lib_logger.setLevel(logging.WARNING)
    
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
    # 否则根据环境设置默认级别
    elif not logger.level:
        env_level = get_environment_log_level()
        logger.setLevel(LOG_LEVEL_MAP.get(env_level, logging.INFO))
    
    return logger


class StructuredLogger:
    """
    结构化日志记录器，支持添加结构化数据。
    
    使用示例:
    ```python
    logger = StructuredLogger("my_module")
    logger.info("操作成功", user_id=123, action="login")
    ```
    """
    
    def __init__(self, name: str):
        """
        初始化结构化日志记录器
        
        Args:
            name: 日志记录器名称
        """
        self.logger = get_logger(name)
        self.name = name
        self.context = {}
    
    def add_context(self, **kwargs) -> None:
        """
        添加上下文数据，这些数据将被添加到所有日志中
        
        Args:
            **kwargs: 上下文数据
        """
        self.context.update(kwargs)
    
    def remove_context(self, *keys) -> None:
        """
        移除上下文数据
        
        Args:
            *keys: 要移除的键
        """
        for key in keys:
            if key in self.context:
                del self.context[key]
    
    def clear_context(self) -> None:
        """清除所有上下文数据"""
        self.context.clear()
    
    def _format_structured_message(self, message: str, **kwargs) -> str:
        """
        格式化结构化消息
        
        Args:
            message: 日志消息
            **kwargs: 结构化数据
            
        Returns:
            str: 格式化后的消息
        """
        # 合并上下文和当前调用的关键字参数
        data = {**self.context}
        
        # 添加本次调用的数据（可能覆盖上下文中的同名数据）
        if kwargs:
            data.update(kwargs)
        
        if not data:
            return message
        
        try:
            # 尝试将数据转换为JSON字符串
            json_data = json.dumps(data, ensure_ascii=False, default=str)
            return f"{message} {json_data}"
        except Exception:
            # 如果转换失败，使用简单的字符串表示
            data_str = " ".join([f"{k}={v}" for k, v in data.items()])
            return f"{message} [{data_str}]"
    
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
        记录异常信息。
        
        Args:
            message: 日志消息
            exc_info: 是否包含异常信息
            **kwargs: 结构化数据
        """
        self.logger.exception(self._format_structured_message(message, **kwargs), exc_info=exc_info)


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
        # 在生产环境减少详细日志
        if not is_production() or self.logger.isEnabledFor(logging.DEBUG):
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
        # 根据执行时间长短选择日志级别
        if execution_time > 1.0:  # 执行时间超过1秒，使用INFO级别
            self.logger.info(f"方法 {method_name} 执行时间: {execution_time:.4f}秒")
        else:
            self.logger.debug(f"方法 {method_name} 执行时间: {execution_time:.4f}秒")


def log_function(level: str = 'INFO', log_args: bool = True, log_result: bool = False) -> Callable[[F], F]:
    """
    记录函数调用的装饰器。
    
    推荐使用 jms_sync.utils.decorators.log_function 装饰器替代此函数。
    
    Args:
        level: 日志级别
        log_args: 是否记录函数参数
        log_result: 是否记录函数返回值
    
    Returns:
        函数装饰器
    """
    from jms_sync.utils.decorators import log_function as decorator_log_function
    return decorator_log_function(level=level, log_args=log_args, log_result=log_result)


def log_dict(logger: logging.Logger, message: str, data: Dict[str, Any], level: str = 'INFO') -> None:
    """
    记录字典数据。

    Args:
        logger: 日志记录器
        message: 日志消息
        data: 字典数据
        level: 日志级别
    """
    log_method = getattr(logger, level.lower())
    try:
        # 生产环境格式化为一行，便于日志分析
        if is_production():
            log_method(f"{message}: {json.dumps(data, ensure_ascii=False)}")
        else:
            # 开发环境格式化为多行，便于阅读
            formatted_json = json.dumps(data, ensure_ascii=False, indent=2)
            log_method(f"{message}:\n{formatted_json}")
    except Exception:
        # 如果JSON序列化失败，使用字符串表示
        log_method(f"{message}: {str(data)}")


def log_exception(logger: logging.Logger, exc: Exception, message: str = "发生异常") -> None:
    """
    记录异常信息。
    
    推荐使用 jms_sync.utils.exceptions.handle_exception 函数替代此函数。

    Args:
        logger: 日志记录器
        exc: 异常对象
        message: 日志消息前缀
    """
    from jms_sync.utils.exceptions import handle_exception
    handle_exception(exc, logger)


def init_default_logging(env_aware: bool = True):
    """
    初始化默认日志配置，从配置文件获取日志设置
    
    Args:
        env_aware: 是否启用环境感知
    """
    config = get_global_config()
    
    if config:
        # 从配置文件获取日志配置
        log_config = config.get('log', {})
        log_level = log_config.get('level')
        log_file = log_config.get('file')
        max_bytes = log_config.get('max_size', DEFAULT_MAX_BYTES) * 1024 * 1024  # 配置中以MB为单位
        backup_count = log_config.get('backup_count', DEFAULT_BACKUP_COUNT)
        json_format = log_config.get('json_format', False)
        detailed = log_config.get('detailed', False)
        separate_error_log = log_config.get('separate_error_log', True)
    else:
        # 兼容模式：如果没有配置对象，则使用默认值或环境变量
        log_level = os.environ.get("LOG_LEVEL")
        log_file = os.environ.get("LOG_FILE")
        max_bytes = DEFAULT_MAX_BYTES
        backup_count = DEFAULT_BACKUP_COUNT
        json_format = os.environ.get("JSON_LOGS", "").lower() in ("true", "1", "yes")
        detailed = os.environ.get("DETAILED_LOGS", "").lower() in ("true", "1", "yes")
        separate_error_log = True
    
    # 设置日志记录器
    setup_logger(
        log_level=log_level,
        log_file=log_file,
        max_bytes=max_bytes,
        backup_count=backup_count,
        json_format=json_format,
        detailed=detailed,
        env_aware=env_aware,
        separate_error_log=separate_error_log
    )