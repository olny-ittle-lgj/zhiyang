import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video import VideoAnalysisError, _probe_video, _subtitle_text, analyze_video_text


class VideoMetadataTests(unittest.TestCase):
    def test_probe_reads_duration_and_dimensions(self):
        stderr = b"Duration: 00:01:15.30, start: 0.000000\nStream #0:0: Video: h264, yuv420p, 1920x1080, 30 fps"
        completed = subprocess.CompletedProcess([], 0, b"", stderr)
        with patch("app.video._run_ffmpeg", return_value=completed):
            self.assertEqual(
                _probe_video(Path("lecture.mp4")),
                {"duration": 75.3, "width": 1920, "height": 1080},
            )

    def test_probe_rejects_unreadable_stream(self):
        completed = subprocess.CompletedProcess([], 1, b"", b"Invalid data found")
        with patch("app.video._run_ffmpeg", return_value=completed):
            with self.assertRaises(VideoAnalysisError):
                _probe_video(Path("broken.mp4"))

    def test_probe_rejects_video_over_duration_limit(self):
        stderr = b"Duration: 00:31:00.00, start: 0.000000\nStream #0:0: Video: h264, 1920x1080, 30 fps"
        completed = subprocess.CompletedProcess([], 1, b"", stderr)
        with patch("app.video._run_ffmpeg", return_value=completed):
            with self.assertRaisesRegex(VideoAnalysisError, "时长"):
                _probe_video(Path("long.mp4"))

    def test_subtitles_are_parsed_as_cues(self):
        srt = (
            b"1\r\n00:00:01,000 --> 00:00:03,000\r\nFirst line\r\ncontinued\r\n\r\n"
            b"2\r\n00:00:04,000 --> 00:00:05,000\r\n<b>Second cue</b>\r\n"
        )
        completed = subprocess.CompletedProcess([], 0, srt, b"")
        with patch("app.video._run_ffmpeg", return_value=completed):
            self.assertEqual(
                _subtitle_text(Path("lecture.mp4")),
                ["First line continued", "Second cue"],
            )


class VideoAnalysisTests(unittest.TestCase):
    def test_combines_subtitles_and_deduplicated_frame_lines(self):
        with (
            patch("app.video._probe_video", return_value={"duration": 12.5, "width": 1280, "height": 720}),
            patch("app.video._subtitle_text", return_value=["Introduction", "Introduction", "Summary"]),
            patch(
                "app.video._keyframe_text",
                return_value=(["Shared heading\nFirst point", "Shared heading\nSecond point"], 2, 0.91),
            ),
        ):
            result = analyze_video_text(b"video", ".mp4")

        self.assertEqual(result["subtitle_lines"], 2)
        self.assertEqual(result["keyframes"], 2)
        self.assertEqual(result["confidence"], 0.91)
        self.assertEqual(
            result["content"],
            "Introduction\nSummary\n\nShared heading\n\nFirst point\n\nSecond point",
        )


if __name__ == "__main__":
    unittest.main()
