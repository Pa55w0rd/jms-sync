#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JMS-Sync 命令行入口脚本

用于将云平台（阿里云、华为云）的 ECS 实例信息同步到 JumpServer 堡垒机中，
实现资产的自动化管理。
"""

import sys
import os

# 确保当前目录在路径中，以便能够导入模块
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from jms_sync.cli import main

if __name__ == '__main__':
    main() 