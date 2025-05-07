#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
JmsNodeManager: 严格遵循《jms节点创建查询逻辑.md》实现JumpServer节点的查询、创建、存储
"""
from typing import Dict, Any, Optional, List, Union
import logging
from jms_sync.jumpserver.models import NodeInfo

class JmsNodeManager:
    def __init__(self, js_client, logger: Optional[logging.Logger] = None):
        """
        初始化节点管理器
        
        Args:
            js_client: JumpServer客户端
            logger: 日志记录器
        """
        self.js_client = js_client
        self.logger = logger or logging.getLogger(__name__)
        self.nodes_map = {}  # 嵌套字典结构，仅在当前运行期间有效
        self.root_key = "1"  # 根节点key固定为1
        self.root_id = None  # 根节点ID
        # 缓存已被移除，使用变量在会话期间保存节点信息
        self.nodes_session = {}  # 路径到节点的映射，仅在当前运行期间有效
        self._init_root_node()

    def _init_root_node(self):
        """初始化根节点"""
        root_node = self._get_root_node()
        if root_node:
            self.root_id = root_node["id"]
            self.nodes_session["/DEFAULT"] = root_node
            self.logger.debug(f"根节点初始化成功: ID={self.root_id}")
        else:
            self.logger.warning("根节点初始化失败")

    def init_nodes(self, cloud_type: str, cloud_name: str):
        """
        初始化节点结构，确保根、二级、三级节点存在，并填充nodes_map
        
        Args:
            cloud_type: 云平台类型，用于创建二级节点
            cloud_name: 云平台名称，用于创建三级节点
        """
        # 1. 获取根节点
        root_node = self._get_root_node()
        if not root_node:
            raise Exception("未找到JumpServer根节点/DEFAULT")
        self.root_id = root_node["id"]
        
        # 2. 获取或创建二级节点
        second_node = self._get_or_create_child_node(self.root_id, self.root_key, cloud_type)
        
        # 3. 获取或创建三级节点
        third_node = self._get_or_create_child_node(second_node["id"], second_node["key_id"], cloud_name)
        
        # 4. 构建嵌套字典
        self.nodes_map = {
            cloud_type: {
                "key_id": second_node["key_id"],
                "key_pId": self.root_key,
                "id": second_node["id"],
                "children": {
                    cloud_name: {
                        "key_id": third_node["key_id"],
                        "key_pId": second_node["key_id"],
                        "id": third_node["id"]
                    }
                }
            }
        }
        
        # 5. 更新会话中的节点信息
        self.nodes_session[f"/DEFAULT/{cloud_type}"] = second_node
        self.nodes_session[f"/DEFAULT/{cloud_type}/{cloud_name}"] = third_node
        
        self.logger.info(f"节点结构初始化完成: {self.nodes_map}")

    def _get_root_node(self) -> Dict[str, Any]:
        """
        获取根节点信息，根据文档根节点默认存在，直接返回固定值
        
        Returns:
            Dict[str, Any]: 根节点信息
        """
        # 文档中明确指出根节点默认存在，无需查询，使用文档提供的默认值
        root_node = {
            "key_id": "1",
            "id": "f7409c89-af14-4417-954c-a4744f8b11e1",
            "value": "DEFAULT",
            "full_value": "/DEFAULT"
        }
        self.logger.debug("使用默认根节点信息")
        return root_node

    def _get_or_create_child_node(self, parent_id: str, parent_key: str, value: str) -> Dict[str, Any]:
        """
        查询指定父节点下的子节点，不存在则创建
        
        Args:
            parent_id: 父节点ID
            parent_key: 父节点key_id
            value: 子节点名称
            
        Returns:
            Dict[str, Any]: 子节点信息
        """
        # 1. 查询
        try:
            resp = self.js_client._api_request(
                "GET", f"/api/v1/assets/nodes/children/tree/?key={parent_key}")
            for node in resp:
                meta = node.get("meta", {}).get("data", {})
                if meta.get("value") == value:
                    self.logger.info(f"找到已存在节点: {value} (key: {meta.get('key')})")
                    return {
                        "id": meta.get("id"),
                        "key_id": meta.get("key"),
                        "value": value
                    }
        except Exception as e:
            self.logger.warning(f"查询节点{value}失败: {e}")
        
        # 2. 创建
        try:
            body = {"value": value}
            self.logger.info(f"创建节点: {value} (父节点ID: {parent_id})")
            resp = self.js_client._api_request(
                "POST", f"/api/v1/assets/nodes/{parent_id}/children/", json_data=body)
            return {
                "id": resp.get("id"),
                "key_id": resp.get("key"),
                "value": value
            }
        except Exception as e:
            self.logger.error(f"创建节点{value}失败: {e}")
            raise

    def get_nodes_map(self) -> Dict[str, Any]:
        """
        获取当前的嵌套节点字典结构
        
        Returns:
            Dict[str, Any]: 节点嵌套字典
        """
        return self.nodes_map
    
    def get_node_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """
        通过路径获取节点信息
        
        Args:
            path: 节点路径，格式如 "/DEFAULT/aliyun/prod"
            
        Returns:
            Optional[Dict[str, Any]]: 节点信息，如果未找到返回None
        """
        # 1. 首先检查会话中是否有节点信息
        path = path.rstrip('/')  # 移除末尾斜杠
        if path in self.nodes_session:
            self.logger.debug(f"从会话中获取节点信息: {path}")
            return self.nodes_session[path]
        
        # 2. 解析路径
        parts = path.strip('/').split('/')
        if not parts or parts[0] != "DEFAULT":
            self.logger.error(f"无效的节点路径: {path}")
            return None
        
        # 3. 处理根节点
        if len(parts) == 1:
            root_node = self._get_root_node()
            self.nodes_session[path] = root_node
            return root_node
        
        # 4. 处理二级节点
        if len(parts) == 2:
            # 确保根节点存在
            root_node = self._get_root_node()
            if not root_node:
                return None
            
            # 获取二级节点
            try:
                resp = self.js_client._api_request("GET", f"/api/v1/assets/nodes/children/tree/?key=1")
                for node in resp:
                    meta = node.get("meta", {}).get("data", {})
                    if meta.get("value") == parts[1]:
                        node_info = {
                            "id": meta.get("id"),
                            "key_id": meta.get("key"),
                            "value": parts[1],
                            "full_value": f"/DEFAULT/{parts[1]}"
                        }
                        self.nodes_session[path] = node_info
                        return node_info
            except Exception as e:
                self.logger.error(f"获取二级节点失败: {e}")
            return None
        
        # 5. 处理三级节点
        if len(parts) == 3:
            # 先获取二级节点
            second_node = self.get_node_by_path(f"/DEFAULT/{parts[1]}")
            if not second_node:
                return None
            
            # 获取三级节点
            try:
                resp = self.js_client._api_request(
                    "GET", f"/api/v1/assets/nodes/children/tree/?key={second_node['key_id']}")
                for node in resp:
                    meta = node.get("meta", {}).get("data", {})
                    if meta.get("value") == parts[2]:
                        node_info = {
                            "id": meta.get("id"),
                            "key_id": meta.get("key"),
                            "value": parts[2],
                            "full_value": f"/DEFAULT/{parts[1]}/{parts[2]}"
                        }
                        self.nodes_session[path] = node_info
                        return node_info
            except Exception as e:
                self.logger.error(f"获取三级节点失败: {e}")
            return None
        
        self.logger.error(f"不支持超过三级的节点路径: {path}")
        return None 

    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        通过ID获取节点信息
        
        Args:
            node_id: 节点ID
            
        Returns:
            Optional[Dict[str, Any]]: 节点信息，如果未找到返回None
        """
        try:
            # 检查会话中是否有该节点
            for path, node in self.nodes_session.items():
                if node.get("id") == node_id:
                    return node
                    
            # 获取所有节点
            nodes = self.js_client.get_nodes()
            for node in nodes:
                if node.id == node_id:
                    node_info = {
                        "id": node.id,
                        "key_id": node.key,
                        "value": node.value,
                        "full_value": node.full_value
                    }
                    # 更新会话，如果有full_value
                    if node.full_value:
                        self.nodes_session[node.full_value] = node_info
                    return node_info
        except Exception as e:
            self.logger.error(f"通过ID获取节点失败: {e}")
        return None

    def update_node(self, node_id: str, value: str) -> Optional[Dict[str, Any]]:
        """
        更新节点
        
        Args:
            node_id: 节点ID
            value: 节点新名称
            
        Returns:
            Optional[Dict[str, Any]]: 更新后的节点信息，失败返回None
        """
        try:
            # 构建更新数据
            update_data = {"value": value}
            # 调用API
            response = self.js_client._api_request(
                "PUT", f"/api/v1/assets/nodes/{node_id}/", json_data=update_data)
            # 返回更新后的节点信息
            node_info = {
                "id": response.get("id"),
                "key_id": response.get("key"),
                "value": response.get("value"),
                "full_value": response.get("full_value")
            }
            
            # 更新会话
            if response.get("full_value"):
                self.nodes_session[response.get("full_value")] = node_info
                
            return node_info
        except Exception as e:
            self.logger.error(f"更新节点失败: {e}")
            return None
        
    def delete_node(self, node_id: str) -> bool:
        """
        删除节点
        
        Args:
            node_id: 节点ID
            
        Returns:
            bool: 删除是否成功
        """
        try:
            # 获取节点信息，用于从会话中删除
            node_info = self.get_node_by_id(node_id)
            
            # 调用API删除节点
            self.js_client._api_request("DELETE", f"/api/v1/assets/nodes/{node_id}/")
            
            # 从会话中删除
            if node_info and node_info.get("full_value"):
                if node_info.get("full_value") in self.nodes_session:
                    del self.nodes_session[node_info.get("full_value")]
            
            return True
        except Exception as e:
            self.logger.error(f"删除节点失败: {e}")
            return False
    
    def get_children_nodes(self, parent_key: str) -> List[Dict[str, Any]]:
        """
        获取指定父节点下的所有子节点
        
        Args:
            parent_key: 父节点key
            
        Returns:
            List[Dict[str, Any]]: 子节点列表
        """
        try:
            # 调用API获取子节点
            resp = self.js_client._api_request(
                "GET", f"/api/v1/assets/nodes/children/tree/?key={parent_key}")
            
            # 处理结果
            children = []
            for node in resp:
                meta = node.get("meta", {}).get("data", {})
                child = {
                    "id": meta.get("id"),
                    "key_id": meta.get("key"),
                    "value": meta.get("value"),
                    "full_value": meta.get("full_value", "")
                }
                children.append(child)
                
                # 更新会话
                if child.get("full_value"):
                    self.nodes_session[child.get("full_value")] = child
            
            return children
        except Exception as e:
            self.logger.error(f"获取子节点失败: {e}")
            return []
    
    def get_or_create_nodes_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """
        通过路径获取或创建节点，自动创建路径中不存在的节点
        
        Args:
            path: 节点路径，格式如 "/DEFAULT/aliyun/prod"
            
        Returns:
            Optional[Dict[str, Any]]: 节点信息，如果创建失败返回None
        """
        # 1. 首先尝试直接获取
        node = self.get_node_by_path(path)
        if node:
            return node
        
        # 2. 解析路径
        parts = path.strip('/').split('/')
        if not parts or parts[0] != "DEFAULT":
            self.logger.error(f"无效的节点路径: {path}")
            return None
        
        # 3. 确保有根节点
        root_node = self._get_root_node()
        if not root_node:
            self.logger.error("未找到根节点")
            return None
        
        # 4. 如果是根节点，直接返回
        if len(parts) == 1:
            return root_node
        
        # 5. 处理二级节点
        if len(parts) >= 2:
            # 获取或创建二级节点
            second_node = self.get_node_by_path(f"/DEFAULT/{parts[1]}")
            if not second_node:
                # 创建二级节点
                second_node = self._get_or_create_child_node(
                    root_node["id"], root_node["key_id"], parts[1])
                if second_node:
                    # 更新会话
                    second_node["full_value"] = f"/DEFAULT/{parts[1]}"
                    self.nodes_session[f"/DEFAULT/{parts[1]}"] = second_node
            
            # 如果只需要二级节点，返回
            if len(parts) == 2:
                return second_node
                
            # 6. 处理三级节点
            if len(parts) == 3:
                # 获取或创建三级节点
                third_node = self.get_node_by_path(f"/DEFAULT/{parts[1]}/{parts[2]}")
                if not third_node:
                    # 创建三级节点
                    third_node = self._get_or_create_child_node(
                        second_node["id"], second_node["key_id"], parts[2])
                    if third_node:
                        # 更新会话
                        third_node["full_value"] = f"/DEFAULT/{parts[1]}/{parts[2]}"
                        self.nodes_session[f"/DEFAULT/{parts[1]}/{parts[2]}"] = third_node
                
                return third_node
            
            # 7. 不支持超过三级的节点
            if len(parts) > 3:
                self.logger.error(f"不支持超过三级的节点路径: {path}")
                return None
        
        return None

    def convert_to_node_info(self, node_data: Dict[str, Any]) -> NodeInfo:
        """
        将节点数据转换为NodeInfo对象
        
        Args:
            node_data: 节点数据
            
        Returns:
            NodeInfo: 节点信息对象
        """
        return NodeInfo(
            id=node_data.get("id"),
            key=node_data.get("key_id"),
            value=node_data.get("value", ""),
            full_value=node_data.get("full_value", "")
        ) 