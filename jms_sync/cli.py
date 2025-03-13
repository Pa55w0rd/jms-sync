#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JMS-Sync 命令行入口
"""

import os
import sys
import argparse
import logging
import time
import json
from typing import Dict, Any

from jms_sync.sync.sync_manager import SyncManager
from jms_sync.utils.logger import setup_logger
from jms_sync.utils.exceptions import JmsSyncError

def parse_args():
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(description='JMS-Sync: 同步云平台资产到JumpServer堡垒机')
    
    parser.add_argument('-c', '--config', 
                        default='config.yaml',
                        help='配置文件路径 (默认: config.yaml)')
    
    parser.add_argument('-l', '--log-level',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO',
                        help='日志级别 (默认: INFO)')
    
    parser.add_argument('--log-file',
                        default='logs/jms-sync.log',
                        help='日志文件路径 (默认: logs/jms-sync.log)')
    
    parser.add_argument('--no-log-file',
                        action='store_true',
                        help='不输出日志到文件')
    
    parser.add_argument('-r', '--retries',
                        type=int,
                        default=3,
                        help='同步失败时的最大重试次数 (默认: 3)')
    
    parser.add_argument('-i', '--interval',
                        type=int,
                        default=5,
                        help='重试间隔时间(秒) (默认: 5)')
    
    parser.add_argument('-o', '--output',
                        help='将同步结果输出到指定的JSON文件')
    
    return parser.parse_args()

def save_result(result: Dict[str, Any], output_file: str):
    """
    保存同步结果到文件
    
    Args:
        result: 同步结果
        output_file: 输出文件路径
    """
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # 保存结果到文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

def main():
    """主程序入口点"""
    # 解析命令行参数
    args = parse_args()
    
    # 获取root logger
    logger = logging.getLogger()
    
    # 确保日志目录存在
    if args.log_file:
        log_dir = os.path.dirname(args.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
    
    # 设置日志级别
    log_level = args.log_level.upper()
    if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
        logger.warning(f"无效的日志级别: {log_level}，将使用INFO")
        log_level = 'INFO'
    logger.setLevel(getattr(logging, log_level))
    
    # 设置日志格式
    log_format = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    # 添加文件处理器（如果指定了日志文件）
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file, encoding='utf-8')
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)
    
    # 记录开始信息
    logger.info(f"JMS-Sync 开始运行")
    logger.info(f"配置文件: {args.config}")
    
    try:
        # 检查配置文件是否存在
        if not os.path.exists(args.config):
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)
            
        # 创建同步管理器
        sync_manager = SyncManager(args.config)
        
        # 运行同步管理器
        start_time = time.time()
        result = sync_manager.run_with_retry(max_retries=args.retries, retry_interval=args.interval)
        end_time = time.time()
        
        # 计算运行时间
        duration = end_time - start_time
        
        # 输出同步结果
        logger.info(f"同步完成，耗时: {duration:.2f}秒")
        
        # 统计同步结果
        total_created = 0
        total_updated = 0
        total_deleted = 0
        total_failed = 0
        cloud_results = result.get('results', {})
        
        for cloud_name, cloud_result in cloud_results.items():
            # 检查cloud_result类型，可能是SyncResult对象或字典
            if hasattr(cloud_result, 'created'):
                # SyncResult对象
                created = getattr(cloud_result, 'created', 0)
                updated = getattr(cloud_result, 'updated', 0)
                deleted = getattr(cloud_result, 'deleted', 0)
                failed = getattr(cloud_result, 'failed', 0)
            else:
                # 字典对象
                created = cloud_result.get('created', 0)
                updated = cloud_result.get('updated', 0)
                deleted = cloud_result.get('deleted', 0)
                failed = cloud_result.get('failed', 0)
                
            total_created += created
            total_updated += updated
            total_deleted += deleted
            total_failed += failed
            logger.info(f"云平台 {cloud_name}: 创建: {created}, 更新: {updated}, 删除: {deleted}, 失败: {failed}")
        
        logger.info(f"总计: 创建: {total_created}, 更新: {total_updated}, 删除: {total_deleted}, 失败: {total_failed}")
        
        # 如果指定了输出文件，保存结果
        if args.output:
            save_result(result, args.output)
            logger.info(f"同步结果已保存到: {args.output}")
            
        # 如果有失败的资产，返回非零退出码
        if total_failed > 0:
            logger.warning(f"有 {total_failed} 个资产同步失败")
            sys.exit(2)
            
        sys.exit(0)
    except JmsSyncError as e:
        logger.error(f"同步失败: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"发生未预期的错误: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main() 