import requests
import os
import json
import time # 可以用于调试或未来扩展，目前直接比较字符串时间戳

# --- Configuration ---
TARGET_DIR = "/root/MoviePilot-Plugins/ty"
ALIST_SCAN_PATH = "/ty"
ALIST_URL = "193.122.122.97:5244"
ALIST_TOKEN = "alist-6fb15a8c-9a11-466a-803f-3cdca3eae4cdXYB0sfYOO8KRJrUkxg6Tk6qntAFHvUqH9mPRJT4iW6EOnoslBnDObR2sLC1SueWN"
SCHEME = "http"
# Media file extensions to look for
MEDIA_EXT = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.ts', '.rmvb',
    '.m2ts', '.mpg', '.mpeg', '.rm', '.asf', '.iso'
}

# --- Cache Configuration ---
# 缓存文件将创建在脚本执行的当前目录下
CACHE_FILE = "alist_strm_cache.json" 

# --- Cache Functions ---
def load_cache():
    """从 JSON 文件加载缓存。"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            print(f"INFO: 缓存已从 {CACHE_FILE} 加载。")
            return cache
        except json.JSONDecodeError as e:
            print(f"ERROR: 从 {CACHE_FILE} 加载缓存失败: {e}。将使用空缓存启动。")
            return {}
        except IOError as e:
            print(f"ERROR: 读取缓存文件 {CACHE_FILE} 失败: {e}。将使用空缓存启动。")
            return {}
    print(f"INFO: 缓存文件 {CACHE_FILE} 未找到。将使用空缓存启动。")
    return {}

def save_cache(cache):
    """将缓存保存到 JSON 文件。"""
    try:
        # 确保缓存文件所在的目录存在
        os.makedirs(os.path.dirname(CACHE_FILE) or '.', exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
        print(f"INFO: 缓存已保存到 {CACHE_FILE}")
    except IOError as e:
        print(f"ERROR: 保存缓存到 {CACHE_FILE} 失败: {e}")

# --- Local File Management Functions ---
def delete_local_strm_file(local_strm_path: str):
    """删除本地 .strm 文件及其可能产生的空父目录。"""
    if os.path.exists(local_strm_path):
        try:
            os.remove(local_strm_path)
            print(f"INFO: 已删除已移除的 strm 文件: {local_strm_path}")
            
            # 尝试删除空父目录，直到 TARGET_DIR
            parent_dir = os.path.dirname(local_strm_path)
            # 循环条件：parent_dir 存在，且不是 TARGET_DIR 本身，且目录为空
            while parent_dir and parent_dir != TARGET_DIR and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
                print(f"INFO: 已删除空目录: {parent_dir}")
                parent_dir = os.path.dirname(parent_dir)
        except OSError as e:
            print(f"ERROR: 删除 strm 文件 {local_strm_path} 失败: {e}")
    else:
        print(f"WARNING: 尝试删除不存在的 strm 文件: {local_strm_path}")

def create_strm_file(target_dir: str, relative_path: str, strm_link: str):
    """创建 .strm 文件并写入提供的链接。"""
    local_file_path = os.path.join(target_dir, relative_path)
    strm_file_path = os.path.splitext(local_file_path)[0] + ".strm"
    try:
        os.makedirs(os.path.dirname(strm_file_path), exist_ok=True)
        with open(strm_file_path, 'w', encoding='utf-8') as f:
            f.write(strm_link)
        print(f"SUCCESS: 已创建 strm 文件: {strm_file_path}")
        return strm_file_path # 返回路径以便缓存
    except IOError as e:
        print(f"ERROR: 写入 strm 文件失败: {strm_file_path} - {e}")
        return None

# --- Core Scanning Function with Caching ---
def scan_alist_recursively(
    target_dir: str, alist_scan_path: str, alist_url: str, alist_token: str, scheme: str,
    cache: dict, processed_alist_paths: set, current_relative_path: str = ""
):
    """使用缓存递归扫描 Alist 路径。"""
    if current_relative_path:
        current_alist_path = f"{alist_scan_path}/{current_relative_path}"
    else:
        current_alist_path = alist_scan_path

    # 将当前 Alist 目录路径添加到本次扫描中遇到的路径集合
    processed_alist_paths.add(current_alist_path)

    api_endpoint = f"{scheme}://{alist_url}/api/fs/list"
    headers = {"Authorization": alist_token}
    payload = {"path": current_alist_path, "page": 1, "per_page": 0}

    print(f"INFO: 正在扫描 Alist 路径: {current_alist_path}")

    try:
        response = requests.post(api_endpoint, json=payload, headers=headers, timeout=30)
        response.raise_for_status() # 如果请求失败，抛出 HTTPError
        data = response.json()

        if data.get("code") != 200:
            print(f"ERROR: Alist API 错误，路径 '{current_alist_path}': {data.get('message')}")
            return

        content = data.get("data", {}).get("content")
        if not content: # 如果内容为空或 None
            print(f"WARNING: 路径 '{current_alist_path}' 内容为空或不存在。")
            # 没有要处理的项，其子项如果存在于缓存中，将在扫描后清理阶段处理
            return

        for item in content:
            item_name = item["name"]
            # 相对于 TARGET_DIR 的路径，用于本地文件系统操作
            if current_relative_path:
                item_path_relative_to_target = f"{current_relative_path}/{item_name}"
            else:
                item_path_relative_to_target = item_name
            
            # Alist 中的完整路径，用于缓存和 API 调用
            full_alist_item_path = f"{current_alist_path}/{item_name}"
            
            # 将此项的完整 Alist 路径添加到当前已处理路径的集合中
            processed_alist_paths.add(full_alist_item_path)

            cached_item_info = cache.get(full_alist_item_path)
            
            # 从当前 Alist 项中提取相关信息
            current_alist_item_info = {
                "name": item_name,
                "is_dir": item["is_dir"],
                "size": item.get("size", 0), # 目录可能没有大小，默认为 0
                "updated_at": item.get("updated_at", "") # 如果不存在，使用空字符串
            }

            if item["is_dir"]:
                # 检查目录本身是否已更改（例如，名称或更新时间）
                # 我们缓存目录主要是为了跟踪它们的存在和更新时间，以便未来优化
                # 并确保它们在消失时从缓存中移除。
                if not cached_item_info or \
                   cached_item_info.get("name") != current_alist_item_info["name"] or \
                   cached_item_info.get("updated_at") != current_alist_item_info["updated_at"]:
                    print(f"INFO: 目录已更改或为新目录: {full_alist_item_path}")
                    cache[full_alist_item_path] = current_alist_item_info
                
                # 递归扫描目录
                scan_alist_recursively(
                    target_dir, alist_scan_path, alist_url, alist_token, scheme,
                    cache, processed_alist_paths, item_path_relative_to_target
                )
            else: # 是文件
                file_suffix = os.path.splitext(item_name)[1].lower()
                if file_suffix in MEDIA_EXT:
                    strm_link = f"{scheme}://{alist_url}/d{full_alist_item_path}"
                    local_file_path = os.path.join(target_dir, item_path_relative_to_target)
                    local_strm_path = os.path.splitext(local_file_path)[0] + ".strm"

                    # 检查媒体文件是否为新文件或已更改
                    # 更改包括大小、更新时间，或者 strm_link 本身是否会更改
                    is_changed = False
                    if not cached_item_info:
                        is_changed = True # 新文件
                    elif cached_item_info.get("size") != current_alist_item_info["size"] or \
                         cached_item_info.get("updated_at") != current_alist_item_info["updated_at"] or \
                         cached_item_info.get("strm_link") != strm_link: # 检查生成的链接是否更改
                        is_changed = True
                    
                    if is_changed:
                        print(f"INFO: 媒体文件已更改或为新文件: {full_alist_item_path}")
                        created_path = create_strm_file(
                            target_dir=target_dir,
                            relative_path=item_path_relative_to_target,
                            strm_link=strm_link
                        )
                        if created_path:
                            current_alist_item_info["strm_link"] = strm_link
                            current_alist_item_info["local_strm_path"] = created_path
                            cache[full_alist_item_path] = current_alist_item_info
                    else:
                        print(f"INFO: 媒体文件未更改（已缓存）: {full_alist_item_path}")
                        # 即使 Alist 中的文件未更改，也要确保本地 .strm 文件仍然存在
                        if not os.path.exists(local_strm_path):
                            print(f"WARNING: 缓存的 strm 文件 {local_strm_path} 缺失，正在重新创建。")
                            created_path = create_strm_file(
                                target_dir=target_dir,
                                relative_path=item_path_relative_to_target,
                                strm_link=strm_link
                            )
                            if created_path:
                                # 如果重新创建，更新缓存中的 local_strm_path
                                cache[full_alist_item_path]["local_strm_path"] = created_path
                else:
                    print(f"INFO: 跳过非媒体文件: {item_path_relative_to_target}")
                    # 如果一个文件以前是媒体文件（因此在缓存中），但现在不是了，
                    # 它将在扫描后清理阶段从缓存中移除，因为这里不会将其重新添加为媒体文件。
                    # 其本地 .strm 文件也将被删除。这是正确的行为。

    except requests.exceptions.RequestException as e:
        print(f"ERROR: 请求 Alist API 失败，路径 '{current_alist_path}': {e}")
    except Exception as e:
        print(f"ERROR: 处理路径 '{current_alist_path}' 时发生未知错误: {type(e).__name__} - {e}")

# --- Main Execution ---
if __name__ == "__main__":
    print("INFO: 启动带缓存的 Alist STRM 生成器。")
    
    # 加载现有缓存
    cache = load_cache()
    
    # 用于跟踪本次扫描中遇到的所有 Alist 路径的集合
    processed_alist_paths = set() 

    # 将 Alist 根扫描路径添加到 processed_alist_paths，以确保它不被视为“已移除”
    # 这在 ALIST_SCAN_PATH 本身是一个存在的目录时很重要。
    processed_alist_paths.add(ALIST_SCAN_PATH)

    # 启动递归扫描
    scan_alist_recursively(
        target_dir=TARGET_DIR,
        alist_scan_path=ALIST_SCAN_PATH,
        alist_url=ALIST_URL,
        alist_token=ALIST_TOKEN,
        scheme=SCHEME,
        cache=cache,
        processed_alist_paths=processed_alist_paths
    )

    # --- 扫描后清理 ---
    print("INFO: 正在启动扫描后清理...")
    paths_to_remove_from_cache = []
    for alist_path, cached_info in cache.items():
        if alist_path not in processed_alist_paths:
            print(f"INFO: 项 '{alist_path}' 在缓存中找到，但不在当前 Alist 扫描中。标记为移除。")
            if not cached_info["is_dir"] and "local_strm_path" in cached_info:
                # 这是一个媒体文件，已从 Alist 中移除或不再是媒体文件
                delete_local_strm_file(cached_info["local_strm_path"])
            paths_to_remove_from_cache.append(alist_path)
    
    # 从缓存中移除不再存在于 Alist 中的项
    for p in paths_to_remove_from_cache:
        del cache[p]
    
    # 保存更新后的缓存
    save_cache(cache)
    print("INFO: 扫描完成，缓存已更新。")
