import json
import math
import subprocess
from fractions import Fraction
from statistics import median
from pathlib import Path

MAX_PIXELS = 8_847_360
VIDEO_CODECS = ("h264", "hevc")
AUDIO_CODECS = ("aac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le")


class InvalidVideo(ValueError):
    pass


def inspect(path: Path, max_duration: int):
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
        videos = [s for s in streams if s["codec_type"] == "video"]
        if len(videos) != 1:
            raise InvalidVideo("请使用单画面的 MP4 或 MOV 视频。")
        video = videos[0]
        duration = float(info["format"]["duration"])
        if (
            "mp4" not in info["format"]["format_name"].split(",")
            or video["codec_name"] not in VIDEO_CODECS
        ):
            raise InvalidVideo("支持 MP4 / MOV 的 H.264 或 HEVC 视频。")
        if not math.isfinite(duration) or not 0 < duration <= max_duration:
            raise InvalidVideo(f"视频时长须在 {max_duration // 60} 分钟以内。")
        audio = [s for s in streams if s["codec_type"] == "audio"]
        if len(audio) > 1 or any(s["codec_name"] not in AUDIO_CODECS for s in audio):
            raise InvalidVideo("暂不支持此视频的音轨格式。")
        width, height = video["width"], video["height"]
        if min(width, height) <= 0 or max(width, height) > 4096 or width * height > MAX_PIXELS:
            raise InvalidVideo("视频分辨率须在 4K 以内。")
        rotation = int(float(video.get("tags", {}).get("rotate", 0)))
        for side in video.get("side_data_list", []):
            rotation = int(side.get("rotation", rotation))
        packet_info = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        timestamps = sorted(
            float(line.split(",")[0])
            for line in packet_info.stdout.splitlines()
            if line and line.split(",")[0] != "N/A"
        )
        differences = [b - a for a, b in zip(timestamps, timestamps[1:])]
        step = median(differences) if differences else 0
        vfr = any(abs(value - step) > 0.0001 for value in differences)
        rate = video.get("r_frame_rate", "0/0")
        try:
            if not 0 < float(Fraction(rate)) <= 240:
                rate = video["avg_frame_rate"]
            if float(Fraction(rate)) <= 0:
                raise ValueError("Invalid frame rate")
        except (ValueError, ZeroDivisionError):
            rate = "30"
        hdr = video.get("color_transfer") in ("smpte2084", "arib-std-b67")
        transcode = (
            video["codec_name"] != "h264"
            or video.get("pix_fmt") != "yuv420p"
            or rotation % 360
            or hdr
            or vfr
        )
        remux = info["format"].get("tags", {}).get("major_brand", "").strip() == "qt" or any(
            s["codec_name"] != "aac" for s in audio
        )
        return {
            "duration_s": duration,
            "width": height if rotation % 180 else width,
            "height": width if rotation % 180 else height,
            "_prepare": "transcode" if transcode else "remux" if remux else "none",
            "_vfr": vfr,
            "_fps": rate,
            "_audio": audio[0]["codec_name"] if audio else None,
            "_codec": video["codec_name"],
            "_hdr": hdr,
        }
    except InvalidVideo:
        raise
    except (subprocess.SubprocessError, KeyError, StopIteration, ValueError, TypeError) as error:
        raise InvalidVideo("无法读取视频，请检查文件是否完整。") from error


def probe(path: Path, max_duration: int):
    return inspect(path, max_duration)


def public_metadata(info):
    return {key: info[key] for key in ("duration_s", "width", "height")}


def conversion_command(source, output, info, max_bytes):
    filters = []
    if info["_hdr"]:
        filters.append(
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv"
        )
    if info.get("_vfr"):
        filters.append("fps=" + info["_fps"])
    # Encoder dimensions must be even; padding never crops source pixels.
    filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p")
    command = [
        "ffmpeg",
        "-nostdin",
        "-xerror",
        "-filter_threads",
        "2",
        "-v",
        "error",
        "-y",
        "-threads",
        "2",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
    ]
    if info["_prepare"] == "transcode":
        command += [
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-threads",
            "2",
            "-fps_mode",
            "passthrough",
        ]
        if info["_hdr"]:
            command += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    else:
        command += ["-c:v", "copy"]
    return command + [
        "-c:a",
        "copy" if info.get("_audio") == "aac" else "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        "-fs",
        str(max_bytes),
        "-f",
        "mp4",
        str(output),
    ]
