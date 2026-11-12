import json
import math
import subprocess
from pathlib import Path


class InvalidVideo(ValueError):
    pass


def probe(path: Path, max_duration: int):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        info = json.loads(result.stdout)
        streams = info["streams"]
        video = next(item for item in streams if item["codec_type"] == "video")
        duration = float(info["format"]["duration"])
        formats = info["format"]["format_name"].split(",")
        if "mp4" not in formats or video["codec_name"] != "h264":
            raise InvalidVideo("请上传 H.264 编码的 MP4 视频。")
        if not math.isfinite(duration) or not 0 < duration <= max_duration:
            raise InvalidVideo(f"视频时长须在 {max_duration // 60} 分钟以内。")
        if any(item["codec_type"] == "audio" and item["codec_name"] != "aac" for item in streams):
            raise InvalidVideo("视频音轨须为 AAC，或使用无音轨视频。")
        if video["width"] <= 0 or video["height"] <= 0:
            raise InvalidVideo("视频尺寸无效。")
        return {"duration_s": duration, "width": video["width"], "height": video["height"]}
    except InvalidVideo:
        raise
    except (subprocess.SubprocessError, KeyError, StopIteration, ValueError) as error:
        raise InvalidVideo("无法读取视频，请检查文件是否完整。") from error
