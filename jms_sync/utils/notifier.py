#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通知模块 - 用于发送各种通知
目前支持钉钉机器人通知
"""

import json
import time
import hmac
import base64
import hashlib
import urllib.parse
import logging
from typing import Dict, List, Any, Optional, Union
import requests

from jms_sync.utils.exceptions import JmsSyncError
from jms_sync.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationError(JmsSyncError):
    """通知错误异常类"""
    
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(f"通知错误: {message}", original_exception)


class DingTalkNotifier:
    """钉钉通知类，用于发送钉钉机器人通知"""
    
    def __init__(self, webhook: str, secret: Optional[str] = None, at_mobiles: List[str] = None, at_all: bool = False):
        """
        初始化钉钉通知器
        
        Args:
            webhook: 钉钉机器人webhook地址
            secret: 钉钉机器人安全设置中的签名密钥
            at_mobiles: 需要@的手机号列表
            at_all: 是否@所有人
        """
        self.webhook = webhook
        self.secret = secret
        self.at_mobiles = at_mobiles or []
        self.at_all = at_all
        
        if not webhook:
            logger.warning("钉钉webhook未配置，无法发送通知")
    
    def _sign(self) -> str:
        """
        生成钉钉机器人签名
        
        Returns:
            str: 签名后的URL
        """
        if not self.secret:
            return self.webhook
            
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        
        # 使用HmacSHA256算法计算签名
        hmac_code = hmac.new(
            self.secret.encode(), 
            string_to_sign.encode(), 
            digestmod=hashlib.sha256
        ).digest()
        
        # 对签名进行Base64编码
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        # 构造带签名的URL
        signed_url = f"{self.webhook}&timestamp={timestamp}&sign={sign}"
        return signed_url
    
    def send_text(self, content: str) -> bool:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            
        Returns:
            bool: 是否发送成功
        """
        if not self.webhook:
            logger.warning("钉钉webhook未配置，无法发送文本通知")
            return False
            
        message = {
            "msgtype": "text",
            "text": {
                "content": content
            },
            "at": {
                "atMobiles": self.at_mobiles,
                "isAtAll": self.at_all
            }
        }
        
        return self._send_message(message)
    
    def send_markdown(self, title: str, content: str) -> bool:
        """
        发送markdown消息
        
        Args:
            title: 消息标题
            content: markdown格式的消息内容
            
        Returns:
            bool: 是否发送成功
        """
        if not self.webhook:
            logger.warning("钉钉webhook未配置，无法发送markdown通知")
            return False
            
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": content
            },
            "at": {
                "atMobiles": self.at_mobiles,
                "isAtAll": self.at_all
            }
        }
        
        return self._send_message(message)
    
    def send_action_card(self, title: str, content: str, btn_title: str = None, btn_url: str = None, btns: List[Dict] = None) -> bool:
        """
        发送ActionCard消息
        
        Args:
            title: 卡片标题
            content: markdown格式的卡片内容
            btn_title: 整体跳转按钮标题，与btn_url一起使用
            btn_url: 整体跳转按钮链接，与btn_title一起使用
            btns: 独立跳转按钮列表[{"title": "按钮标题", "action_url": "跳转链接"}]
            
        Returns:
            bool: 是否发送成功
        """
        if not self.webhook:
            logger.warning("钉钉webhook未配置，无法发送ActionCard通知")
            return False
        
        # 初始化ActionCard基本结构    
        action_card = {
            "title": title,
            "text": content,
            "hideAvatar": "0",
            "btnOrientation": "0"
        }
        
        # 根据参数决定是整体跳转还是独立跳转
        if btn_title and btn_url:
            # 整体跳转
            action_card["singleTitle"] = btn_title
            action_card["singleURL"] = btn_url
        elif btns:
            # 独立跳转
            action_card["btns"] = [
                {"title": btn["title"], "actionURL": btn["action_url"]} 
                for btn in btns
            ]
            
        message = {
            "msgtype": "actionCard",
            "actionCard": action_card
        }
        
        return self._send_message(message)
    
    def send_asset_changes(self, sync_result: Dict[str, Any], platform: str, cloud_name: str, created_assets: List[Dict[str, Any]] = None, deleted_assets: List[Dict[str, Any]] = None) -> bool:
        """
        发送资产变更通知
        
        Args:
            sync_result: 同步结果
            platform: 云平台类型（如阿里云、华为云）
            cloud_name: 云平台名称
            created_assets: 新创建的资产列表
            deleted_assets: 已删除的资产列表
            
        Returns:
            bool: 是否发送成功
        """
        if not self.webhook:
            logger.warning("钉钉webhook未配置，无法发送资产变更通知")
            return False
            
        # 如果没有变更，不发送通知
        if (sync_result.get("created", 0) == 0 and sync_result.get("updated", 0) == 0 and sync_result.get("deleted", 0) == 0):
            logger.info("没有资产变更，不发送通知")
            return True
        
        # 获取结果数据
        created = sync_result.get('created', 0)
        updated = sync_result.get('updated', 0)
        deleted = sync_result.get('deleted', 0)
        failed = sync_result.get('failed', 0)
        total = sync_result.get('total', 0)
        duration = sync_result.get('duration', '0秒')
        
        # 构建ActionCard标题 - 与截图完全一致
        title = f"JMS资产同步通知"
        
        # 构建ActionCard内容 - 匹配截图样式
        content = ""
        content += f"# JMS资产同步通知\n"
        content += f"### **云资产** {platform} - {cloud_name}\n\n"
        content += f"### **同步时间** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # 同步结果部分
        content += "### **同步结果**\n\n"
        
        # 使用表格展示结果数据 - 完全匹配截图样式
        content += "| 指标 | 数值 |\n"
        content += "|---|---|\n"
        content += f"| 总计资产 | {total} 个 |\n"
        content += f"| 新增资产 | {created} 个 |\n"
        content += f"| 更新资产 | {updated} 个 |\n"
        content += f"| 删除资产 | {deleted} 个 |\n"
        content += f"| 失败操作 | {failed} 个 |\n"
        content += f"| 总耗时 | {duration} |\n\n"
        
        # 添加新增资产详情 - 使用与截图一致的样式
        if created_assets and created > 0:
            content += "### **新增资产详情**\n\n"
            
            # 使用表格展示资产信息
            content += "| 主机名 | IP地址 | 平台类型 |\n"
            content += "|---|---|---|\n"
            
            # 限制显示的资产数量
            limit = min(len(created_assets), 10)
            for i in range(limit):
                asset = created_assets[i]
                # 尝试多种可能的主机名字段
                hostname = "Unknown"
                for name_key in ['hostname', 'instance_name', 'name']:
                    if asset.get(name_key):
                        hostname = asset.get(name_key)
                        break
                        
                ip = asset.get('ip', 'No IP')
                
                # 获取操作系统类型
                os_type = "Unknown"
                for os_key in ['os', 'os_type', 'platform', 'system_type', 'system']:
                    if asset.get(os_key):
                        os_value = asset.get(os_key, '').lower()
                        if 'linux' in os_value or 'centos' in os_value or 'ubuntu' in os_value or 'debian' in os_value:
                            os_type = "Linux"
                            break
                        elif 'windows' in os_value or 'win' in os_value:
                            os_type = "Windows"
                            break
                        else:
                            os_type = asset.get(os_key)
                            break
                
                # 使用圆点符号表示列表项，与截图一致，添加平台类型列
                content += f"| {hostname} | {ip} | {os_type} |\n"
            
            # 添加查看详情链接
            if len(created_assets) > limit:
                content += f"\n*等共 {len(created_assets)} 个资产*\n"
        
        # 添加删除资产详情
        if deleted_assets and deleted > 0:
            content += "\n### **删除资产详情**\n\n"
            
            # 使用表格展示资产信息
            content += "| 主机名 | IP地址 | 平台类型 |\n"
            content += "|---|---|---|\n"
            
            # 限制显示的资产数量
            limit = min(len(deleted_assets), 10)
            for i in range(limit):
                asset = deleted_assets[i]
                # 获取资产名称
                asset_name = "Unknown"
                if hasattr(asset, 'name') and asset.name:
                    asset_name = asset.name
                elif isinstance(asset, dict):
                    for name_key in ['hostname', 'instance_name', 'name']:
                        if asset.get(name_key):
                            asset_name = asset.get(name_key)
                            break
                
                # 获取IP地址
                asset_ip = "No IP"
                if hasattr(asset, 'ip') and asset.ip:
                    asset_ip = asset.ip
                elif isinstance(asset, dict):
                    asset_ip = asset.get("ip", "No IP")
                
                # 获取操作系统类型
                os_type = "Unknown"
                if isinstance(asset, dict):
                    for os_key in ['os', 'os_type', 'platform', 'system_type', 'system']:
                        if asset.get(os_key):
                            os_value = asset.get(os_key, '').lower()
                            if 'linux' in os_value or 'centos' in os_value or 'ubuntu' in os_value or 'debian' in os_value:
                                os_type = "Linux"
                                break
                            elif 'windows' in os_value or 'win' in os_value:
                                os_type = "Windows"
                                break
                            else:
                                os_type = asset.get(os_key)
                                break
                
                # 添加平台类型列
                content += f"| {asset_name} | {asset_ip} | {os_type} |\n"
            
            if len(deleted_assets) > limit:
                content += f"\n*等共 {len(deleted_assets)} 个资产*\n"
        
        # 如果有错误，添加错误详情
        if failed > 0 and "errors" in sync_result:
            content += "\n### **错误详情**\n\n"
            
            # 使用表格展示错误信息
            content += "| 资产 | 错误信息 |\n"
            content += "|---|---|\n"
            
            # 限制显示的错误数量
            errors = sync_result.get("errors", [])
            limit = min(len(errors), 5)
            for i in range(limit):
                error = errors[i]
                asset_ip = error.get('asset_ip', 'Unknown')
                error_msg = error.get('message', 'Unknown error')
                content += f"| {asset_ip} | {error_msg} |\n"
            
            if len(errors) > limit:
                content += f"\n*等共 {len(errors)} 个错误*\n"
        
        # 创建操作按钮 - 查看资产详情按钮
        btns = [
            {
                "title": "查看资产详情",
                "action_url": "http://192.168.51.45/ui/#/console/assets/assets"
            }
        ]
        
        # 使用ActionCard发送通知，添加底部按钮
        return self.send_action_card(title, content, btns=btns)
    
    def _send_message(self, message: Dict[str, Any]) -> bool:
        """
        发送消息到钉钉
        
        Args:
            message: 消息内容
            
        Returns:
            bool: 是否发送成功
        """
        try:
            # 获取签名后的URL
            url = self._sign()
            
            # 发送POST请求
            headers = {'Content-Type': 'application/json; charset=utf-8'}
            response = requests.post(url, headers=headers, data=json.dumps(message))
            
            # 解析响应
            result = response.json()
            
            if response.status_code == 200 and result.get('errcode') == 0:
                logger.info(f"钉钉通知发送成功: {result.get('errmsg')}")
                return True
            else:
                logger.error(f"钉钉通知发送失败: {result.get('errmsg')}, 错误码: {result.get('errcode')}")
                return False
                
        except Exception as e:
            logger.exception(f"发送钉钉通知时发生错误: {e}")
            return False


class NotificationManager:
    """通知管理器，用于管理和发送各种通知"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化通知管理器
        
        Args:
            config: 通知配置
        """
        self.config = config or {}
        self.notifiers = {}
        
        # 初始化钉钉通知器
        dingtalk_config = self.config.get('dingtalk', {})
        if dingtalk_config and dingtalk_config.get('enabled', False):
            webhook = dingtalk_config.get('webhook', '')
            secret = dingtalk_config.get('secret', '')
            at_mobiles = dingtalk_config.get('at_mobiles', [])
            at_all = dingtalk_config.get('at_all', False)
            
            if webhook:
                self.notifiers['dingtalk'] = DingTalkNotifier(
                    webhook=webhook,
                    secret=secret,
                    at_mobiles=at_mobiles,
                    at_all=at_all
                )
                logger.info("钉钉通知器初始化成功")
            else:
                logger.warning("钉钉webhook未配置，无法初始化钉钉通知器")
    
    def notify_asset_changes(self, sync_result: Dict[str, Any], platform: str, cloud_name: str, created_assets: List[Dict[str, Any]] = None, deleted_assets: List[Dict[str, Any]] = None) -> bool:
        """
        发送资产变更通知
        
        Args:
            sync_result: 同步结果
            platform: 云平台类型
            cloud_name: 云平台名称
            created_assets: 新创建的资产列表
            deleted_assets: 已删除的资产列表
            
        Returns:
            bool: 是否有通知成功发送
        """
        # 检查是否有变更，如果没有变更则不发送通知
        if (sync_result.get("created", 0) == 0 and 
            sync_result.get("updated", 0) == 0 and 
            sync_result.get("deleted", 0) == 0):
            logger.info("没有资产变更，不发送通知")
            return True
            
        success = False
        
        # 发送钉钉通知
        dingtalk = self.notifiers.get('dingtalk')
        if dingtalk:
            dingtalk_success = dingtalk.send_asset_changes(
                sync_result=sync_result,
                platform=platform,
                cloud_name=cloud_name,
                created_assets=created_assets,
                deleted_assets=deleted_assets
            )
            success = success or dingtalk_success
            
        return success 