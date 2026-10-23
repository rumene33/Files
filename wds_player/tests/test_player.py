"""Тестове без хардуер:  python3 -m unittest discover -s tests"""

import os
import struct
import sys
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n  # noqa: E402
from audio import AudioPlayer, NullAudio, find_audio  # noqa: E402
from dmx_engine import BLACKOUT, NullDMXOutput  # noqa: E402
from player import DMXPlayer, State, next_start  # noqa: E402
from settings import Settings  # noqa: E402
from wds_parser import (FORMAT_RAW, FORMAT_RECORDS, FRAME_SIZE, HEADER_SIZE,  # noqa: E402
                        WDSError, WDSFile, parse_header)


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "Test.wds")


def make_raw_wds(path, frames, header_text=b"My Show\x00song.mp3\x00", extra=b""):
    header = bytearray(HEADER_SIZE)
    header[8:8 + len(header_text)] = header_text
    with open(path, "wb") as f:
        f.write(header)
        for i in range(frames):
            f.write(bytes([i % 256]) * FRAME_SIZE)
        f.write(extra)


def make_wds(path, frames, step_ms=40, pad=500, name=b"Rec Show", mp3=b"song.mp3"):
    """Формат със записи: кадър i -> канал 1 = i, канал 3 = 200 само в кадър 0."""
    header = bytearray(HEADER_SIZE)
    header[0:2] = b"OA"
    header[6:6 + len(name)] = name
    header[0x32:0x32 + len(mp3)] = mp3
    with open(path, "wb") as f:
        f.write(header + bytes(pad))
        for i in range(frames):
            chans = [(1, i % 256)] + ([(3, 200)] if i == 0 else [])
            f.write(struct.pack("<IH", i * step_ms, 3 * len(chans)))
            for ch, v in chans:
                f.write(struct.pack("<HB", ch, v))


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "Edna_Bulgarska_Roza.wds")

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_format(self):
        make_wds(self.path, 50)
        with WDSFile(self.path) as w:
            i = w.info
            self.assertEqual(i.format, FORMAT_RECORDS)
            self.assertEqual(i.data_offset, HEADER_SIZE + 500)
            self.assertEqual((i.show_name, i.audio_file), ("Rec Show", "song.mp3"))
            self.assertEqual(i.frame_count, 50)
            self.assertAlmostEqual(i.duration, 2.0)
            self.assertEqual(i.channels, (1, 3))
            self.assertAlmostEqual(w.frame_time(10), 0.4)
            f = w.read_frame(7)
            self.assertEqual((f[0], f[1], f[2], len(f)), (7, 0, 200, 512))  # канал 3 се запазва
            self.assertEqual(w.frame_at(0.41), 10)

    def test_raw_format(self):
        make_raw_wds(self.path, 50, extra=b"\x01\x02")
        with WDSFile(self.path) as w:
            self.assertEqual(w.info.format, FORMAT_RAW)
            self.assertEqual(w.info.frame_count, 50)
            self.assertAlmostEqual(w.info.duration, 2.0)
            self.assertEqual((w.info.show_name, w.info.audio_file), ("My Show", "song.mp3"))
            self.assertEqual(w.read_frame(7), bytes([7]) * FRAME_SIZE)
            self.assertEqual(len(list(w.frames(45))), 5)
            self.assertTrue(w.info.warnings)
            with self.assertRaises(IndexError):
                w.read_frame(50)

    @unittest.skipUnless(os.path.exists(FIXTURE), "няма tests/data/Test.wds")
    def test_real_depence_file(self):
        with WDSFile(FIXTURE) as w:
            i = w.info
            self.assertEqual(i.format, FORMAT_RECORDS)
            self.assertEqual((i.show_name, i.audio_file), ("Test", "Audio Video Sync Test.mp3"))
            self.assertEqual(i.data_offset, 17507)
            self.assertEqual(i.frame_count, 1578)
            self.assertEqual(i.channels, (1, 2, 3))
            self.assertFalse(i.warnings)
            self.assertAlmostEqual(i.duration, 63.12, places=2)
            f = w.read_frame(w.frame_at(3.08))
            self.assertEqual(tuple(f[:3]), (255, 0, 0))  # първата червена светкавица

    def test_fallback_name_and_utf16(self):
        self.assertEqual(parse_header(bytes(1024), "stem"), ("stem", None))
        hdr = "Шоу".encode("utf-16-le") + b"\x00\x00" + "C:\\music\\track.mp3".encode("utf-16-le")
        self.assertEqual(parse_header(hdr, "stem"), ("stem", "track.mp3"))

    def test_too_small(self):
        make_raw_wds(self.path, 0)
        with self.assertRaises(WDSError):
            WDSFile(self.path)


class PlayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "show.wds")
        make_wds(self.path, 10)  # 0.4 s @ 25 fps
        self.out = NullDMXOutput()
        self.player = DMXPlayer(self.out)
        self.player.start()

    def tearDown(self):
        self.player.shutdown()
        self.tmp.cleanup()

    def wait_for(self, cond, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            s = self.player.snapshot()
            if cond(s):
                return s
            time.sleep(0.01)
        self.fail(f"timeout, snapshot={self.player.snapshot()}")

    def test_play_to_end_then_blackout(self):
        self.player.load(self.path)
        self.wait_for(lambda s: s.info is not None)
        t = time.perf_counter()
        self.player.play()
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.wait_for(lambda s: s.state is State.IDLE)
        elapsed = time.perf_counter() - t
        self.assertGreater(elapsed, 0.33)
        self.assertLess(elapsed, 0.8)
        self.assertEqual(self.out.last_frame, BLACKOUT)
        self.assertEqual(self.player.snapshot().frame_index, 0)

    def test_pause_resume_stop(self):
        self.player.load(self.path)
        self.wait_for(lambda s: s.info is not None)
        self.player.play()
        self.wait_for(lambda s: s.frame_index >= 3)
        self.player.pause()
        s = self.wait_for(lambda s: s.state is State.PAUSED)
        idx = s.frame_index
        time.sleep(0.2)
        self.assertEqual(self.player.snapshot().frame_index, idx)
        self.assertEqual(self.out.last_frame[0], idx - 1)  # кадърът се държи
        self.player.play()
        self.wait_for(lambda s: s.frame_index > idx)
        self.player.stop()
        s = self.wait_for(lambda s: s.state is State.IDLE)
        self.assertEqual(s.frame_index, 0)
        self.assertEqual(self.out.last_frame, BLACKOUT)

    def test_loop_restarts_without_blackout(self):
        self.player.set_loops(0)
        self.player.load(self.path)
        self.wait_for(lambda s: s.info is not None)
        self.player.play()
        self.wait_for(lambda s: s.frame_index >= 8)
        time.sleep(0.6)  # повече от цяла дължина (0.4 s) - трябва още да свири
        s = self.player.snapshot()
        self.assertIs(s.state, State.PLAYING)
        self.assertNotEqual(self.out.last_frame, BLACKOUT)
        self.player.set_loops(1)  # веднъж -> спира в края на текущото възпроизвеждане
        self.wait_for(lambda s: s.state is State.IDLE)
        self.assertEqual(self.out.last_frame, BLACKOUT)

    def test_play_without_file(self):
        self.player.play()
        self.wait_for(lambda s: s.error is not None)
        self.assertIs(self.player.snapshot().state, State.IDLE)


class ShowPlaybackTest(unittest.TestCase):
    """Повторения, пауза между тях, звук и график (без хардуер)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.path = os.path.join(self.dir, "show.wds")
        make_wds(self.path, 10, mp3=b"Song.mp3")   # 0.4 s
        self.song = os.path.join(self.dir, "song.MP3")  # главни/малки букви различни
        open(self.song, "wb").close()
        self.out = NullDMXOutput()
        self.audio = NullAudio()
        self.player = DMXPlayer(self.out, audio=self.audio)
        self.player.start()

    def tearDown(self):
        self.player.shutdown()
        self.tmp.cleanup()

    def wait_for(self, cond, timeout=4.0):
        end = time.time() + timeout
        while time.time() < end:
            s = self.player.snapshot()
            if cond(s):
                return s
            time.sleep(0.01)
        self.fail(f"timeout, snapshot={self.player.snapshot()}, audio={self.audio.calls}")

    def load(self, **kw):
        self.player.load(self.path, **kw)
        return self.wait_for(lambda s: s.info is not None)

    def plays(self):
        return [c for c in self.audio.calls if c[0] == "play"]

    def test_audio_found_case_insensitive_and_loaded(self):
        s = self.load()
        self.assertEqual(s.audio_path, self.song)
        self.assertIn(("load", self.song), self.audio.calls)

    def test_audio_missing_reports_error(self):
        os.unlink(self.song)
        s = self.load()
        self.assertIsNone(s.audio_path)
        self.assertIn("Song.mp3", s.error)

    def test_manual_audio_and_back_to_auto(self):
        other = os.path.join(self.dir, "other.mp4")
        open(other, "wb").close()
        self.load()
        self.player.set_audio(other)
        s = self.wait_for(lambda s: s.audio_path == other)
        self.assertIn(("load", other), self.audio.calls)
        self.player.set_audio(None)
        self.wait_for(lambda s: s.audio_path == self.song)

    def test_load_count_signals_finished_load(self):
        before = self.player.snapshot().load_count
        self.load()
        s = self.wait_for(lambda s: s.load_count == before + 1)
        self.assertEqual(s.audio_path, self.song)
        self.player.load(os.path.join(self.dir, "missing.wds"))   # неуспешно зареждане също се брои
        s = self.wait_for(lambda s: s.load_count == before + 2)
        self.assertIsNone(s.info)

    def test_volume_is_forwarded(self):
        self.player.set_volume(35)
        self.player.set_volume(0)
        self.assertEqual([c for c in self.audio.calls if c[0] == "volume"],
                         [("volume", 35), ("volume", 0)])

    def test_audio_offset_is_forwarded(self):
        self.player.set_audio_offset(150)
        self.player.set_audio_offset(-80)
        self.assertEqual([c for c in self.audio.calls if c[0] == "offset"],
                         [("offset", 0.15), ("offset", -0.08)])

    def test_load_with_saved_override(self):
        other = os.path.join(self.dir, "other.mp3")
        open(other, "wb").close()
        s = self.load(audio=other)
        self.assertEqual(s.audio_path, other)

    def test_audio_follows_play_pause_stop(self):
        self.load()
        self.player.play()
        self.wait_for(lambda s: s.frame_index >= 3)
        self.player.pause()
        s = self.wait_for(lambda s: s.state is State.PAUSED)
        self.player.play()
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.player.stop()
        self.wait_for(lambda s: s.state is State.IDLE)
        kinds = [c[0] for c in self.audio.calls if c[0] != "load"]
        self.assertEqual(kinds, ["play", "pause", "play", "stop"])
        resume_pos = self.plays()[1][1]
        self.assertGreater(resume_pos, 0.05)       # продължава от позицията, не от нулата

    def test_loops_count_and_audio_restarts(self):
        self.load()
        self.player.set_loops(3)
        t = time.perf_counter()
        self.player.play()
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.wait_for(lambda s: s.state is State.IDLE)
        elapsed = time.perf_counter() - t
        self.assertGreater(elapsed, 1.1)           # 3 x 0.4 s
        self.assertLess(elapsed, 2.0)
        self.assertEqual(len(self.plays()), 3)     # старт + 2 рестарта на звука
        for _, pos in self.plays():
            self.assertLess(pos, 0.1)
        self.assertEqual(self.audio.calls[-1], ("stop",))
        self.assertEqual(self.out.last_frame, BLACKOUT)

    def test_gap_between_loops_is_blackout(self):
        self.load()
        self.player.set_loops(2)
        self.player.set_loop_gap(1)
        t = time.perf_counter()
        self.player.play()
        s = self.wait_for(lambda s: s.waiting_until > 0)
        self.assertEqual(s.loop_number, 2)
        self.assertEqual(self.out.last_frame, BLACKOUT)
        self.assertGreater(s.waiting_until, time.perf_counter() + 0.3)
        self.wait_for(lambda s: s.state is State.IDLE, timeout=5)
        elapsed = time.perf_counter() - t
        self.assertGreater(elapsed, 1.7)           # 0.4 + 1 + 0.4
        self.assertLess(elapsed, 2.6)
        self.assertEqual(len(self.plays()), 2)

    def test_endless_until_stop(self):
        self.load()
        self.player.set_loops(0)
        self.player.play()
        self.wait_for(lambda s: s.loop_number >= 3)
        self.assertIs(self.player.snapshot().state, State.PLAYING)
        self.player.stop()
        self.wait_for(lambda s: s.state is State.IDLE)

    def test_daily_schedule_starts_show(self):
        self.load()
        target = datetime.now() + timedelta(seconds=2)
        self.player.set_schedule(True, target.hour, target.minute, target.second)
        time.sleep(1.0)
        self.assertIs(self.player.snapshot().state, State.IDLE)  # още не е време
        self.wait_for(lambda s: s.state is State.PLAYING, timeout=3)

    def test_schedule_disabled_does_not_start(self):
        self.load()
        target = datetime.now() + timedelta(seconds=1)
        self.player.set_schedule(False, target.hour, target.minute, target.second)
        time.sleep(2.0)
        self.assertIs(self.player.snapshot().state, State.IDLE)

    def test_next_start(self):
        now = datetime(2026, 10, 20, 12, 0, 0, 500000)
        self.assertIsNone(next_start((False, 7, 43, 0), now))
        self.assertEqual(next_start((True, 7, 43, 0), now), datetime(2026, 10, 21, 7, 43, 0))
        self.assertEqual(next_start((True, 12, 10, 5), now), datetime(2026, 10, 20, 12, 10, 5))


class FindAudioTest(unittest.TestCase):
    def test_header_name_then_stem_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            wds = os.path.join(d, "Show.wds")
            open(wds, "wb").close()
            self.assertIsNone(find_audio(wds, "Track.mp3"))
            open(os.path.join(d, "Show.mp4"), "wb").close()
            self.assertEqual(find_audio(wds, None), os.path.join(d, "Show.mp4"))
            open(os.path.join(d, "TRACK.MP3"), "wb").close()
            self.assertEqual(find_audio(wds, "C:\\music\\track.mp3"), os.path.join(d, "TRACK.MP3"))


class AudioPlayerIpcTest(unittest.TestCase):
    """Проверка на протокола към mpv със заместител (tests/fake_mpv.py)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "mpv.log")
        os.environ["FAKE_MPV_LOG"] = self.log
        fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_mpv.py")
        self.audio = AudioPlayer(mpv_cmd=[sys.executable, fake], offset=0.0)
        self.song = os.path.join(self.tmp.name, "a.mp3")

    def tearDown(self):
        self.audio.close()
        self.tmp.cleanup()

    def commands(self):
        time.sleep(0.15)
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_protocol(self):
        self.audio.load(self.song)
        self.audio.play(2.5)
        self.audio.pause()
        self.audio.stop()
        cmds = self.commands()
        self.assertEqual(cmds, [
            ["loadfile", self.song, "replace"],
            ["seek", 2.5, "absolute"],
            ["set_property", "pause", False],
            ["set_property", "pause", True],
            ["set_property", "pause", True],
            ["seek", 0, "absolute"],
        ])

    def test_offset_and_close(self):
        self.audio._offset = 0.2
        self.audio.load(self.song)
        self.audio.play(1.0)
        self.assertEqual(self.commands()[1], ["seek", 1.2, "absolute"])
        proc = self.audio._proc
        self.audio.close()
        self.assertIsNotNone(proc.wait(3))
        self.assertFalse(os.path.exists(self.audio._sock_path))

    def test_volume_set_live_and_clamped(self):
        self.audio.load(self.song)
        self.audio.set_volume(40)
        self.audio.set_volume(250)
        self.assertEqual([c for c in self.commands() if c[:2] == ["set_property", "volume"]],
                         [["set_property", "volume", 40], ["set_property", "volume", 100]])

    def test_volume_passed_at_mpv_start(self):
        a = AudioPlayer(mpv_cmd=[sys.executable, os.path.join(os.path.dirname(__file__), "fake_mpv.py")],
                        volume=35)
        self.assertEqual(a._volume, 35)

    def test_query_reads_mpv_properties(self):
        self.audio.load(self.song)
        self.assertEqual(self.audio.query("time-pos"), 1.5)
        self.assertEqual(self.audio.query("current-ao"), "alsa")
        self.assertIs(self.audio.query("pause"), False)

    def test_start_from_zero_skips_seek(self):
        self.audio.load(self.song)
        self.audio.play(0.0)              # файлът вече чака в 0 -> само пускане
        self.audio.stop()
        self.audio.play(0.0)              # след стоп също е в 0
        cmds = self.commands()
        self.assertEqual(cmds, [
            ["loadfile", self.song, "replace"],
            ["set_property", "pause", False],
            ["set_property", "pause", True],
            ["seek", 0, "absolute"],
            ["set_property", "pause", False],
        ])

    def test_negative_offset_delays_unpause_and_pause_cancels_it(self):
        self.audio.set_offset(-0.3)       # звукът да закъснее с 300 ms
        self.audio.load(self.song)
        self.audio.play(0.0)
        early = self.commands()
        self.assertIn(["seek", 0, "absolute"], early)
        self.assertNotIn(["set_property", "pause", False], early)   # още не е пуснат
        time.sleep(0.4)
        self.assertIn(["set_property", "pause", False], self.commands())
        # отказ: пауза преди изтичане на закъснението -> звукът не се пуска
        self.audio.play(0.0)
        self.audio.pause()
        n = len(self.commands())
        time.sleep(0.5)
        self.assertEqual(len(self.commands()), n)

    def test_missing_mpv_reports_error(self):
        from audio import AudioError
        broken = AudioPlayer(mpv_cmd=["/nonexistent/mpv"])
        self.assertFalse(broken.available)
        with self.assertRaises(AudioError):
            broken.load(self.song)


class SettingsTest(unittest.TestCase):
    def test_roundtrip_clamp_and_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x", "settings.json")
            s = Settings(loops=3, loop_gap=10, start_h=7, start_m=43,
                         audio_offset_ms=-250,
                         last_file="/a/b.wds", audio_overrides={"/a/b.wds": "/a/c.mp3"})
            s.save(p)
            self.assertEqual(Settings.load(p), s)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"loops": 5000, "start_h": 99, "audio_offset_ms": 5000, "unknown": 1}, f)
            r = Settings.load(p)
            self.assertEqual((r.loops, r.start_h, r.audio_offset_ms), (999, 23, 1000))
            with open(p, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(Settings.load(p), Settings())


class I18nTest(unittest.TestCase):
    def setUp(self):
        self.old = i18n.get_lang()
        self.old_cfg = i18n.CONFIG_FILE
        self.tmp = tempfile.TemporaryDirectory()
        i18n.CONFIG_FILE = os.path.join(self.tmp.name, "cfg", "lang")

    def tearDown(self):
        i18n.CONFIG_FILE = self.old_cfg
        i18n.set_lang(self.old, save=False)
        self.tmp.cleanup()

    def test_every_key_has_both_languages(self):
        for key, entry in i18n.STRINGS.items():
            for lang in i18n.LANGS:
                self.assertTrue(entry.get(lang), f"{key}/{lang}")

    def test_switch_and_format(self):
        i18n.set_lang("bg")
        self.assertEqual(i18n.t("start"), "СТАРТ")
        i18n.set_lang("en")
        self.assertEqual(i18n.t("start"), "START")
        self.assertEqual(i18n.t("frame_info", i=3, n=10, fps=25), "frame 3 / 10 @ 25 fps")
        self.assertEqual(i18n.toggle_lang(), "bg")

    def test_persistence(self):
        i18n.set_lang("en")                # записва във временен файл
        i18n.set_lang("bg", save=False)
        self.assertEqual(i18n.load_saved(), "en")

    def test_error_translation(self):
        msg = "Портът /dev/serial0 не може да се отвори: boom"
        i18n.set_lang("bg", save=False)
        self.assertEqual(i18n.tr_error(msg), msg)
        i18n.set_lang("en", save=False)
        self.assertEqual(i18n.tr_error(msg), "Port /dev/serial0 cannot be opened: boom")
        self.assertEqual(i18n.tr_error("Няма зареден .wds файл"), "No .wds file loaded")
        self.assertEqual(i18n.tr_error("непознато"), "непознато")
        self.assertIsNone(i18n.tr_error(None))


if __name__ == "__main__":
    unittest.main()
