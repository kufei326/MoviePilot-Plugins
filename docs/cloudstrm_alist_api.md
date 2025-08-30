# CloudStrm 插件 - Alist API 支持

## 概述

CloudStrm 插件已升级支持直接使用 Alist API 来生成 strm 文件，无需将云盘挂载到本地。这种方式更加高效和稳定。

## 新功能特性

1. **Alist API 直链获取**：直接调用 Alist 的 `/api/fs/link` 接口获取文件直链
2. **Token 认证支持**：支持使用 Alist token 进行身份验证
3. **自动回退机制**：如果 API 调用失败，自动回退到原来的 `/d` 路径方式
4. **更好的错误处理**：详细的日志记录和错误提示

## 配置格式

### 1. 本地挂载模式（原有方式）
```
监控目录#目的目录#媒体服务器内源文件路径
```
示例：
```
/mnt/downloads#/media/movies#/movies
```

### 2. Alist 模式（无 Token）
```
监控目录#目的目录#alist#alist挂载本地跟路径#alist服务地址
```
示例：
```
/mnt/alist#/media/movies#alist#/mnt/alist#alist.example.com
```

### 3. Alist 模式（有 Token，推荐）
```
监控目录#目的目录#alist#alist挂载本地跟路径#alist服务地址#alist_token
```
示例：
```
/mnt/alist#/media/movies#alist#/mnt/alist#alist.example.com#alist-xxx-xxx-xxx
```

## Alist Token 获取方法

1. 登录 Alist 管理界面
2. 进入 `设置` -> `其他` -> `令牌`
3. 点击 `生成` 按钮生成新的 token
4. 复制生成的 token 用于配置

## 工作原理

1. **扫描文件**：插件扫描指定目录下的媒体文件
2. **API 调用**：对于 Alist 模式，调用 `/api/fs/link` 接口获取直链
3. **生成 strm**：将获取到的直链写入 `.strm` 文件
4. **回退机制**：如果 API 调用失败，使用 `/d` 路径作为备选方案

## API 请求示例

```json
POST https://alist.example.com/api/fs/link
Headers:
{
    "Content-Type": "application/json",
    "Authorization": "Bearer your-alist-token"
}
Body:
{
    "path": "/movies/example.mp4",
    "password": ""
}
```

## 优势

1. **无需挂载**：不需要将云盘挂载到本地，减少系统资源占用
2. **更稳定**：避免挂载可能出现的网络问题和断连
3. **更安全**：使用 token 认证，提高安全性
4. **更快速**：直接获取直链，减少中间环节

## 注意事项

1. 确保 Alist 服务正常运行且可访问
2. Token 需要有足够的权限访问目标文件
3. 网络连接需要稳定，建议使用内网地址
4. 如果使用 HTTPS，确保证书有效

## 故障排除

1. **API 调用失败**：检查 Alist 地址和 token 是否正确
2. **权限不足**：确认 token 有访问目标路径的权限
3. **网络问题**：检查网络连接和防火墙设置
4. **路径错误**：确认文件路径格式正确

## 版本更新

### v4.5.0 (最新)
- **重构 Alist API 集成**：完全按照 Alist 官方 API 规范重新实现
- **改进路径处理**：更准确的文件路径解析和URL编码
- **增强错误处理**：详细的错误分类和日志记录
- **连接测试**：插件启动时自动测试 Alist 连接状态
- **更好的回退机制**：API 失败时智能回退到 `/d` 端点
- **超时优化**：增加请求超时时间，提高稳定性

### v4.4.2 (之前版本)
- 新增 Alist API 直链获取功能
- 新增 Token 认证支持
- 新增自动回退机制
- 优化错误处理和日志记录

## 最佳实践

1. **推荐配置**：使用带 Token 的 Alist 模式，获得最佳性能和稳定性
2. **网络环境**：建议在内网环境中部署，减少网络延迟
3. **Token 管理**：定期更新 Alist Token，确保安全性
4. **监控日志**：关注插件日志，及时发现和解决问题
5. **路径规范**：确保路径配置正确，避免编码问题