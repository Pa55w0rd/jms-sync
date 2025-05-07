# JMS-Sync 资产同步工具

JMS-Sync 是一个高效的云平台资产同步工具，用于将多种云平台的资产自动同步到 JumpServer 堡垒机，实现资产的自动化管理和运维安全保障。

## 项目概述

JMS-Sync 通过云平台 API 获取云服务器实例信息，并将其同步到 JumpServer 堡垒机中，确保堡垒机资产库与实际云平台资产保持一致。该工具采用了多种优化技术，包括多线程并行处理、缓存机制、批量处理和智能错误处理，提高了同步效率和稳定性。

## 功能特性

- **多云平台支持**
  - 支持阿里云 ECS 实例同步
  - 支持华为云 ECS 实例同步
  - 可扩展架构，便于添加其他云平台支持

- **高效同步机制**
  - 多线程并行处理，提高同步速度
  - 批量处理资产，避免内存溢出问题
  - 智能缓存机制，减少重复 API 调用
  - 增量同步，只处理变更的资产

- **完善的错误处理**
  - 分类错误处理机制，针对不同错误类型采取不同策略
  - 智能重试机制，自动重试临时性错误
  - 详细的错误日志记录，便于问题排查
  - 同步失败自动恢复机制

- **灵活的配置选项**
  - 支持配置同步参数，如并行线程数、批处理大小等
  - 支持 IP 白名单和受保护 IP 功能
  - 可配置是否执行删除操作
  - 支持多环境配置

- **完善的日志系统**
  - 结构化日志输出，便于分析
  - 日志轮转机制，避免日志文件过大
  - 可配置的日志级别和格式
  - 支持JSON格式日志输出

- **通知提醒功能**
  - 支持钉钉机器人通知
  - 资产变更时自动发送通知
  - 详细展示新增、更新和删除的资产信息
  - 灵活的通知配置，支持@指定人员
  - 美观的Markdown格式通知卡片

## 系统要求

- Python 3.8 以上（推荐使用 Python 3.8.10）
- JumpServer 社区版 v4.7.0 及以上
- 云平台 API 访问权限和凭证
- 网络环境可访问JumpServer和云平台API

## 安装指南

### 1. 克隆代码仓库

```bash
git clone https://github.com/pa55w0rd/jms-sync.git
cd jms-sync
```

### 2. 安装依赖包

```bash
pip install -r requirements.txt
```

对于国内用户，建议使用镜像源加速安装：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置文件准备

```bash
cp config.yaml.example config.yaml
```

然后编辑 `config.yaml` 文件，填写 JumpServer 和云平台的配置信息。

### 4. JumpServer 前置配置

在使用 JMS-Sync 工具前，您需要在 JumpServer 社区版 v4.7.0 中完成以下前置配置：

#### 4.1 创建网域

1. 登录 JumpServer 管理界面
2. 导航至 "资产管理" > "网域列表"
3. 点击 "创建" 按钮
4. 填写网域信息：
   - 名称：为网域指定一个有意义的名称（如 "阿里云资产网域"）
5. 点击 "提交" 完成创建
6. 记录新建网域的 ID（通过URL查看），此 ID 将用于配置文件

#### 4.2 设置网关

1. 在网域列表中找到刚创建的网域，点击 "网关列表" 
2. 点击 "创建" 按钮
3. 填写网关信息：
   - 名称：网关名称（如 "阿里云网关"）
   - IP/主机：填写可访问云平台资产的地址（内网环境可填写 JumpServer 所在服务器IP）
   - 平台：网关平台只能选择以 Gateway 开头的平台
   - 节点：选择指定的资产节点
   - 端口：一般为 22（SSH）或 3389（RDP）
   - 协议：选择合适的协议（如 SSH）
   - 账号：填写网关服务器账号
4. 点击 "提交" 完成网关创建

#### ~~4.3 创建账号模板~~

~~账号模板用于自动为同步的资产创建登录凭证：~~

1. ~~导航至 "账号管理" > "账号模板"~~
2. ~~点击 "创建" 按钮~~
3. ~~填写凭证信息~~：
   - ~~名称：为模板命名（如 "Linux服务器模板"、"Windows服务器模板"）~~
   - ~~类型：选择 "SSH私钥" (Linux) 或 "密码" (Windows)~~
   - ~~登录用户名：填写默认登录用户（如Linux的 "root"，Windows的 "Administrator"）~~
   - ~~密码或私钥：填写对应的认证信息~~
   - ~~自动推送：建议启用~~
4. ~~点击 "提交" 创建账号模板~~
5. ~~记录创建的账号模板 ID，填入配置文件对应区域~~

## 配置说明

`config.yaml` 包含以下主要配置部分：

### 环境配置

```yaml
environment:
  # 环境类型: PRODUCTION, DEVELOPMENT, TESTING
  type: "DEVELOPMENT"
```

### JumpServer 配置

```yaml
jumpserver:
  url: "https://jumpserver.example.com"  # JumpServer URL
  access_key_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # 访问密钥ID
  access_key_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 访问密钥
  org_id: "00000000-0000-0000-0000-000000000002"  # 组织ID
  verify_ssl: true  # 是否验证SSL证书
```

> **重要提示**：填写的账号模板ID必须对应JumpServer中已创建的模板，否则资产同步后将无法自动设置登录凭证。

### 云平台配置

```yaml
clouds:
  - type: "阿里云" # 云平台，阿里云或华为云，其他自行扩展
    name: "aliyun-prod"  # 用于多账号配置节点常见， /DEFAULT/阿里云/aliyun-prod
    access_key_id: "YOUR_ALIYUN_ACCESS_KEY_ID"  # 阿里云访问密钥ID
    access_key_secret: "YOUR_ALIYUN_ACCESS_KEY_SECRET"  # 阿里云访问密钥
    regions:
      - "cn-beijing"
    domain_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # 网域ID，必须提前在JumpServer中创建，无跨网络可为空
    enabled: true # 是否开启云资产同步
```

> **安全建议**：不要在配置文件中使用具有过高权限的API密钥，应创建专用于资产同步的最小权限账号。

### 同步配置

```yaml
sync:
  whitelist: []  # IP白名单，空列表表示不限制
  protected_ips: []  # 保护的IP列表，不会被删除
  no_delete: false  # 是否禁用删除功能
```

### 通知配置

```yaml
notification:
  # 钉钉通知配置，其他通知自行扩展
  dingtalk:
    enabled: true  # 是否启用钉钉通知
    webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxxxxxxx"  # 钉钉机器人webhook
    secret: "SECxxxxxxxxxxxxxxxx"  # 钉钉机器人签名密钥，如果没有可以留空
    at_mobiles:  # 需要@的手机号列表
      - "138xxxxxxxx"
      - "139xxxxxxxx"
    at_all: false  # 是否@所有人
```

### 日志配置

```yaml
log:
  level: "INFO"  # 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: "logs/jms-sync.log"  # 日志文件路径
  max_size: 10  # 日志文件最大大小（MB）
  backup_count: 5  # 保留的日志文件数量
  json_format: false  # 是否使用JSON格式输出日志
  detailed: false  # 是否使用详细日志格式（包含线程信息）
  separate_error_log: true  # 是否将ERROR及以上级别的日志单独记录到一个文件
```

## 使用方法

### 基本用法

```bash
python jms-sync.py
```

这将使用默认配置文件（`config.yaml`）运行同步任务。

### 命令行参数

```bash
python jms-sync.py -c custom-config.yaml  # 使用自定义配置文件
python jms-sync.py -l DEBUG               # 设置日志级别
python jms-sync.py --no-log-file          # 不将日志写入文件
python jms-sync.py -r 5                   # 设置重试次数为5
python jms-sync.py -i 10                  # 设置重试间隔为10秒
python jms-sync.py -o results.json        # 将结果输出到JSON文件
```

完整的命令行参数说明：

| 参数 | 描述 |
|-----|-----|
| `-c, --config` | 配置文件路径 (默认: config.yaml) |
| `-l, --log-level` | 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `--log-file` | 日志文件路径 |
| `--no-log-file` | 不输出日志到文件 |
| `-r, --retries` | 同步失败时的最大重试次数 (默认: 3) |
| `-i, --interval` | 重试间隔时间(秒) (默认: 5) |
| `-o, --output` | 将同步结果输出到指定的JSON文件 |

## 架构说明

JMS-Sync 采用模块化设计，主要包含以下组件：

- **CLI 模块**: 处理命令行参数和启动同步任务
- **配置模块**: 读取和解析配置文件
- **云平台模块**: 实现与各云平台 API 的交互
- **JumpServer 模块**: 实现与 JumpServer API 的交互
- **同步模块**: 协调各模块工作，实现资产同步逻辑
- **工具模块**: 提供缓存、日志、异常处理等通用功能
- **通知模块**: 实现资产变更通知功能

### 数据流程

1. 从配置文件加载配置参数
2. 初始化日志系统和云平台客户端
3. 调用云平台API获取服务器实例信息
4. 处理并标准化云平台数据
5. 创建或获取JumpServer节点
6. 将处理后的数据同步到JumpServer
7. 发送通知并记录同步结果

## 通知功能说明

### 钉钉通知配置

1. 在钉钉中创建一个自定义机器人：
   - 进入钉钉群 -> 群设置 -> 智能群助手 -> 添加机器人 -> 自定义
   - 设置机器人名称，并配置安全设置（推荐使用签名模式）
   - 复制机器人的 Webhook 地址和签名密钥

2. 在 `config.yaml` 中配置机器人信息：
   ```yaml
   notification:
     dingtalk:
       enabled: true
       webhook: "你的机器人webhook地址"
       secret: "你的签名密钥"
       at_mobiles: ["需要@的手机号"]
       at_all: false
   ```

3. 通知效果：
   - 使用现代化的ActionCard卡片格式展示，更直观美观
   - 当资产发生变更（新增、更新、删除）时，自动发送通知
   - 通知内容包括变更摘要和详细资产信息
   - 对于大量变更，将展示前几条并标注总数
   - 提供"查看资产详情"按钮，一键跳转到资产管理页面
   - 支持资产详情表格显示主机名、IP地址和平台类型
   - 统计同步耗时，便于评估同步性能

### 通知卡片效果展示

钉钉通知卡片格式包含以下主要部分：

```
# JMS资产同步通知
### 同步时间：2023-12-15 09:30:25

### 同步结果

| 指标 | 数值 |
|---|---|
| 总计资产 | 120 个 |
| 新增资产 | 5 个 |
| 更新资产 | 2 个 |
| 删除资产 | 1 个 |
| 失败操作 | 0 个 |
| 总耗时 | 25.48秒 |

### 新增资产详情

| 主机名 | IP地址 | 平台类型 |
|---|---|---|
| web-server-01 | 192.168.1.101 | Linux |
| db-server-01 | 192.168.1.102 | Linux |
| app-server-02 | 192.168.1.103 | Windows |

*等共 5 个资产*

### 删除资产详情

| 主机名 | IP地址 | 平台类型 |
|---|---|---|
| old-server-01 | 192.168.1.201 | Linux |
```

### 平台类型识别

系统会自动分析资产信息中的操作系统字段，识别并显示资产的操作系统类型：

- **Linux**：自动检测包含"linux"、"centos"、"ubuntu"、"debian"等关键词的资产
- **Windows**：自动检测包含"windows"或"win"关键词的资产
- **其他**：如果无法识别，则显示原始值或"Unknown"

## 性能优化技术

JMS-Sync 采用了多种性能优化技术，确保在处理大量资产时保持高效：

### 1. 批量处理

- 将资产分批同步到JumpServer，避免一次处理过多数据导致的内存溢出
- 默认批量大小为100，可通过配置文件调整
- 自动根据系统资源调整批处理参数

### 2. 增量同步

- 只处理发生变化的资产，减少API调用和数据传输
- 使用资产指纹技术快速识别变更
- 自动跳过未变更的资产，显著提高同步速度

### 3. 缓存机制

- 缓存云平台和JumpServer的数据，减少重复API调用
- 智能缓存过期策略，确保数据一致性
- 多级缓存架构，优化读写性能

### 4. 并行处理

- 多线程并行获取云平台资产数据
- 智能线程池管理，根据系统负载动态调整线程数
- 区域级并行处理，加速多区域资产同步

### 5. 错误恢复机制

- 细粒度错误追踪，单个资产同步失败不影响整体同步
- 自动重试临时性错误
- 记录详细错误信息，便于问题排查

## 最佳实践

### 性能优化建议

- 在大型环境中，建议启用JSON格式日志，便于日志分析和问题排查
- 对于网络不稳定环境，适当增加重试次数和间隔时间
- 使用受保护IP功能，确保关键资产不会被误删
- 首次运行时开启DEBUG日志级别，后续可调整为INFO级别
- 定期清理日志文件，避免占用过多磁盘空间

### 安全建议

- 使用最小权限原则配置云平台和 JumpServer 的 API 凭证
- 定期轮换 API 密钥，建议至少每90天更新一次
- 使用 HTTPS 协议访问 JumpServer，确保通信加密
- 谨慎配置钉钉通知，避免泄露敏感信息
- 保护好配置文件，避免明文凭证泄露

## 故障排除

### 常见问题

1. **连接超时**
   - 检查网络连接和防火墙设置
   - 确认 JumpServer 和云平台 API 地址正确
   - 适当增加重试次数和超时时间
   - 检查代理配置是否正确

2. **认证失败**
   - 检查 API 密钥是否正确，注意不要有多余的空格
   - 确认密钥是否有效且未过期
   - 验证 API 权限设置是否足够
   - 检查系统时间是否准确（某些API认证依赖时间戳）

3. **同步失败**
   - 查看日志文件了解详细错误信息
   - 检查配置文件格式是否正确，确保无语法错误
   - 适当减小批处理大小减轻负载
   - 验证JumpServer和云平台API是否正常运行

4. **通知发送失败**
   - 检查钉钉机器人配置是否正确
   - 确认 Webhook 地址有效且可访问
   - 检查网络环境是否允许访问钉钉服务器
   - 验证签名密钥是否正确

### 日志分析

查看日志文件定位问题：
```bash
tail -f logs/jms-sync.log
```

查看错误日志：
```bash
tail -f logs/jms-sync.error.log
```

## 开发指南

### 添加新云平台支持

1. 在 `jms_sync/cloud` 目录下创建新的云平台模块
2. 继承 `CloudBase` 类并实现必要的方法：
   ```python
   from jms_sync.cloud.base import CloudBase
   
   class NewCloudProvider(CloudBase):
       def __init__(self, access_key_id, access_key_secret, region):
           super().__init__(access_key_id, access_key_secret, region)
           
       def get_instances(self):
           # 实现获取云平台实例的逻辑
           pass
           
       def set_region(self, region):
           # 实现切换区域的逻辑
           pass
   ```
3. 在 `jms_sync/cloud/__init__.py` 中注册新的云平台
4. 在 `CloudClientFactory` 中添加创建新云平台客户端的逻辑

### 扩展通知方式

1. 在 `jms_sync/utils/notifier.py` 中创建新的通知类：
   ```python
   class NewNotifier:
       def __init__(self, config):
           self.config = config
           # 初始化逻辑
           
       def send_notification(self, title, content):
           # 实现发送通知的逻辑
           pass
   ```
2. 在 `NotificationManager` 类中添加对应的初始化和发送方法
3. 在配置文件中添加新通知方式的配置项

### 代码规范

- 遵循 PEP 8 编码规范
- 使用类型提示增强代码可读性
- 编写详细的函数和类文档
- 使用 pylint 或 flake8 进行代码检查
- 保持代码覆盖率在80%以上

## 贡献

欢迎贡献代码、报告问题或提出改进建议！请遵循以下步骤：

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详情请参阅 [LICENSE](LICENSE) 文件。

## 联系方式

如有任何问题或建议，请通过以下方式联系我们：

- 项目issues: [https://github.com/Pa55w0rd/jms-sync/issues](https://github.com/Pa55w0rd/jms-sync/issues)
- 电子邮件: pa55w0rd@aliyun.com

## 安全配置指南

为确保JMS-Sync工具的安全使用，请遵循以下最佳实践：

### 1. 敏感信息处理

- **永远不要将包含真实凭证的`config.yaml`文件提交到Git仓库**
- 确保`.gitignore`文件中包含`config.yaml`
- 如果不慎提交，使用以下命令从仓库中移除（但不删除本地文件）：
  ```bash
  git rm --cached config.yaml
  git commit -m "移除敏感配置文件"
  ```

### 2. API凭证安全

- 为JMS-Sync创建专用的最小权限API密钥
- 阿里云API密钥只需授予ECS只读权限
- 华为云API密钥只需授予ECS只读权限
- JumpServer访问密钥应限制仅有资产管理权限

### 3. 网络安全

- JMS-Sync应部署在能够同时访问JumpServer和云平台API的网络环境
- 建议通过HTTPS连接JumpServer，确保API通信加密
- 如使用HTTP连接，务必确保在受信任的内网环境中运行

## 未来规划

- 支持更多云平台（腾讯云、AWS、Azure等）
- 增加Web管理界面，实现可视化配置和监控
- 支持更多通知方式（邮件、企业微信等）
- 实现资产变更自动审批流程
- 集成自动化运维功能