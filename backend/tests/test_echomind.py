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
        assert client.put("/api/settings", headers=hdr, json={"quiet_hours_enabled": False}).status_code == 200
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": False}).status_code == 200

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
        assert client.put("/api/settings", headers=hdr, json={"quiet_hours_enabled": False}).status_code == 200
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": False}).status_code == 200

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
        assert client.put("/api/settings", headers=hdr, json={"quiet_hours_enabled": False}).status_code == 200
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": False}).status_code == 200

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
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": True}).status_code == 200
        assert SafeMotionGuard.sanitize("spin_slow", 5000, 95)["speed"] == 0
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": False}).status_code == 200


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
        assert client.put("/api/settings", headers=hdr, json={"quiet_hours_enabled": False}).status_code == 200
        assert client.post("/api/schedules/quiet-toggle", headers=hdr, json={"active": False}).status_code == 200

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


def test_cloud_music_multi_source_search_toplists_and_batch_download():
    """验证 go-music-dl 多源搜歌原唱置顶、热歌榜单、歌单解析、实时代理试听与云端批量下歌入库。"""
    import http.server
    import threading
    import time
    from urllib.parse import parse_qs, urlparse

    sample_audio = _make_synthetic_voice_wav(392.0, 1.0)

    class MockMusicDlHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path == "/music/api/ai/index":
                body = json.dumps({"name": "go-music-dl", "sources": {"song": ["netease", "qq", "kugou"]}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/music/search":
                stype = (qs.get("type") or ["song"])[0]
                if stype == "playlist":
                    html_doc = (
                        '<div class="playlist-card"><button class="ctrl-btn primary" '
                        'data-name="华语经典怀旧歌单" data-cover="" data-creator="音乐达人" '
                        'data-track-count="50" data-source="qq" data-external-id="pl-101" '
                        'data-content-type="playlist"></button></div>'
                    )
                else:
                    html_doc = (
                        '<ul>'
                        '<li class="song-card" data-id="song-live" data-source="qq" data-name="晴天 (Live版)" '
                        'data-artist="周杰伦" data-album="演唱会" data-cover="" data-duration="280" data-extra="{}"></li>'
                        '<li class="song-card" data-id="song-orig" data-source="netease" data-name="晴天" '
                        'data-artist="周杰伦" data-album="叶惠美" data-cover="" data-duration="269" '
                        'data-extra=\'{"hash":"abc123"}\'></li>'
                        '</ul>'
                    )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_doc.encode("utf-8"))
                return

            if parsed.path == "/music/toplists":
                html_doc = (
                    '<a class="toplist-card" href="/music/toplist_songs?source=netease&amp;toplist_id=3778678'
                    '&amp;toplist_name=%E7%83%AD%E6%AD%8C%E6%A6%9C&amp;track_count=200">'
                    '<span><i class="fa-solid fa-headphones"></i> 88.8亿</span></a>'
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_doc.encode("utf-8"))
                return

            if parsed.path == "/music/toplist_songs":
                html_doc = (
                    '<ul><li class="song-card" data-id="top-1" data-source="netease" '
                    'data-name="七里香" data-artist="周杰伦" data-album="七里香" '
                    'data-cover="" data-duration="299" data-extra="{}"></li></ul>'
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_doc.encode("utf-8"))
                return

            if parsed.path == "/music/download":
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(sample_audio)
                return

            if parsed.path == "/music/download_lrc":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("[00:01.00]刮风这天 我试过握着你手".encode("utf-8"))
                return

            self.send_response(404)
            self.end_headers()

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockMusicDlHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    mock_url = f"http://127.0.0.1:{httpd.server_address[1]}"

    try:
        with TestClient(app) as client:
            hdr = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'boss', 'password': 'pass1234'}).json()['token']}"}

            # 1. 保存并探测音乐引擎连通性
            assert client.put("/api/settings", headers=hdr, json={"music_dl_url": mock_url}).status_code == 200
            probe = client.post("/api/settings/test-music-dl", headers=hdr, json={"music_dl_url": mock_url})
            assert probe.status_code == 200
            assert probe.json()["ok"] is True
            assert "netease" in probe.json()["sources"]

            # 2. 搜歌原唱智能置顶、搜歌单、热歌榜解析
            sr = client.get("/api/cloud-music/search", headers=hdr, params={"q": "周杰伦 晴天", "search_type": "song"})
            assert sr.status_code == 200
            songs = sr.json()["songs"]
            assert len(songs) == 2
            assert songs[0]["name"] == "晴天"
            assert songs[0]["extra"]["hash"] == "abc123"

            pl = client.get("/api/cloud-music/search", headers=hdr, params={"q": "怀旧", "search_type": "playlist"})
            assert pl.status_code == 200
            assert pl.json()["collections"][0]["id"] == "pl-101"

            tops = client.get("/api/cloud-music/toplists", headers=hdr)
            assert tops.status_code == 200
            assert tops.json()[0]["name"] == "热歌榜"
            assert tops.json()[0]["play_count_text"] == "88.8亿"

            top_songs = client.get("/api/cloud-music/toplists/songs", headers=hdr, params={"source": "netease", "toplist_id": "3778678"})
            assert top_songs.status_code == 200
            assert top_songs.json()[0]["name"] == "七里香"

            # 3. 实时流代理试听
            stream_r = client.get("/api/cloud-music/stream", params={"id": "song-orig", "source": "netease", "name": "晴天", "artist": "周杰伦"})
            assert stream_r.status_code == 200
            assert len(stream_r.content) > 256

            # 4. 批量下载到新私有专辑（含歌词入库与 -16 LUFS 转码）
            batch = client.post(
                "/api/cloud-music/batch-download",
                headers=hdr,
                json={"songs": [songs[0]], "new_album_title": "华语金曲私有辑"},
            )
            assert batch.status_code == 200
            job_id = batch.json()["job_id"]

            job_done = False
            for _ in range(30):
                time.sleep(0.2)
                jobs = client.get("/api/cloud-music/jobs", headers=hdr).json()
                cur = next((j for j in jobs if j["id"] == job_id), None)
                if cur and cur["status"] == "done":
                    assert cur["tracks_added"] == 1
                    job_done = True
                    break
            assert job_done is True

            albs = client.get("/api/media/albums?exclude_inbox=true", headers=hdr).json()
            target_alb = next((a for a in albs if a["title"] == "华语金曲私有辑"), None)
            assert target_alb is not None
            assert len(target_alb["tracks"]) == 1
            tr = target_alb["tracks"][0]
            assert tr["title"] == "晴天 - 周杰伦"
            assert "刮风这天" in tr["text_content"]

            r_local_play = client.get(f"/api/media/tracks/{tr['id']}/stream")
            assert r_local_play.status_code == 200
            assert len(r_local_play.content) > 256
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_series_three_level_resume_cross_season_voice_collect_and_english_ladder(monkeypatch):
    """验证三级分类(系列→季→集)、断点续播、语音跳季跳集、跨季自动连播、音箱语音采集+AI自动分类+播报通知与英语L1-L5启蒙。"""
    import time
    from pathlib import Path
    from app.services import ai_curator
    from app.services.collector import insert_normalized_track

    with TestClient(app) as client:
        hdr = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'boss', 'password': 'pass1234'}).json()['token']}"}
        # 确保夜间免打扰关闭，不受 UTC 时间影响
        assert client.put("/api/settings", headers=hdr, json={"quiet_hours_enabled": False}).status_code == 200

        # 1. 创建一级系列《汪汪队》（自动建第1季）+ 新增第2季 + 每季导入 2 集真实音频
        s_resp = client.post(
            "/api/media/series",
            headers=hdr,
            json={
                "title": "汪汪队",
                "channel": "story",
                "cover_emoji": "🐶",
                "auto_create_first_season": True,
                "first_season_label": "第1季",
            },
        )
        assert s_resp.status_code == 200
        series_id = s_resp.json()["id"]
        s1_album_id = s_resp.json()["seasons"][0]["id"]

        s2_resp = client.post(
            f"/api/media/series/{series_id}/seasons",
            headers=hdr,
            json={"season_num": 2, "season_label": "第2季"},
        )
        assert s2_resp.status_code == 200
        s2_album_id = s2_resp.json()["id"]

        wav_bytes = _make_synthetic_voice_wav(f0_hz=420.0, duration_sec=0.6)
        s1_t1 = client.post("/api/media/collect/upload", headers=hdr, data={"album_id": str(s1_album_id)}, files={"file": ("第1集_救援出发.wav", wav_bytes, "audio/wav")}).json()
        s1_t2 = client.post("/api/media/collect/upload", headers=hdr, data={"album_id": str(s1_album_id)}, files={"file": ("第2集_阿奇立功.wav", wav_bytes, "audio/wav")}).json()
        s2_t1 = client.post("/api/media/collect/upload", headers=hdr, data={"album_id": str(s2_album_id)}, files={"file": ("第1集_海上巡逻.wav", wav_bytes, "audio/wav")}).json()
        s2_t2 = client.post("/api/media/collect/upload", headers=hdr, data={"album_id": str(s2_album_id)}, files={"file": ("第2集_冰雪大救援.wav", wav_bytes, "audio/wav")}).json()

        # 2. 保存第2季第1集 42.5 秒的播放位置，验证三级树 resume_info 精准记忆
        pr = client.post(
            f"/api/media/albums/{s2_album_id}/progress",
            headers=hdr,
            json={"track_id": s2_t1["track_id"], "position_sec": 42.5},
        )
        assert pr.status_code == 200

        tree = client.get("/api/media/series?channel=story", headers=hdr).json()
        paw = next((x for x in tree if x["id"] == series_id), None)
        assert paw is not None
        assert paw["season_count"] == 2
        assert paw["total_tracks"] == 4
        assert paw["resume_info"] is not None
        assert paw["resume_info"]["season_num"] == 2
        assert paw["resume_info"]["episode_num"] == 1
        assert abs(paw["resume_info"]["position_sec"] - 42.5) < 0.1

        # 3. 语音喊「播放汪汪队」-> 自动从记忆的 第2季第1集 42.5 秒续播
        v_resume = client.post("/api/interact", headers=hdr, json={"text": "播放汪汪队"}).json()
        assert v_resume["play_track"] is not None
        assert v_resume["play_track"]["id"] == s2_t1["track_id"]
        assert abs(v_resume["play_track"]["start_position_sec"] - 42.5) < 0.1
        assert "第2季" in v_resume["reply_text"]

        # 4. 语音喊「播放汪汪队第一季第二集」-> 中文数字跳季跳集精准命中第1季第2集
        v_jump_season = client.post("/api/interact", headers=hdr, json={"text": "播放汪汪队第一季第二集"}).json()
        assert v_jump_season["play_track"] is not None
        assert v_jump_season["play_track"]["id"] == s1_t2["track_id"]
        assert v_jump_season["play_track"]["season_num"] == 1
        assert v_jump_season["play_track"]["episode_num"] == 2

        # 5. 绑定模拟音箱并通过 WebSocket 验证：会话内「跳到第1集」+ 播完第1季最后一集自动跨季连播第2季第1集
        dev = client.post(
            "/api/devices",
            headers=hdr,
            json={"name": "儿童房测试音箱", "device_type": "speaker_xiaoai", "room": "儿童房", "max_volume": 75, "wake_word": "你好小音"},
        ).json()
        dev_id = dev["id"]
        dev_token = dev["auth_token"]

        # 准备受控的模拟在线搜索与下载器，确保音箱语音采集全链路 100% 确定性（不依赖外网）
        async def _fake_search(q: str, limit: int = 5):
            return [
                {"title": "小猪佩奇 第1集 泥坑历险", "duration_sec": 60.0, "uploader": "test", "url": "https://mock.local/peppa/1"},
                {"title": "小猪佩奇 第2集 恐龙玩具", "duration_sec": 65.0, "uploader": "test", "url": "https://mock.local/peppa/2"},
            ][:limit]

        async def _fake_download(url: str, album_id: int, title_hint: str = ""):
            tmp = Path("/tmp") / f"test_peppa_{int(time.time() * 100000)}.wav"
            tmp.write_bytes(wav_bytes)
            try:
                ep = ai_curator.extract_episode_number_from_title(title_hint)
                return await insert_normalized_track(album_id=album_id, title=title_hint, raw_file=tmp, source_url=url, episode_num=ep)
            finally:
                tmp.unlink(missing_ok=True)

        monkeypatch.delenv("ECHOMIND_DISABLE_ONLINE_SEARCH", raising=False)
        monkeypatch.setattr(ai_curator, "search_online_audio", _fake_search)
        monkeypatch.setattr(ai_curator, "_download_ytdlp_single_item", _fake_download)

        with client.websocket_connect(f"/ws/speaker?device_id={dev_id}&token={dev_token}") as ws:
            # 推第1季第2集（本季最后一集）到音箱
            push_r = client.post(
                "/api/playback/push",
                headers=hdr,
                json={"device_ids": [dev_id], "album_id": s1_album_id, "start_index": 1, "resume": False},
            )
            assert push_r.status_code == 200
            m1 = ws.receive_json()
            assert m1["type"] == "play_url"
            assert "阿奇立功" in m1["title"]

            # 音箱语音说「跳到第1集」-> 当前队列内精准跳到第1集
            ws.send_json({"type": "chat", "text": "跳到第1集"})
            got_jump_play = False
            got_jump_reply = False
            for _ in range(4):
                pkt = ws.receive_json()
                if pkt["type"] == "play_url" and "救援出发" in pkt["title"]:
                    got_jump_play = True
                if pkt["type"] == "reply" and "第 1 集" in pkt["reply_text"]:
                    got_jump_reply = True
                if got_jump_play and got_jump_reply:
                    break
            assert got_jump_play and got_jump_reply

            # 切到第1季第2集（本季末尾）后上报 track_ended -> 自动跨季连播第2季第1集！
            assert client.post(f"/api/playback/rooms/{dev_id}/control", headers=hdr, json={"action": "jump", "index": 1}).status_code == 200
            _ = ws.receive_json()
            ws.send_json({"type": "track_ended"})
            m_cross = ws.receive_json()
            assert m_cross["type"] == "play_url"
            assert "海上巡逻" in m_cross["title"]

            rooms = client.get("/api/playback/rooms", headers=hdr).json()
            cur_room = next((r for r in rooms if r["id"] == dev_id), None)
            assert cur_room is not None and cur_room["session"]["season_num"] == 2
            assert cur_room["session"]["album_id"] == s2_album_id

            # 6. 音箱语音采集：「帮我采集小猪佩奇第二季的故事」-> 立即回复确认 -> AI自动分类入库 -> 音箱收到播报通知！
            ws.send_json({"type": "chat", "text": "帮我采集小猪佩奇第二季的故事"})
            ack_pkt = ws.receive_json()
            assert ack_pkt["type"] == "reply"
            assert ack_pkt["background_job"] is not None
            assert "采集" in ack_pkt["reply_text"]

            # 等待后台任务完成并收到音箱主动播报消息 type=="play"
            announce_pkt = None
            for _ in range(15):
                pkt = ws.receive_json()
                if pkt.get("type") == "play" and "小猪佩奇" in pkt.get("text", ""):
                    announce_pkt = pkt
                    break
            assert announce_pkt is not None
            assert announce_pkt.get("tts_url", "").startswith("/api/tts-cache/")
            assert "第2季" in announce_pkt["text"]
            assert "2 集" in announce_pkt["text"]

        # 验证小猪佩奇已被 AI 自动分类到「故事书架 → 小猪佩奇 → 第2季」并有序入库 2 集
        story_tree = client.get("/api/media/series?channel=story", headers=hdr).json()
        peppa = next((x for x in story_tree if x["title"] == "小猪佩奇"), None)
        assert peppa is not None
        assert len(peppa["seasons"]) == 1
        assert peppa["seasons"][0]["season_num"] == 2
        assert peppa["seasons"][0]["season_label"] == "第2季"
        assert len(peppa["seasons"][0]["tracks"]) == 2
        assert peppa["seasons"][0]["tracks"][0]["episode_num"] == 1
        assert peppa["seasons"][0]["tracks"][1]["episode_num"] == 2

        # 7. 英语启蒙 L1~L5 分级树、打卡进度与词卡点读验证
        seed_en = client.post("/api/english/courses/seed-builtin", headers=hdr)
        assert seed_en.status_code == 200
        l1_list = client.get("/api/media/series?channel=english&level_code=L1", headers=hdr).json()
        assert len(l1_list) >= 1
        first_l1_track = l1_list[0]["seasons"][0]["tracks"][0]
        assert client.patch(f"/api/media/tracks/{first_l1_track['id']}", headers=hdr, json={"completed": True}).status_code == 200
        l1_after = client.get("/api/media/series?channel=english&level_code=L1", headers=hdr).json()
        assert l1_after[0]["completed_tracks"] >= 1

        pron = client.post("/api/english/pronounce", headers=hdr, json={"text": "Good morning!"})
        assert pron.status_code == 200
        assert pron.json()["tts_url"].startswith("/api/tts-cache/")


def test_xiaoai_cloud_mcp_webdav_multimember_progress_voice_ops_and_storage(monkeypatch):
    """深度全链路验证：真小爱桥接、标准MCP Server、WebDAV三级同步、两级本地目录扫描、多人独立进度、新语音口令、英语打卡跟读与磁盘运维。"""
    import http.server
    import threading
    from app.services import ai_curator
    from app.services.xiaoai_bridge import xiaoai_bridge

    wav_bytes = _make_synthetic_voice_wav(f0_hz=380.0, duration_sec=0.8)

    # 1. 搭建本机轻量模拟 WebDAV 服务器（含 故事系列/第2季/01_探险.wav 两级目录）
    class MockWebDavHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_PROPFIND(self):
            clen = int(self.headers.get("Content-Length") or 0)
            if clen > 0:
                _ = self.rfile.read(clen)
            from urllib.parse import unquote
            p = unquote(self.path).rstrip("/") or "/"
            if p == "/dav":
                xml_doc = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/dav/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat></D:response>
  <D:response><D:href>/dav/%E6%B5%B7%E5%BA%95%E5%B0%8F%E7%BA%B5%E9%98%9F/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat></D:response>
</D:multistatus>"""
            elif p.endswith("海底小纵队"):
                xml_doc = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/dav/%E6%B5%B7%E5%BA%95%E5%B0%8F%E7%BA%B5%E9%98%9F/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat></D:response>
  <D:response><D:href>/dav/%E6%B5%B7%E5%BA%95%E5%B0%8F%E7%BA%B5%E9%98%9F/%E7%AC%AC3%E5%AD%A3/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat></D:response>
</D:multistatus>"""
            else:
                xml_doc = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/dav/%E6%B5%B7%E5%BA%95%E5%B0%8F%E7%BA%B5%E9%98%9F/%E7%AC%AC3%E5%AD%A3/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat></D:response>
  <D:response><D:href>/dav/%E6%B5%B7%E5%BA%95%E5%B0%8F%E7%BA%B5%E9%98%9F/%E7%AC%AC3%E5%AD%A3/%E7%AC%AC2%E9%9B%86_%E6%B7%B1%E6%B5%B7%E6%95%91%E6%8F%B4.wav</D:href><D:propstat><D:prop><D:resourcetype/><D:getcontentlength>10240</D:getcontentlength></D:prop></D:propstat></D:response>
</D:multistatus>"""
            raw = xml_doc.encode("utf-8")
            self.send_response(207)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)

    wd_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockWebDavHandler)
    threading.Thread(target=wd_server.serve_forever, daemon=True).start()
    wd_base = f"http://127.0.0.1:{wd_server.server_address[1]}/dav"

    # 2. 模拟小米 MiNAService 验证真小爱发现/绑定/推送/播报/音量护耳
    mi_calls: list[tuple[str, Any]] = []

    class FakeMiNA:
        async def device_list(self, master=0):
            return [
                {"deviceID": "mi_dev_001", "miotDID": "miot_99", "alias": "客厅小爱Pro", "hardware": "LX06", "mac": "AA:BB:CC", "presence": "online"}
            ]

        async def play_by_music_url(self, deviceId, url, _type=2):
            mi_calls.append(("play_url", (deviceId, url)))
            return {"code": 0}

        async def play_by_url(self, deviceId, url, _type=2):
            mi_calls.append(("play_url", (deviceId, url)))
            return {"code": 0}

        async def text_to_speech(self, deviceId, text):
            mi_calls.append(("tts", (deviceId, text)))
            return {"code": 0}

        async def player_set_volume(self, deviceId, volume):
            mi_calls.append(("volume", (deviceId, volume)))
            return {"code": 0}

        async def player_pause(self, deviceId):
            mi_calls.append(("pause", deviceId))
            return {"code": 0}

        async def player_stop(self, deviceId):
            mi_calls.append(("stop", deviceId))
            return {"code": 0}

    async def _fake_ensure_mina(mi_user=None, mi_pass=None):
        return FakeMiNA()

    monkeypatch.setattr(xiaoai_bridge, "_ensure_mina", _fake_ensure_mina)

    try:
        with TestClient(app) as client:
            hdr = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'boss', 'password': 'pass1234'}).json()['token']}"}

            # A. 故事候选噪声过滤验证
            filtered = ai_curator.filter_and_rank_candidates(
                [
                    {"title": "【汪汪队第2季Reaction】主播反应解说", "url": "https://a/1"},
                    {"title": "汪汪队立大功全集 睡前故事音频", "url": "https://a/2"},
                ],
                "story",
            )
            assert filtered[0]["url"] == "https://a/2"

            # B. 真·小米小爱音箱发现 -> 绑定 -> 推送音频 -> 音量护耳限幅 -> 语音播报
            disc = client.post(
                "/api/devices/xiaoai/discover",
                headers=hdr,
                json={"mi_user": "13800001111", "mi_pass": "secret123", "public_base_url": "http://192.168.1.9:8090"},
            )
            assert disc.status_code == 200
            assert disc.json()["count"] == 1
            mi_dev = disc.json()["devices"][0]

            bound = client.post(
                "/api/devices/xiaoai/bind",
                headers=hdr,
                json={
                    "mi_device_id": mi_dev["mi_device_id"],
                    "miot_did": mi_dev["miot_did"],
                    "name": mi_dev["name"],
                    "hardware": mi_dev["hardware"],
                    "room": "客厅",
                    "max_volume": 65,
                },
            )
            assert bound.status_code == 200
            xiaoai_dev_id = bound.json()["id"]

            # 调音量到 90 -> 被护耳上限夹到 65 并下发真小爱
            assert client.post("/api/interact", headers=hdr, json={"text": "音量调到90", "device_id": xiaoai_dev_id}).status_code == 200
            assert ("volume", ("mi_dev_001", 65)) in mi_calls

            # C. WebDAV 预览 + 挂载 + 递归三级树同步（海底小纵队 -> 第3季 -> 第2集）
            prev_wd = client.post("/api/media/webdav-mounts/preview", headers=hdr, json={"base_url": wd_base, "remote_path": "/"})
            assert prev_wd.status_code == 200, prev_wd.text
            assert prev_wd.json()["count"] == 1

            m_wd = client.post(
                "/api/media/webdav-mounts",
                headers=hdr,
                json={"name": "家庭故事网盘", "base_url": wd_base, "remote_path": "/", "channel": "story"},
            )
            assert m_wd.status_code == 200
            mount_id = m_wd.json()["id"]
            sync_wd = client.post(f"/api/media/webdav-mounts/{mount_id}/sync", headers=hdr)
            assert sync_wd.status_code == 200, sync_wd.text
            assert sync_wd.json()["tracks_added"] == 1

            story_tree = client.get("/api/media/series?channel=story", headers=hdr).json()
            octo = next((s for s in story_tree if s["title"] == "海底小纵队"), None)
            assert octo is not None
            assert octo["seasons"][0]["season_num"] == 3
            assert octo["seasons"][0]["tracks"][0]["episode_num"] == 2

            # D. 本地两级子目录自动三级树扫描（恐龙战队/第2季/第3集_出发.wav）
            with tempfile.TemporaryDirectory(prefix="echomind_tree_scan_") as scan_dir:
                sub = Path(scan_dir) / "恐龙战队" / "第2季"
                sub.mkdir(parents=True, exist_ok=True)
                (sub / "第3集_霸王龙出发.wav").write_bytes(wav_bytes)
                lf = client.post(
                    "/api/media/local-folders",
                    headers=hdr,
                    json={"name": "本地三维故事盘", "folder_path": scan_dir, "media_type": "story", "age_stage": "S6_ALL"},
                )
                assert lf.status_code == 200
                sc = client.post(f"/api/media/local-folders/{lf.json()['id']}/scan", headers=hdr)
                assert sc.status_code == 200
                assert sc.json()["tracks_added"] == 1
            story_tree2 = client.get("/api/media/series?channel=story", headers=hdr).json()
            dino = next((s for s in story_tree2 if s["title"] == "恐龙战队"), None)
            assert dino is not None
            assert dino["seasons"][0]["season_num"] == 2
            assert dino["seasons"][0]["tracks"][0]["episode_num"] == 3

            # E. 多人独立播放进度隔离（大宝 vs 二宝对《汪汪队》互不覆盖）
            paw = next((s for s in story_tree2 if s["title"] == "汪汪队"), None)
            assert paw is not None
            s1_alb, s2_alb = paw["seasons"][0], paw["seasons"][1]
            assert client.post(
                f"/api/media/albums/{s1_alb['id']}/progress",
                headers=hdr,
                json={"track_id": s1_alb["tracks"][0]["id"], "position_sec": 18.5, "member_key": "member:101"},
            ).status_code == 200
            assert client.post(
                f"/api/media/albums/{s2_alb['id']}/progress",
                headers=hdr,
                json={"track_id": s2_alb["tracks"][1]["id"], "position_sec": 55.0, "member_key": "member:102"},
            ).status_code == 200

            t101 = next(s for s in client.get("/api/media/series?channel=story&member_key=member:101", headers=hdr).json() if s["title"] == "汪汪队")
            t102 = next(s for s in client.get("/api/media/series?channel=story&member_key=member:102", headers=hdr).json() if s["title"] == "汪汪队")
            assert t101["resume_info"]["season_num"] == 1 and abs(t101["resume_info"]["position_sec"] - 18.5) < 0.1
            assert t102["resume_info"]["season_num"] == 2 and abs(t102["resume_info"]["position_sec"] - 55.0) < 0.1

            # F. 新增高频语音口令（汪汪队有几季 / 重播 / 快进30秒 / 单曲循环 / 现在放的是什么）+ 推送到真小爱验证
            q_info = client.post("/api/interact", headers=hdr, json={"text": "汪汪队有几季"}).json()
            assert "2 季" in q_info["reply_text"] and "4 集" in q_info["reply_text"]

            push_mi = client.post(
                "/api/playback/push",
                headers=hdr,
                json={"device_ids": [xiaoai_dev_id], "series_id": paw["id"], "resume": True},
            )
            assert push_mi.status_code == 200
            assert any(op == "play_url" and payload[0] == "mi_dev_001" for op, payload in mi_calls)

            r_what = client.post("/api/interact", headers=hdr, json={"text": "现在放的是什么", "device_id": xiaoai_dev_id}).json()
            assert "汪汪队" in r_what["reply_text"]
            r_seek = client.post("/api/interact", headers=hdr, json={"text": "快进30秒", "device_id": xiaoai_dev_id}).json()
            assert r_seek["control_action"]["action"] == "seek_delta" and r_seek["control_action"]["delta_sec"] == 30
            r_rep = client.post("/api/interact", headers=hdr, json={"text": "重播这集", "device_id": xiaoai_dev_id}).json()
            assert r_rep["control_action"]["action"] == "replay"
            r_loop = client.post("/api/interact", headers=hdr, json={"text": "单曲循环", "device_id": xiaoai_dev_id}).json()
            assert r_loop["control_action"]["loop_mode"] == "repeat_one"

            # G. 标准 MCP Server JSON-RPC 2.0 端到端验证（供 xiaozhi-esp32-server 接入）
            mcp_list = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            assert mcp_list.status_code == 200
            tool_names = [t["name"] for t in mcp_list.json()["result"]["tools"]]
            assert "echomind_play_series" in tool_names and "echomind_collect_and_classify" in tool_names

            mcp_call = client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "echomind_list_library", "arguments": {"channel": "story"}}},
            )
            assert mcp_call.status_code == 200
            assert mcp_call.json()["result"]["structuredContent"]["count"] >= 3

            # H. 英语启蒙 7 天打卡日历与跟读录音打星
            chk = client.post("/api/english/checkin", headers=hdr, json={"duration_min": 8.0, "spoken_score": 5, "member_key": "member:101"})
            assert chk.status_code == 200
            assert chk.json()["streak_days"] >= 1 and chk.json()["today_checked"] is True
            assert len(chk.json()["last_7_days"]) == 7

            ev = client.post(
                "/api/english/evaluate-speech",
                headers=hdr,
                data={"expected_text": "Good morning!", "member_key": "member:101"},
                files={"file": ("read.wav", wav_bytes, "audio/wav")},
            )
            assert ev.status_code == 200
            assert ev.json()["stars"] >= 4

            # I. 服务器磁盘空间运维监控与缓存清理
            st_r = client.get("/api/media/storage", headers=hdr)
            assert st_r.status_code == 200
            st_data = st_r.json()
            assert st_data["disk_total_gb"] > 0 and len(st_data["series_usage"]) >= 3

            cln = client.post("/api/media/storage/clean-cache", headers=hdr)
            assert cln.status_code == 200 and cln.json()["status"] == "cleaned"
    finally:
        wd_server.shutdown()
        wd_server.server_close()




