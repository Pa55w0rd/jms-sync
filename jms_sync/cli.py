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
from jms_sync.utils.logger import setup_logger, set_global_config, init_default_logging
from jms_sync.utils.exceptions import JmsSyncError
from jms_sync.config import load_config

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
    
    # 创建临时控制台日志，用于初始日志记录
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s', '%Y-%m-%d %H:%M:%S'))
    logger.addHandler(console_handler)
    
    # 记录开始信息
    logger.info(f"JMS-Sync 开始运行")
    logger.info(f"配置文件: {args.config}")
    
    try:
        # 检查配置文件是否存在
        if not os.path.exists(args.config):
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)
            
        # 加载配置文件
        try:
            config = load_config(args.config)
            logger.info("配置文件加载成功")
            
            # 设置全局配置对象，供日志模块使用
            set_global_config(config)
            
            # 初始化日志配置，现在将从配置文件获取设置
            init_default_logging()
            
            # 重新获取logger，现在已经应用了配置文件的设置
            logger = logging.getLogger()
            
        except Exception as e:
            logger.error(f"配置文件加载失败: {str(e)}")
            sys.exit(1)
            
        # 创建同步管理器
        sync_manager = SyncManager(config)
        
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