# 初始化JumpServer客户端
if 'jumpserver' in config:
    try:
        # 获取JumpServer配置
        js_config = config['jumpserver']
        verify_ssl = js_config.get('verify_ssl', True)
        
        # 创建JumpServer客户端
        js_client = JumpServerClient(
            base_url=js_config.get('url', ''),
            access_key_id=js_config.get('access_key_id', ''),
            access_key_secret=js_config.get('access_key_secret', ''),
            org_id=js_config.get('org_id', ''),
            config=js_config  # 传递完整的jumpserver配置
        )
        logger.info("JumpServer客户端初始化成功")
    except Exception as e:
        logger.error(f"JumpServer客户端初始化失败: {e}")
        raise 