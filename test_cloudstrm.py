import requests
import os
import json

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

# --- Core Functions (adapted from the plugin) ---

# get_file_raw_url 函数不再需要，因为我们直接构建链接

def create_strm_file(target_dir: str, relative_path: str, strm_link: str):
    """Creates a .strm file with the provided link."""
    local_file_path = os.path.join(target_dir, relative_path)
    strm_file_path = os.path.splitext(local_file_path)[0] + ".strm"
    try:
        os.makedirs(os.path.dirname(strm_file_path), exist_ok=True)
        with open(strm_file_path, 'w', encoding='utf-8') as f:
            f.write(strm_link) # 写入构建好的链接
        print(f"SUCCESS: Created strm file: {strm_file_path}")
    except IOError as e:
        print(f"ERROR: Failed to write strm file: {strm_file_path} - {e}")

def scan_alist_recursively(target_dir: str, alist_scan_path: str, alist_url: str, alist_token: str, scheme: str, current_relative_path: str = ""):
    """Recursively scans an Alist path using its API."""
    if current_relative_path:
        current_alist_path = f"{alist_scan_path}/{current_relative_path}"
    else:
        current_alist_path = alist_scan_path

    api_endpoint = f"{scheme}://{alist_url}/api/fs/list"
    headers = {"Authorization": alist_token}
    payload = {"path": current_alist_path, "page": 1, "per_page": 0}

    print(f"INFO: Scanning Alist path: {current_alist_path}")

    try:
        response = requests.post(api_endpoint, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 200:
            print(f"ERROR: Alist API error for path '{current_alist_path}': {data.get('message')}")
            return

        content = data.get("data", {}).get("content")
        if content is None:
            print(f"WARNING: Path '{current_alist_path}' content is empty or does not exist.")
            return

        for item in content:
            item_name = item["name"]
            if current_relative_path:
                item_path = f"{current_relative_path}/{item_name}"
            else:
                item_path = item_name

            if item["is_dir"]:
                scan_alist_recursively(target_dir, alist_scan_path, alist_url, alist_token, scheme, item_path)
            else:
                file_suffix = os.path.splitext(item_name)[1].lower()
                if file_suffix in MEDIA_EXT:
                    # 获取文件在 Alist 中的完整路径
                    # 这就是你想要的 {current_alist_path} 部分
                    full_file_path_in_alist = f"{current_alist_path}/{item_name}"

                    # 构建 strm 文件中的链接
                    strm_link = f"{scheme}://{alist_url}/d{full_file_path_in_alist}"
                    
                    create_strm_file(
                        target_dir=target_dir,
                        relative_path=item_path,
                        strm_link=strm_link # 传递构建好的链接
                    )
                else:
                    print(f"INFO: Skipping non-media file: {item_path}")

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to request Alist API for path '{current_alist_path}': {e}")
    except Exception as e:
        print(f"ERROR: An unknown error occurred while processing path '{current_alist_path}': {type(e).__name__} - {e}")

# --- Main Execution ---
if __name__ == "__main__":
    scan_alist_recursively(
        target_dir=TARGET_DIR,
        alist_scan_path=ALIST_SCAN_PATH,
        alist_url=ALIST_URL,
        alist_token=ALIST_TOKEN,
        scheme=SCHEME
    )
    print("INFO: Scan finished.")
