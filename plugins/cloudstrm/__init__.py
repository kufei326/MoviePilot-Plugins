import json
import os
import shutil
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

# Media file extensions to look for
MEDIA_EXT = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.ts', '.rmvb',
    '.m2ts', '.mpg', '.mpeg', '.rm', '.asf', '.iso'
}


class CloudStrm(_PluginBase):
    # 插件名称
    plugin_name = "云盘Strm生成 (纯API版)"
    # 插件描述
    plugin_desc = "通过Alist API直接扫描云盘目录并生成Strm文件，无需本地挂载。优化版本，使用直接链接方式提升性能。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/create.png"
    # 插件版本
    plugin_version = "6.3.0"
    # 插件作者
    plugin_author = "kufei326"
    # 作者主页
    author_url = "https://github.com/kufei326"
    # 插件配置项ID前缀
    plugin_config_prefix = "cloudstrm_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _cron = None
    _rebuild_cron = None
    _monitor_confs = None
    _onlyonce = False
    _copy_files = False
    _rebuild = False
    _https = False
    _scheduler: Optional[BackgroundScheduler] = None
    _processed_files_json = "alist_strm_cache.json"
    _processed_files = {}

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._rebuild_cron = config.get("rebuild_cron")
            self._onlyonce = config.get("onlyonce")
            self._rebuild = config.get("rebuild")
            self._https = config.get("https")
            self._copy_files = config.get("copy_files")
            self._monitor_confs = config.get("monitor_confs")
        
        self._processed_files_json = os.path.join(self.get_data_path(), self._processed_files_json)

        self.stop_service()

        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._onlyonce:
                logger.info("云盘监控(纯API版)全量执行服务启动，立即运行一次")
                self._scheduler.add_job(func=self.scan, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="云盘监控(纯API版)全量执行")
                self._onlyonce = False
                self.__update_config()
            if self._cron:
                try:
                    self._scheduler.add_job(func=self.scan,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="云盘监控(纯API版)生成")
                except Exception as err:
                    logger.error(f"定时任务配置错误：{err}")
                    self.systemmessage.put(f"执行周期配置错误：{err}")

            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def scan(self):
        """
        遍历所有配置并为每一条执行扫描
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        
        monitor_confs = self._monitor_confs.split("\n")
        if not monitor_confs:
            logger.error("未获取到可用目录监控配置，请检查")
            return

        # 加载或初始化已处理文件缓存
        if self._rebuild or not Path(self._processed_files_json).exists():
            logger.info("重建索引或首次运行，将处理所有文件。")
            self._processed_files = {}
            self._rebuild = False
            self.__update_config()
        else:
            logger.info("加载已处理文件缓存...")
            try:
                with open(self._processed_files_json, 'r', encoding='utf-8') as f:
                    self._processed_files = json.load(f)
                logger.info(f"成功加载 {len(self._processed_files)} 条已处理记录。")
            except (IOError, json.JSONDecodeError):
                logger.error("加载缓存失败，将视为首次运行。")
                self._processed_files = {}

        for conf_line in monitor_confs:
            if not conf_line or conf_line.startswith("#"):
                continue
            
            parts = conf_line.split("#")
            if len(parts) == 5 and parts[1] == "alist":
                target_dir, _, alist_scan_path, alist_url, alist_token = parts
                logger.info(f"开始处理配置: Alist路径 '{alist_scan_path}' -> 本地目录 '{target_dir}'")
                try:
                    self.scan_alist_path_recursively(
                        target_dir=target_dir,
                        alist_scan_path=alist_scan_path,
                        alist_url=alist_url,
                        alist_token=alist_token,
                        scheme="https" if self._https else "http"
                    )
                except Exception as e:
                    logger.error(f"处理配置时发生严重错误: {conf_line} - {e}")
            else:
                logger.warning(f"配置格式不支持或错误，已跳过: {conf_line}")

        # 扫描后清理：删除已经不存在的文件对应的strm文件
        self.cleanup_removed_files()
        
        # 保存更新后的已处理文件列表
        self.save_processed_files()
        logger.info("所有配置处理完成。")
        
    def scan_alist_path_recursively(self, target_dir: str, alist_scan_path: str, alist_url: str, alist_token: str, scheme: str, current_relative_path: str = ""):
        """
        使用API递归扫描Alist目录
        """
        # 构造当前要扫描的Alist绝对路径
        if current_relative_path:
            current_alist_path = f"{alist_scan_path}/{current_relative_path}"
        else:
            current_alist_path = alist_scan_path
        
        api_endpoint = f"{scheme}://{alist_url}/api/fs/list"
        headers = {"Authorization": alist_token}
        payload = {"path": current_alist_path, "page": 1, "per_page": 0} # per_page=0 获取全部

        logger.info(f"正在扫描 Alist 路径: {current_alist_path}")

        try:
            response = requests.post(api_endpoint, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                logger.error(f"Alist API 错误 for path '{current_alist_path}': {data.get('message')}")
                return

            content = data.get("data", {}).get("content")
            if content is None:
                logger.warning(f"路径 '{current_alist_path}' 的内容为空或不存在。")
                return

            for item in content:
                item_name = item["name"]
                if current_relative_path:
                    item_path = f"{current_relative_path}/{item_name}"
                else:
                    item_path = item_name
                
                # 构造完整的Alist路径作为缓存键
                full_alist_item_path = f"{current_alist_path}/{item_name}"
                
                # 从当前 Alist 项中提取相关信息
                current_alist_item_info = {
                    "name": item_name,
                    "is_dir": item["is_dir"],
                    "size": item.get("size", 0),
                    "updated_at": item.get("updated_at", "")
                }
                
                cached_item_info = self._processed_files.get(full_alist_item_path)
                
                is_dir = item["is_dir"]
                if is_dir:
                    # 检查目录是否已更改
                    if not cached_item_info or \
                       cached_item_info.get("name") != current_alist_item_info["name"] or \
                       cached_item_info.get("updated_at") != current_alist_item_info["updated_at"]:
                        logger.info(f"目录已更改或为新目录: {full_alist_item_path}")
                        self._processed_files[full_alist_item_path] = current_alist_item_info
                    
                    # 递归扫描目录
                    self.scan_alist_path_recursively(target_dir, alist_scan_path, alist_url, alist_token, scheme, item_path)
                else:
                    # 如果是文件，进行处理
                    file_suffix = os.path.splitext(item_name)[1].lower()
                    
                    if file_suffix in MEDIA_EXT:
                        # 是媒体文件，检查是否需要更新
                        strm_link = f"{scheme}://{alist_url}/d{full_alist_item_path}"
                        local_file_path = os.path.join(target_dir, item_path)
                        local_strm_path = os.path.splitext(local_file_path)[0] + ".strm"
                        
                        # 检查媒体文件是否为新文件或已更改
                        is_changed = False
                        if not cached_item_info:
                            is_changed = True  # 新文件
                            logger.info(f"发现新媒体文件: {full_alist_item_path}")
                        elif cached_item_info.get("size") != current_alist_item_info["size"] or \
                             cached_item_info.get("updated_at") != current_alist_item_info["updated_at"] or \
                             cached_item_info.get("strm_link") != strm_link:
                            is_changed = True  # 文件已更改
                            logger.info(f"媒体文件已更改: {full_alist_item_path}")
                        
                        if is_changed:
                            success = self.create_strm_file_from_api(
                                target_dir=target_dir,
                                relative_path=item_path,
                                strm_link=strm_link
                            )
                            if success:
                                current_alist_item_info["strm_link"] = strm_link
                                current_alist_item_info["local_strm_path"] = local_strm_path
                                self._processed_files[full_alist_item_path] = current_alist_item_info
                        else:
                            logger.debug(f"媒体文件未更改（已缓存）: {full_alist_item_path}")
                            # 检查本地strm文件是否存在，如果不存在则重新创建
                            if not os.path.exists(local_strm_path):
                                logger.warning(f"缓存的 strm 文件 {local_strm_path} 缺失，正在重新创建。")
                                success = self.create_strm_file_from_api(
                                    target_dir=target_dir,
                                    relative_path=item_path,
                                    strm_link=strm_link
                                )
                                if success:
                                    self._processed_files[full_alist_item_path]["local_strm_path"] = local_strm_path
                    elif self._copy_files:
                        # 是辅助文件且开启了复制
                        logger.warning(f"辅助文件复制功能已移除，跳过文件: {item_path}")
                    else:
                        logger.debug(f"跳过非媒体文件: {item_path}")

        except requests.exceptions.RequestException as e:
            logger.error(f"请求 Alist API 失败 for path '{current_alist_path}': {e}")
        except Exception as e:
            logger.error(f"在处理路径 '{current_alist_path}' 时发生未知错误: {type(e).__name__} - {e}")


    def create_strm_file_from_api(self, target_dir: str, relative_path: str, strm_link: str):
        """
        根据API信息创建strm文件
        """
        local_file_path = os.path.join(target_dir, relative_path)
        strm_file_path = os.path.splitext(local_file_path)[0] + ".strm"

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(strm_file_path), exist_ok=True)
            
            with open(strm_file_path, 'w', encoding='utf-8') as f:
                f.write(strm_link)
            
            logger.info(f"成功创建 strm 文件: {strm_file_path}")
            return True
        except IOError as e:
            logger.error(f"写入 strm 文件失败: {strm_file_path} - {e}")
            return False
            
    def cleanup_removed_files(self):
        """清理已经不存在的文件对应的strm文件"""
        logger.info("正在启动扫描后清理...")
        
        # 收集当前扫描中遇到的所有Alist路径
        current_scan_paths = set()
        
        # 重新扫描所有配置，只收集路径信息，不处理文件
        monitor_confs = self._monitor_confs.split("\n")
        for conf_line in monitor_confs:
            if not conf_line or conf_line.startswith("#"):
                continue
            
            parts = conf_line.split("#")
            if len(parts) == 5 and parts[1] == "alist":
                target_dir, _, alist_scan_path, alist_url, alist_token = parts
                try:
                    self.collect_current_paths(
                        alist_scan_path=alist_scan_path,
                        alist_url=alist_url,
                        alist_token=alist_token,
                        scheme="https" if self._https else "http",
                        current_paths=current_scan_paths
                    )
                except Exception as e:
                    logger.error(f"收集路径信息时发生错误: {conf_line} - {e}")
        
        # 查找需要删除的文件
        paths_to_remove = []
        for alist_path, cached_info in self._processed_files.items():
            if alist_path not in current_scan_paths:
                logger.info(f"项 '{alist_path}' 在缓存中找到，但不在当前 Alist 扫描中。标记为移除。")
                if not cached_info.get("is_dir", False) and "local_strm_path" in cached_info:
                    # 这是一个媒体文件，已从 Alist 中移除
                    self.delete_local_strm_file(cached_info["local_strm_path"])
                paths_to_remove.append(alist_path)
        
        # 从缓存中移除不再存在的项
        for path in paths_to_remove:
            del self._processed_files[path]
        
        if paths_to_remove:
            logger.info(f"清理完成，移除了 {len(paths_to_remove)} 个不存在的项。")
        else:
            logger.info("清理完成，没有发现需要移除的项。")

    def collect_current_paths(self, alist_scan_path: str, alist_url: str, alist_token: str, scheme: str, current_paths: set, current_relative_path: str = ""):
        """收集当前扫描中的所有路径，用于清理"""
        if current_relative_path:
            current_alist_path = f"{alist_scan_path}/{current_relative_path}"
        else:
            current_alist_path = alist_scan_path
        
        current_paths.add(current_alist_path)
        
        api_endpoint = f"{scheme}://{alist_url}/api/fs/list"
        headers = {"Authorization": alist_token}
        payload = {"path": current_alist_path, "page": 1, "per_page": 0}
        
        try:
            response = requests.post(api_endpoint, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 200:
                return
            
            content = data.get("data", {}).get("content")
            if content is None:
                return
            
            for item in content:
                item_name = item["name"]
                full_alist_item_path = f"{current_alist_path}/{item_name}"
                current_paths.add(full_alist_item_path)
                
                if item["is_dir"]:
                    if current_relative_path:
                        item_path = f"{current_relative_path}/{item_name}"
                    else:
                        item_path = item_name
                    self.collect_current_paths(alist_scan_path, alist_url, alist_token, scheme, current_paths, item_path)
        
        except Exception as e:
            logger.error(f"收集路径信息失败 for path '{current_alist_path}': {e}")

    def delete_local_strm_file(self, local_strm_path: str):
        """删除本地 .strm 文件及其可能产生的空父目录"""
        if os.path.exists(local_strm_path):
            try:
                os.remove(local_strm_path)
                logger.info(f"已删除已移除的 strm 文件: {local_strm_path}")
                
                # 尝试删除空父目录
                parent_dir = os.path.dirname(local_strm_path)
                while parent_dir and os.path.exists(parent_dir) and not os.listdir(parent_dir):
                    try:
                        os.rmdir(parent_dir)
                        logger.info(f"已删除空目录: {parent_dir}")
                        parent_dir = os.path.dirname(parent_dir)
                    except OSError:
                        break
            except OSError as e:
                logger.error(f"删除 strm 文件 {local_strm_path} 失败: {e}")
        else:
            logger.warning(f"尝试删除不存在的 strm 文件: {local_strm_path}")
            
    def save_processed_files(self):
        """保存已处理的文件缓存到json"""
        try:
            with open(self._processed_files_json, 'w', encoding='utf-8') as f:
                json.dump(self._processed_files, f, ensure_ascii=False, indent=4)
            logger.info(f"已处理文件缓存已保存，共 {len(self._processed_files)} 条记录。")
        except IOError as e:
            logger.error(f"保存已处理文件缓存失败: {e}")

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled, "onlyonce": self._onlyonce, "rebuild": self._rebuild,
            "copy_files": self._copy_files, "https": self._https, "cron": self._cron,
            "rebuild_cron": self._rebuild_cron, "monitor_confs": self._monitor_confs,
        })

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {'component': 'VForm', 'content': [
                {'component': 'VRow', 'content': [
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}]},
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '全量运行一次'}}]},
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'rebuild', 'label': '重建索引(下次运行时生效)'}}]}
                ]},
                {'component': 'VRow', 'content': [
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [{'component': 'VTextField', 'props': {'model': 'cron', 'label': '扫描周期', 'placeholder': '0 2 * * *'}}]},
                ]},
                {'component': 'VTextarea', 'props': {'model': 'monitor_confs', 'label': '监控配置 (纯API模式)', 'rows': 5, 'placeholder': '本地目标目录#alist#Alist中扫描的起始路径#Alist服务地址#Alist的API Token'}},
                {'component': 'VRow', 'content': [
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'copy_files', 'label': '下载非媒体文件(nfo,jpg等)'}}]},
                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'https', 'label': 'Alist启用https'}}]},
                ]},
                {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal', 'text': '格式: 本地目标目录#alist#Alist扫描起始路径#Alist服务地址#Alist的API Token\n'
                                                                                               '示例: /strm/movies#alist#/aliyun/Movies#192.168.1.10:5244#alist-token-xxxx'}},
                {'component': 'VAlert', 'props': {'type': 'warning', 'variant': 'tonal', 'text': '此版本完全通过API工作，不再需要本地挂载云盘。本地目标目录必须为MoviePilot可写路径。'}}
            ]}
        ], {
            "enabled": False, "cron": "0 2 * * *", "rebuild_cron": "", "onlyonce": False, "rebuild": False,
            "copy_files": True, "https": False, "monitor_confs": "",
        }

    def stop_service(self):
        try:
            if self._scheduler and self._scheduler.running:
                self._scheduler.shutdown()
            self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
    
    @eventmanager.register(EventType.PluginAction)
    def cloudstrm_file(self, event: Event = None):
        """
        处理插件动作事件
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "cloudstrm":
                return
            
            action_type = event_data.get("type")
            if action_type == "scan_now":
                logger.info("收到立即扫描命令，开始执行...")
                self.scan()
            elif action_type == "rebuild_index":
                logger.info("收到重建索引命令，将在下次扫描时生效...")
                self._rebuild = True
                self.__update_config()
                self.systemmessage.put("重建索引已设置，将在下次扫描时生效")

    def get_state(self) -> bool:
        return self._enabled

    def get_command(self) -> List[Dict[str, Any]]:
        """
        定义插件命令
        """
        return [
            {
                "action": "cloudstrm",
                "name": "立即扫描",
                "type": "scan_now",
                "description": "立即执行一次云盘扫描并生成strm文件"
            },
            {
                "action": "cloudstrm", 
                "name": "重建索引",
                "type": "rebuild_index",
                "description": "重建已处理文件索引，下次扫描时将处理所有文件"
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        定义插件服务
        """
        if self._enabled and self._scheduler and self._scheduler.running:
            return [
                {
                    "id": "cloudstrm_scan",
                    "name": "云盘Strm扫描服务",
                    "type": "scheduler",
                    "status": True,
                    "func": self.scan_all_confs
                }
            ]
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        定义插件API
        """
        return [
            {
                "path": "/scan",
                "endpoint": self.api_scan,
                "methods": ["POST"],
                "summary": "立即扫描",
                "description": "立即执行一次云盘扫描"
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "summary": "获取状态",
                "description": "获取插件运行状态和统计信息"
            },
            {
                "path": "/rebuild",
                "endpoint": self.api_rebuild,
                "methods": ["POST"],
                "summary": "重建索引",
                "description": "重建已处理文件索引"
            }
        ]

    def get_page(self) -> List[dict]:
        """
        定义插件页面
        """
        return [
            {
                "component": "div",
                "text": "云盘Strm生成插件",
                "props": {
                    "class": "text-center"
                }
            }
        ]

    def api_scan(self):
        """
        API: 立即扫描
        """
        try:
            if not self._enabled:
                return {"code": 400, "message": "插件未启用"}
            
            # 在后台执行扫描
            if self._scheduler:
                self._scheduler.add_job(
                    func=self.scan,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=1),
                    name="API触发扫描"
                )
                return {"code": 0, "message": "扫描任务已启动"}
            else:
                return {"code": 500, "message": "调度器未运行"}
        except Exception as e:
            logger.error(f"API扫描失败: {e}")
            return {"code": 500, "message": f"扫描失败: {str(e)}"}

    def api_status(self):
        """
        API: 获取状态
        """
        try:
            status = {
                "enabled": self._enabled,
                "cron": self._cron,
                "processed_files_count": len(self._processed_files),
                "scheduler_running": self._scheduler.running if self._scheduler else False,
                "jobs": []
            }
            
            if self._scheduler:
                for job in self._scheduler.get_jobs():
                    status["jobs"].append({
                        "id": job.id,
                        "name": job.name,
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None
                    })
            
            return {"code": 0, "data": status}
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            return {"code": 500, "message": f"获取状态失败: {str(e)}"}

    def api_rebuild(self):
        """
        API: 重建索引
        """
        try:
            self._rebuild = True
            self.__update_config()
            return {"code": 0, "message": "重建索引已设置，将在下次扫描时生效"}
        except Exception as e:
            logger.error(f"设置重建索引失败: {e}")
            return {"code": 500, "message": f"设置重建索引失败: {str(e)}"}
