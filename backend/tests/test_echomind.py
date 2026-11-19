"""EchoMind 商业级多用户全龄段平台全链路自动化测试。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

_TMP_DIR = tempfile.TemporaryDirectory(prefix="echomind_v2_test_")
os.environ["ECHOMIND_DATA_DIR"] = _TMP_DIR.name

from app.main import app  # noqa: E402
from app.services.audio_norm import pcm16_to_wav_bytes  # noqa: E402
from app.services.brain import SafeMotionGuard  # noqa: E402
from app.services.voiceprint import cosine_similarity, extract_acoustic_embedding  # noqa: E402


def _make_synthetic_voice_wav(f0_hz: float, duration_sec: float = 1.6) -> bytes:
    sr = 16000
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    sig = (
        0.45 * np.sin(2 * np.pi * f0_hz * t)
        + 0.25 * np.sin(2 * np.pi * f0_hz * 2 * t)
        + 0.12 * np.sin(2 * np.pi * f0_hz * 3 * t)
        + 0.05 * np.sin(2 * np.pi * f0_hz * 4 * t)
    )
    pcm = (np.clip(sig, -0.95, 0.95) * 32767).astype(np.int16).tobytes()
    return pcm16_to_wav_bytes(pcm, sr)


def test_zero_fake_data_and_rbac_users():
    """验证零假数据初始态、首个注册为 admin、普通用户权限隔离与管理员用户 CRUD。"""
    with TestClient(app) as client:
        # 1. 未初始化时状态检查与未登录拦截
        st = client.get("/api/auth/status").json()
        assert st["initialized"] is False
        assert st["user_count"] == 0
        assert client.get("/api/dashboard").status_code == 401

        # 2. 首个注册账号自动成为 admin
        r1 = client.post("/api/auth/register", json={"username": "boss", "password": "pass1234", "display_name": "家庭管理员"})
        assert r1.status_code == 200
        assert r1.json()["user"]["role"] == "admin"
        admin_hdr = {"Authorization": f"Bearer {r1.json()['token']}"}

        # 3. 验证系统初始完全零假数据：0 设备、0 成员、0 专辑、0 书籍
        dash = client.get("/api/dashboard", headers=admin_hdr).json()
        assert dash["devices"] == []
        assert dash["pending_devices"] == []
        assert dash["members"] == []
        assert dash["albums"] == []
        assert dash["book_count"] == 0

        # 4. 第二个注册账号自动为普通 user，且无权调用 /api/admin/*
        r2 = client.post("/api/auth/register", json={"username": "parent2", "password": "pass1234"})
        assert r2.status_code == 200
        assert r2.json()["user"]["role"] == "user"
        user_hdr = {"Authorization": f"Bearer {r2.json()['token']}"}

        assert client.get("/api/admin/users", headers=user_hdr).status_code == 403
        assert client.get("/api/admin/users", headers=admin_hdr).status_code == 200

        # 5. 管理员创建、禁用、删普通用户
        c_u = client.post("/api/admin/users", headers=admin_hdr, json={"username": "grandma", "password": "pass1234", "role": "user"})
        assert c_u.status_code == 200
        gid = c_u.json()["id"]
        assert client.patch(f"/api/admin/users/{gid}", headers=admin_hdr, json={"is_active": False}).status_code == 200
        assert client.post("/api/auth/login", json={"username": "grandma", "password": "pass1234"}).status_code == 403
        assert client.delete(f"/api/admin/users/{gid}", headers=admin_hdr).status_code == 200


def test_device_lifecycle_discovery_and_volume_guard():
    """验证音箱手动添加、连接上线、音量护耳限幅、陌生设备自动发现认领与解绑删除。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "boss", "password": "pass1234"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # 1. 手动添加客厅音箱（上限 65%）
        dev = client.post(
            "/api/devices",
            headers=hdr,
            json={"name": "客厅小爱音箱", "device_type": "speaker_xiaoai", "room": "客厅", "max_volume": 65},
        ).json()
        did = dev["id"]
        tok = dev["auth_token"]

        # 2. 获取预填专属桥接脚本
        script = client.get(f"/api/devices/{did}/bridge-script", headers=hdr)
        assert script.status_code == 200
        assert did in script.text
        assert tok in script.text

        # 3. 调节音量超过 max_volume(65) 应被截断为 65
        patched = client.patch(f"/api/devices/{did}", headers=hdr, json={"volume": 98}).json()
        assert patched["volume"] == 65

        # 4. 带合法 token 连入 /ws/speaker 上线
        with client.websocket_connect(f"/ws/speaker?device_id={did}&token={tok}") as spk_ws:
            devs = client.get("/api/devices", headers=hdr).json()["devices"]
            assert any(d["id"] == did and d["online"] == 1 for d in devs)
            spk_ws.send_text(json.dumps({"type": "ping"}))
            assert json.loads(spk_ws.receive_text())["type"] == "pong"

        # 5. 陌生未绑定设备连入 -> 自动生成 6 位 pair_code 并出现在待认领池
        with client.websocket_connect("/ws/speaker?device_id=new-xiaoai-99&name=儿童房新音箱") as new_ws:
            pair_msg = json.loads(new_ws.receive_text())
            assert pair_msg["type"] == "pair_required"
            pair_code = pair_msg["pair_code"]
            assert len(pair_code) == 6

            pending = client.get("/api/devices", headers=hdr).json()["pending_devices"]
            assert any(p["id"] == "new-xiaoai-99" for p in pending)

            # 认领成功
            claim = client.post(
                "/api/devices/claim",
                headers=hdr,
                json={"pair_code": pair_code, "name": "儿童房主音箱", "room": "儿童房", "max_volume": 60},
            )
            assert claim.status_code == 200
            assert claim.json()["paired"] == 1
            claimed_notify = json.loads(new_ws.receive_text())
            assert claimed_notify["type"] == "claimed"

        # 6. 删除设备应彻底从列表中消失
        assert client.delete(f"/api/devices/{did}", headers=hdr).status_code == 200
        assert client.delete("/api/devices/new-xiaoai-99", headers=hdr).status_code == 200
        assert client.get("/api/devices", headers=hdr).json()["devices"] == []


def test_full_age_books_sources_and_media_crud():
    """验证管理员内容源、示范包按需导入、全阶段书籍文本转有声章节、Range 206 流与清理删除。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "boss", "password": "pass1234"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # 1. 管理员一键导入全年龄段示范包（覆盖 S1_0_3 ~ S5_12_18 及 Pre_A1 ~ B2_PLUS）
        seeded = client.post("/api/admin/seed-sample-catalog", headers=hdr)
        assert seeded.status_code == 200
        assert seeded.json()["books_added"] >= 5

        # 2. 按阶段筛选书籍
        s4_books = client.get("/api/books?age_stage=S4_9_12", headers=hdr).json()
        assert len(s4_books) >= 1

        # 3. 新建一本 6-9 岁英语桥梁书并从正文文本直接合成护耳有声章节
        book = client.post(
            "/api/books",
            headers=hdr,
            json={
                "title": "Magic Treehouse Sample",
                "author": "Test Author",
                "category": "bridge_book",
                "age_stage": "S3_6_9",
                "english_level": "A2",
                "language": "en",
            },
        ).json()
        bid = book["id"]
        ch = client.post(
            f"/api/books/{bid}/chapters/from-text",
            headers=hdr,
            json={"title": "Chapter 1: Into the Woods", "text_content": "Jack and Annie climbed up the rope ladder into the quiet woods."},
        )
        assert ch.status_code == 200
        ch_data = ch.json()
        ch_path = Path(ch_data["file_path"])
        assert ch_path.exists()
        assert ch_data["lufs_normalized"] == 1

        # HTTP Range 206 流验证
        r_stream = client.get(f"/api/books/chapters/{ch_data['id']}/stream", headers={"Range": "bytes=0-511"})
        assert r_stream.status_code == 206
        assert len(r_stream.content) == 512

        # 删除书籍必须连带清理磁盘上的音频文件
        assert client.delete(f"/api/books/{bid}", headers=hdr).status_code == 200
        assert not ch_path.exists()

        # 4. 管理员播客/内容采集源 CRUD
        src = client.post(
            "/api/content-sources",
            headers=hdr,
            json={
                "name": "科学少年广播RSS",
                "source_type": "podcast_rss",
                "url": "https://example.com/podcast.xml",
                "age_stage": "S4_9_12",
                "english_level": "B1",
                "auto_sync": True,
                "sync_interval_hours": 12,
            },
        )
        assert src.status_code == 200
        sid = src.json()["id"]
        assert client.patch(f"/api/content-sources/{sid}", headers=hdr, json={"auto_sync": False}).status_code == 200
        assert client.delete(f"/api/content-sources/{sid}", headers=hdr).status_code == 200


def test_dynamic_growth_voiceprint_isolation_and_schedules():
    """验证动态全龄阶段推算、声纹注册/识别/清空重置、记忆隔离与定时课表完整 CRUD。"""
    dad_wav = _make_synthetic_voice_wav(115.0)
    dad_wav_2 = _make_synthetic_voice_wav(118.0)
    child_wav = _make_synthetic_voice_wav(320.0)
    assert cosine_similarity(extract_acoustic_embedding(dad_wav[44:]), extract_acoustic_embedding(dad_wav_2[44:])) > 0.9

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "boss", "password": "pass1234"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # 1. 创建一位 10 岁（2016-05 出生）的孩子与一位爸爸成员
        teen = client.post(
            "/api/members",
            headers=hdr,
            json={"name": "大宝", "nickname": "乐乐", "role": "child", "birth_date": "2016-05", "english_stage": "B1"},
        ).json()
        assert teen["age_stage"] == "S4_9_12"  # 自动推算 9-12 岁阶段
        assert teen["age_months"] >= 110

        dad = client.post(
            "/api/members",
            headers=hdr,
            json={"name": "爸爸", "nickname": "老爸", "role": "adult"},
        ).json()

        # 写入一条爸爸私密备忘
        mem = client.post(
            "/api/memories",
            headers=hdr,
            json={"member_id": dad["id"], "scope": "personal", "content": "爸爸私密备忘：周五去体检"},
        ).json()
        assert client.patch(f"/api/memories/{mem['id']}", headers=hdr, json={"content": "爸爸私密备忘：周五上午九点去体检"}).status_code == 200

        # 2. 注册爸爸声纹 -> 爸爸音频识别成功 -> 儿童高频音频降级 child_safe 不可读体检隐私 -> 清空声纹
        up = client.post(f"/api/members/{dad['id']}/voiceprint", headers=hdr, files={"file": ("dad.wav", dad_wav, "audio/wav")})
        assert up.status_code == 200
        ident = client.post("/api/members/identify-audio", headers=hdr, files={"file": ("dad2.wav", dad_wav_2, "audio/wav")}).json()
        assert ident["member_id"] == dad["id"]
        assert ident["safety_mode"] == "adult_private"

        ident_c = client.post("/api/members/identify-audio", headers=hdr, files={"file": ("c.wav", child_wav, "audio/wav")}).json()
        assert ident_c["safety_mode"] == "child_safe"

        r_safe = client.post("/api/interact", headers=hdr, json={"text": "爸爸有什么秘密备忘？", "simulated_member_id": 0}).json()
        assert "体检" not in r_safe["reply_text"]
        r_dad = client.post("/api/interact", headers=hdr, json={"text": "我有什么备忘？", "simulated_member_id": dad["id"]}).json()
        assert "体检" in r_dad["reply_text"]

        clr = client.delete(f"/api/members/{dad['id']}/voiceprint", headers=hdr)
        assert clr.status_code == 200
        assert clr.json()["has_voiceprint"] is False

        # 3. 定时课表自定义工作日 CRUD
        sch = client.post(
            "/api/schedules",
            headers=hdr,
            json={"name": "上学日早间英语", "cron_time": "07:30", "days_of_week": "1,2,3,4,5", "task_type": "english_immersion", "target_volume": 45},
        )
        assert sch.status_code == 200
        sch_id = sch.json()["id"]
        assert client.put(
            f"/api/schedules/{sch_id}",
            headers=hdr,
            json={"name": "上学日早间英语（改）", "cron_time": "07:40", "days_of_week": "1,2,3,4,5", "task_type": "english_immersion", "target_volume": 40, "fade_out": False, "enabled": True},
        ).status_code == 200
        assert client.delete(f"/api/schedules/{sch_id}", headers=hdr).status_code == 200
        assert SafeMotionGuard.sanitize("spin_slow", 5000, 95)["speed"] == 40


def test_structured_english_courses_local_scan_and_voice_cache_fallback(monkeypatch):
    """验证英语系列课程生成与播放、本地目录扫描（含音乐与绘本图书+txt）、语音点播本地优先->在线播放自动缓存到本地。"""
    import functools
    import http.server
    import threading
    import time

    from app.services import brain as brain_mod

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "boss", "password": "pass1234"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # 1. 验证 6 套 24 节英语系列课与主题生成 4 节定制课
        seed_res = client.post("/api/english/courses/seed-builtin", headers=hdr)
        assert seed_res.status_code == 200
        courses = client.get("/api/english/courses", headers=hdr).json()
        assert len(courses) >= 6
        assert any(c["stage"] == "B2_PLUS" and c["total_lessons"] == 4 for c in courses)

        gen_c = client.post(
            "/api/english/courses/generate",
            headers=hdr,
            json={"topic": "恐龙世界探险", "stage": "A1"},
        )
        assert gen_c.status_code == 200
        gen_data = gen_c.json()
        assert gen_data["total_lessons"] == 4
        first_lid = gen_data["lessons"][0]["id"]

        play_l = client.post(f"/api/english/lessons/{first_lid}/play", headers=hdr, json={"mark_completed": True})
        assert play_l.status_code == 200
        assert play_l.json()["lesson"]["completed"] == 1
        stream_l = client.get(play_l.json()["stream_url"])
        assert stream_l.status_code == 200
        assert len(stream_l.content) > 256

        # 2. 本地目录挂载扫描（同时导入音乐与绘本有声章节+.txt文稿）
        local_dir = Path(_TMP_DIR.name) / "custom_local_media"
        (local_dir / "music").mkdir(parents=True, exist_ok=True)
        (local_dir / "books" / "小狐狸绘本").mkdir(parents=True, exist_ok=True)
        (local_dir / "music" / "本地儿歌测试.wav").write_bytes(_make_synthetic_voice_wav(260.0, 1.0))
        (local_dir / "books" / "小狐狸绘本" / "第1章_进森林.wav").write_bytes(_make_synthetic_voice_wav(280.0, 1.0))
        (local_dir / "books" / "小狐狸绘本" / "第1章_进森林.txt").write_text("小狐狸背着小书包走进森林。", encoding="utf-8")

        fld = client.post(
            "/api/media/local-folders",
            headers=hdr,
            json={"name": "我的本地仓库", "folder_path": str(local_dir), "media_type": "auto", "age_stage": "S2_3_6"},
        )
        assert fld.status_code == 200
        scan = client.post(f"/api/media/local-folders/{fld.json()['id']}/scan", headers=hdr)
        assert scan.status_code == 200
        assert scan.json()["tracks_added"] >= 1
        assert scan.json()["chapters_added"] >= 1

        local_books = client.get("/api/media/local-files?kind=book", headers=hdr).json()
        assert any(it["title"] == "第1章_进森林" for it in local_books)

        # 3. 语音点播：本地命中直接走本地流
        r_local = client.post("/api/interact", headers=hdr, json={"text": "播放本地儿歌测试", "simulated_member_id": 0})
        assert r_local.status_code == 200
        d_local = r_local.json()
        assert d_local["track_url"].startswith("/api/media/tracks/")
        assert "本地" in d_local["reply_text"]

        # 4. 语音点播：本地未命中 -> Mock 在线直链音源，立即返回 /api/media/live-stream/... 并在后台自动缓存到本地
        mock_srv_dir = Path(_TMP_DIR.name) / "mock_web"
        mock_srv_dir.mkdir(parents=True, exist_ok=True)
        (mock_srv_dir / "twinkle_star.wav").write_bytes(_make_synthetic_voice_wav(440.0, 1.2))

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

        handler = functools.partial(QuietHandler, directory=str(mock_srv_dir))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()
        port = httpd.server_address[1]

        async def _fake_online_search(q: str, limit: int = 3):
            return [
                {
                    "title": "小星星哄睡测试曲",
                    "duration_sec": 2,
                    "uploader": "mock",
                    "url": f"http://127.0.0.1:{port}/twinkle_star.wav",
                }
            ]

        monkeypatch.setattr(brain_mod, "search_online_audio", _fake_online_search)
        monkeypatch.setenv("ECHOMIND_DISABLE_ONLINE_SEARCH", "0")

        try:
            r_online = client.post("/api/interact", headers=hdr, json={"text": "播放小星星", "simulated_member_id": 0})
            assert r_online.status_code == 200
            d_online = r_online.json()
            assert d_online["track_url"].startswith("/api/media/live-stream/")
            assert "在线播放" in d_online["reply_text"]

            # 等待后台异步缓存落盘完成
            cached_found = False
            for _ in range(30):
                time.sleep(0.25)
                albs = client.get("/api/media/albums", headers=hdr).json()
                for a in albs:
                    if any("小星星哄睡测试曲" in t["title"] for t in (a.get("tracks") or [])):
                        cached_found = True
                        break
                if cached_found:
                    break
            assert cached_found is True

            # 再次语音点播同名曲目，应直接命中本地持久化轨道而非重复在线下载
            r_again = client.post("/api/interact", headers=hdr, json={"text": "播放小星星哄睡测试曲", "simulated_member_id": 0})
            assert r_again.status_code == 200
            assert r_again.json()["track_url"].startswith("/api/media/tracks/")
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_echomind_v3_tags_unified_catalog_room_queue_and_voice_controls():
    """验证 EchoMind 二级分类标签、统一容器融汇与按需流、收件箱转正、房间队列自动连播与全场景语音播控。"""
    with TestClient(app) as client:
        hdr = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'boss', 'password': 'pass1234'}).json()['token']}"}
        u_hdr = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'parent2', 'password': 'pass1234'}).json()['token']}"}

        # 1. 二级分类标签预设加载与 RBAC 增删控制
        music_tags = client.get("/api/media/tags?channel=music", headers=u_hdr)
        assert music_tags.status_code == 200
        assert any(t["name"] == "哄睡轻音乐" for t in music_tags.json())

        assert client.post("/api/media/tags", headers=u_hdr, json={"channel": "story", "name": "越权标签"}).status_code == 403
        cr_tag = client.post("/api/media/tags", headers=hdr, json={"channel": "story", "name": "成长童话", "sort_order": 5})
        assert cr_tag.status_code == 200
        tag_id = cr_tag.json()["id"]
        assert any(t["name"] == "成长童话" for t in client.get("/api/media/tags?channel=story", headers=hdr).json())
        assert client.delete(f"/api/media/tags/{tag_id}", headers=hdr).status_code == 200

        # 2. 统一容器融汇验证（含英语课与有声书）+ 按需流即时合成
        unified = client.get("/api/media/albums?exclude_inbox=true", headers=hdr)
        assert unified.status_code == 200
        albs = unified.json()
        eng_albs = [a for a in albs if a["category"] == "english" and a.get("tracks")]
        story_albs = [a for a in albs if a["category"] == "story" and a.get("tracks")]
        assert len(eng_albs) >= 1 and len(story_albs) >= 1

        # 从尚未生成磁盘音频文件的英语单集发起流请求，应触发按需即时合成并返回 200 音频
        lazy_track = next(
            (t for a in eng_albs for t in a["tracks"] if not t.get("file_path")),
            eng_albs[0]["tracks"][0],
        )
        r_lazy = client.get(f"/api/media/tracks/{lazy_track['id']}/stream")
        assert r_lazy.status_code == 200
        assert len(r_lazy.content) > 256

        # 新建正式专辑并通过文本直接合成 2 集故事单集
        alb_resp = client.post(
            "/api/media/albums",
            headers=hdr,
            json={"title": "晚安成长故事辑", "category": "story", "sub_tag": "睡前绘本", "age_stage": "S2_3_6", "language": "zh"},
        )
        assert alb_resp.status_code == 200
        new_alb_id = alb_resp.json()["id"]

        for ep_title, ep_text in (
            ("故事1_月亮的晚安信", "月亮婆婆给森林里的小兔寄去了一封晚安信。"),
            ("故事2_小熊的梦境列车", "小熊坐着火车穿过棉花糖云朵去睡觉啦。"),
        ):
            r_tr = client.post(
                f"/api/media/albums/{new_alb_id}/tracks/from-text",
                headers=hdr,
                json={"title": ep_title, "text_content": ep_text, "language": "zh"},
            )
            assert r_tr.status_code == 200
            assert r_tr.json()["stream_url"].startswith("/api/media/tracks/")

        # 3. 语音缓存收件箱单集一键转正移入正式专辑
        inbox_albs = client.get("/api/media/albums?only_inbox=true", headers=hdr).json()
        inbox_tracks = [t for a in inbox_albs for t in (a.get("tracks") or [])]
        star_track = next((t for t in inbox_tracks if "小星星哄睡测试曲" in t["title"]), None)
        assert star_track is not None

        moved = client.patch(f"/api/media/tracks/{star_track['id']}", headers=hdr, json={"album_id": new_alb_id})
        assert moved.status_code == 200
        assert moved.json()["album_id"] == new_alb_id

        inbox_after = client.get("/api/media/albums?only_inbox=true", headers=hdr).json()
        assert not any(t["id"] == star_track["id"] for a in inbox_after for t in (a.get("tracks") or []))
        refreshed = [a for a in client.get("/api/media/albums?exclude_inbox=true", headers=hdr).json() if a["id"] == new_alb_id][0]
        assert len(refreshed["tracks"]) == 3

        # 4. 房间推送整张专辑队列 + WebSocket track_ended 自动连播推进 + 按集睡眠截停
        dev = client.post(
            "/api/devices",
            headers=hdr,
            json={"name": "婴儿房音箱", "device_type": "speaker_xiaoai", "room": "婴儿房", "max_volume": 60, "wake_word": "小爱同学"},
        ).json()
        did = dev["id"]
        tok = dev["auth_token"]

        try:
            with client.websocket_connect(f"/ws/speaker?device_id={did}&token={tok}") as spk_ws:
                push = client.post(
                    "/api/playback/push",
                    headers=hdr,
                    json={"device_ids": [did], "album_id": new_alb_id, "start_index": 0, "loop_mode": "sequential", "sleep_episodes": 2},
                )
                assert push.status_code == 200
                msg1 = json.loads(spk_ws.receive_text())
                assert msg1["type"] == "play_url"
                assert msg1["title"] == "故事1_月亮的晚安信"

                rooms = client.get("/api/playback/rooms", headers=hdr).json()
                rm = next(r for r in rooms if r["id"] == did)
                assert rm["session"]["status"] == "playing"
                assert rm["session"]["current_index"] == 0
                assert rm["session"]["sleep_remaining_episodes"] == 2
                assert len(rm["session"]["queue"]) == 3

                # 模拟第 1 集播放完成 -> 自动推送第 2 集，剩余集数减为 1
                spk_ws.send_text(json.dumps({"type": "track_ended"}))
                msg2 = json.loads(spk_ws.receive_text())
                assert msg2["type"] == "play_url"
                assert msg2["title"] == "故事2_小熊的梦境列车"

                rooms2 = client.get("/api/playback/rooms", headers=hdr).json()
                rm2 = next(r for r in rooms2 if r["id"] == did)
                assert rm2["session"]["current_index"] == 1
                assert rm2["session"]["sleep_remaining_episodes"] == 1

                # 模拟第 2 集播放完成 -> 触发 2 集睡眠定时停止
                spk_ws.send_text(json.dumps({"type": "track_ended"}))
                msg_stop = json.loads(spk_ws.receive_text())
                assert msg_stop["type"] == "control"
                assert msg_stop["command"] == "stop"

                rooms3 = client.get("/api/playback/rooms", headers=hdr).json()
                rm3 = next(r for r in rooms3 if r["id"] == did)
                assert rm3["session"]["status"] == "stopped"

                # 5. 全场景语音播控状态机验证
                assert client.post("/api/playback/push", headers=hdr, json={"device_ids": [did], "album_id": new_alb_id}).status_code == 200
                assert json.loads(spk_ws.receive_text())["type"] == "play_url"

                r_vol = client.post("/api/interact", headers=hdr, json={"text": "音量调到 85", "simulated_member_id": 0, "device_id": did})
                assert r_vol.status_code == 200
                assert r_vol.json()["control_action"] == {"action": "volume_set", "value": 60}
                assert json.loads(spk_ws.receive_text()) == {"type": "set_volume", "volume": 60}

                r_next = client.post("/api/interact", headers=hdr, json={"text": "下一首", "simulated_member_id": 0, "device_id": did})
                assert r_next.status_code == 200
                assert r_next.json()["control_action"]["action"] == "next"
                assert json.loads(spk_ws.receive_text())["type"] == "play_url"

                r_sleep = client.post("/api/interact", headers=hdr, json={"text": "20分钟后停止", "simulated_member_id": 0, "device_id": did})
                assert r_sleep.status_code == 200
                assert r_sleep.json()["control_action"] == {"action": "sleep_minutes", "minutes": 20}

                r_pause = client.post("/api/interact", headers=hdr, json={"text": "暂停播放", "simulated_member_id": 0, "device_id": did})
                assert r_pause.status_code == 200
                assert r_pause.json()["control_action"]["action"] == "pause"
                assert json.loads(spk_ws.receive_text()) == {"type": "control", "command": "pause"}

                r_resume = client.post("/api/interact", headers=hdr, json={"text": "继续播放", "simulated_member_id": 0, "device_id": did})
                assert r_resume.status_code == 200
                assert r_resume.json()["control_action"]["action"] == "resume"
                assert json.loads(spk_ws.receive_text())["type"] == "play_url"
        finally:
            client.delete(f"/api/devices/{did}", headers=hdr)

