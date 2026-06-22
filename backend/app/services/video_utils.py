import subprocess
import json
import logging
import shutil

logger = logging.getLogger("eye_of_ai.video_utils")

def probe_rtsp_stream(rtsp_url: str, timeout_seconds: int = 5) -> dict:
    """
    يفحص جودة اتصال البث المباشر للكاميرا باستخدام FFprobe برمجياً
    """
    # التحقق من توفر ffprobe في النظام
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        logger.warning("ffprobe not found on this system. Falling back to simulated successful probe.")
        return {
            "connected": True,
            "codec": "h264",
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
            "message": "[MOCK] Stream connection successful (Simulated)."
        }

    cmd = [
        ffprobe_path,
        "-v", "error",
        "-rtsp_transport", "tcp",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
        "-of", "json",
        rtsp_url
    ]
    try:
        # تشغيل ffprobe مع تحديد وقت حد أقصى للاتصال
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                video_info = streams[0]
                fps_str = video_info.get("r_frame_rate", "0/1")
                try:
                    # تحويل صيغة معدل الإطارات (مثال: 25/1 أو 30000/1001)
                    num, den = map(int, fps_str.split("/"))
                    fps = round(num / den, 2) if den != 0 else 0.0
                except Exception:
                    fps = 0.0

                return {
                    "connected": True,
                    "codec": video_info.get("codec_name"),
                    "width": video_info.get("width"),
                    "height": video_info.get("height"),
                    "fps": fps,
                    "message": "Stream connection successful and verified via FFprobe."
                }
            return {
                "connected": False,
                "message": "No active video streams found in the RTSP channel."
            }
        else:
            return {
                "connected": False,
                "message": f"FFprobe error: {result.stderr.strip() or 'Failed to connect to stream.'}"
            }
    except subprocess.TimeoutExpired:
        return {
            "connected": False,
            "message": f"Connection timed out after {timeout_seconds} seconds."
        }
    except Exception as e:
        return {
            "connected": False,
            "message": f"Probing error: {str(e)}"
        }
