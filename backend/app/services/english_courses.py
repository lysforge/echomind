"""全阶英语系列课程（Pre-A1 -> B2+）内置教研课包、主题定制生成与护耳音频合成服务。"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import DATA_DIR, MEDIA_RAW_DIR, load_settings
from app.db import get_db, now_iso
from app.services.audio_norm import normalize_audio_to_lufs
from app.services.tts_asr import synthesize_speech

ENGLISH_LESSONS_DIR = DATA_DIR / "books" / "english_lessons"

STAGE_TO_AGE = {
    "Pre_A1": "S1_0_3",
    "A1": "S2_3_6",
    "A2": "S3_6_9",
    "B1": "S4_9_12",
    "B2_PLUS": "S5_12_18",
}

BUILTIN_ENGLISH_COURSES: list[dict[str, Any]] = [
    {
        "title": "Pre-A1 · 小耳朵韵律生活启蒙",
        "subtitle": "零基础磨耳朵 · 日常生活场景 4 课",
        "stage": "Pre_A1",
        "age_stage": "S1_0_3",
        "theme": "daily",
        "cover_emoji": "🧸",
        "description": "专为 0-3 岁零基础宝宝设计：不讲语法，通过温暖双语拟声词与生活高频词建立英文声音熟悉感。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 早上起床问候（Good Morning）",
                "objective": "熟悉晨起阳光和微笑问候的自然英文韵律。",
                "vocab": [
                    {"en": "Good morning", "zh": "早上好", "example": "Good morning, sunshine!"},
                    {"en": "Sun", "zh": "太阳公公", "example": "Look, the warm yellow sun."},
                    {"en": "Smile", "zh": "微笑", "example": "Give mama a big smile!"},
                ],
                "dialogue_script": "早安宝贝！太阳公公起来啦，Sun, sun! 我们用甜甜的声音说：Good morning! 早上好！Smile, smile, 给爸爸妈妈一个大大的微笑吧！Good morning!",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · 香甜水果点心（Yummy Fruits）",
                "objective": "在吃水果场景中感知 Apple / Banana / Milk 声音映射。",
                "vocab": [
                    {"en": "Apple", "zh": "苹果", "example": "Red apple, crunch, crunch!"},
                    {"en": "Banana", "zh": "香蕉", "example": "Yellow banana, yummy!"},
                    {"en": "Milk", "zh": "牛奶", "example": "Drink warm milk."},
                ],
                "dialogue_script": "点心时间到啦！红彤彤的大苹果 Apple! 咔嚓咬一口，Crunch crunch! 弯弯的小月亮是香蕉 Banana! 喝一口香香的牛奶 Milk, yummy!",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 农场小动物唱歌（Animal Sounds）",
                "objective": "用趣味拟声词建立对小鸭、小猫、小狗英文词的条件反射。",
                "vocab": [
                    {"en": "Duck", "zh": "小鸭子", "example": "Duck says quack, quack!"},
                    {"en": "Cat", "zh": "小猫咪", "example": "Little cat says meow."},
                    {"en": "Dog", "zh": "小狗狗", "example": "Happy dog says woof, woof!"},
                ],
                "dialogue_script": "听，小鸭子走过来啦！Duck, duck! Quack quack quack! 小猫咪咪叫：Cat, cat, meow! 还有摇尾巴的小狗 Dog, woof woof!",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 晚安月亮睡前曲（Bedtime）",
                "objective": "轻柔收尾进入睡眠仪式，熟悉 Moon / Star / Night。",
                "vocab": [
                    {"en": "Moon", "zh": "月亮", "example": "Goodnight, little moon."},
                    {"en": "Star", "zh": "小星星", "example": "Twinkle, twinkle, little star."},
                    {"en": "Goodnight", "zh": "晚安", "example": "Goodnight, sweet dreams!"},
                ],
                "dialogue_script": "天黑啦，月亮船出来咯，Moon, moon. 小星星一闪一闪，Star, star. 闭上小眼睛，我们轻轻地说：Goodnight! 晚安，好梦。",
            },
        ],
    },
    {
        "title": "Pre-A1 · 缤纷色彩与快乐律动",
        "subtitle": "零基础磨耳朵 · 颜色数字身体动作 4 课",
        "stage": "Pre_A1",
        "age_stage": "S1_0_3",
        "theme": "rhythm",
        "cover_emoji": "🌈",
        "description": "配合拍手、转圈、看绘本时的色彩与数字韵律输入，培养英语听觉敏感期节奏感。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 彩虹的三原色（Red, Blue, Yellow）",
                "objective": "建立红、蓝、黄三原色的直观英文听辨。",
                "vocab": [
                    {"en": "Red", "zh": "红色", "example": "Red like a strawberry."},
                    {"en": "Blue", "zh": "蓝色", "example": "Blue like the sky."},
                    {"en": "Yellow", "zh": "黄色", "example": "Yellow like a little duck."},
                ],
                "dialogue_script": "看天上的大彩虹！Red, 红色的小草莓；Blue, 蓝蓝的大海和天空；Yellow, 黄澄澄的小鸭子！Red, blue, yellow!",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · 拍拍小手摇摇头（Clap Hands）",
                "objective": "在全身小动作中听懂简单指令词。",
                "vocab": [
                    {"en": "Clap", "zh": "拍拍手", "example": "Clap your hands!"},
                    {"en": "Jump", "zh": "跳一跳", "example": "Jump up high!"},
                    {"en": "Hug", "zh": "抱一抱", "example": "Give a warm hug!"},
                ],
                "dialogue_script": "音乐响起来咯！跟着小音一起拍拍手：Clap, clap, clap! 像小兔子一样跳一跳：Jump, jump! 最后给爸爸妈妈一个大拥抱：Hug!",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 手指头数一数（One Two Three）",
                "objective": "用节奏感数出 One, Two, Three, Four, Five。",
                "vocab": [
                    {"en": "One", "zh": "一", "example": "One little finger."},
                    {"en": "Two", "zh": "二", "example": "Two bright eyes."},
                    {"en": "Three", "zh": "三", "example": "One, two, three, go!"},
                ],
                "dialogue_script": "伸出小手指跟我数！One, 一根手指点一点；Two, 两只亮亮的小眼睛；One, two, three, four, five! 太棒啦！",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 晴天与小雨点（Sunny & Rainy）",
                "objective": "把每天窗外的天气和英文拟声联系起来。",
                "vocab": [
                    {"en": "Sunny", "zh": "晴天", "example": "Today is a sunny day!"},
                    {"en": "Rainy", "zh": "下雨天", "example": "Pitter-patter, rainy day!"},
                    {"en": "Wind", "zh": "风", "example": "Whoosh goes the wind!"},
                ],
                "dialogue_script": "看看窗外是什么天气呀？太阳公公笑眯眯：Sunny, sunny! 小雨点滴答滴答：Rainy, pitter-patter! 小风呼呼吹：Whoosh, wind!",
            },
        ],
    },
    {
        "title": "A1 · 幼儿日常高频口语 100 句入门",
        "subtitle": "3-6岁 · 生活习惯、礼貌用语与情绪表达 4 课",
        "stage": "A1",
        "age_stage": "S2_3_6",
        "theme": "daily",
        "cover_emoji": "🦷",
        "description": "结合 3-6 岁幼儿园与居家核心场景，短句跟读 + 音频鼓励问答，帮孩子自然开口说整句。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 刷牙洗脸好习惯（Brush Teeth）",
                "objective": "掌握起床洗漱高频动作短句，鼓励跟读。",
                "vocab": [
                    {"en": "Time to brush teeth", "zh": "该刷牙啦", "example": "Time to brush teeth, up and down!"},
                    {"en": "Wash my face", "zh": "洗洗脸", "example": "I wash my face every morning."},
                    {"en": "Clean", "zh": "干净的", "example": "Now my teeth are shiny and clean!"},
                ],
                "dialogue_script": "Morning, little buddy! 早安好习惯小卫士！先来跟读一句：Time to brush teeth! 该刷牙啦！上刷刷、下刷刷，再说一句：I wash my face! 看，牙齿亮晶晶 Clean! 你也大声跟读试试看？",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · 礼貌魔法小词（Please & Thank You）",
                "objective": "在请求与接过礼物时习惯用英文表达礼貌。",
                "vocab": [
                    {"en": "Please", "zh": "请", "example": "Water, please!"},
                    {"en": "Thank you", "zh": "谢谢你", "example": "Thank you very much!"},
                    {"en": "You are welcome", "zh": "不客气", "example": "You are welcome!"},
                ],
                "dialogue_script": "今天学两个超级魔法词！想要小水杯怎么说？Water, please! 拿到东西要笑着说：Thank you! 当别人谢谢你时，大声回答：You are welcome!",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 穿衣出门去探险（Let's Go Outside）",
                "objective": "学会穿鞋、戴帽与出发的常用口语短句。",
                "vocab": [
                    {"en": "Put on your shoes", "zh": "穿上鞋子", "example": "Put on your shoes, let's go!"},
                    {"en": "Let's explore nature", "zh": "去探索大自然吧", "example": "Put on your hat, let's explore nature!"},
                    {"en": "Ready to go", "zh": "准备好出发啦", "example": "I am ready to go!"},
                ],
                "dialogue_script": "我们要出门去公园玩咯！Put on your shoes, 穿上小鞋子！准备好了吗？大声告诉妈妈：I am ready! Let's explore nature!",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 说出我的小情绪（Happy & Brave）",
                "objective": "用英文简单表达开心、害羞、生气与勇敢。",
                "vocab": [
                    {"en": "I am happy", "zh": "我很开心", "example": "I am happy today!"},
                    {"en": "I feel sleepy", "zh": "我觉得有点困了", "example": "I feel sleepy at night."},
                    {"en": "I am brave", "zh": "我很勇敢", "example": "Take a deep breath, I am brave!"},
                ],
                "dialogue_script": "小音问问你：How do you feel today? 今天心情怎么样？如果很开心就说：I am happy! 如果遇到困难需要勇气，跟我拍拍胸口说：I am brave!",
            },
        ],
    },
    {
        "title": "A2 · 神奇大自然双语科普课",
        "subtitle": "6-9岁 · 桥梁阅读与科学小问号 4 课",
        "stage": "A2",
        "age_stage": "S3_6_9",
        "theme": "nature",
        "cover_emoji": "🌍",
        "description": "面向小学低中年级：用清晰易懂的双语科普句型解释彩虹、四季、海洋与太阳系，并带思考提问。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 彩虹是怎么形成的？（Rainbow Science）",
                "objective": "用 A2 英语短段落理解阳光与雨滴折射成彩虹的原理。",
                "vocab": [
                    {"en": "Sunlight", "zh": "阳光", "example": "Sunlight travels through raindrops."},
                    {"en": "Raindrop", "zh": "小雨滴", "example": "Millions of tiny raindrops act like prisms."},
                    {"en": "What caused the rainbow?", "zh": "彩虹是怎么形成的？", "example": "Sunlight and raindrops make a rainbow!"},
                ],
                "dialogue_script": "Welcome to Nature Science! 今天的科普小问题是：What caused the rainbow? 当雨后的阳光 Sunlight 穿过空中微小的雨滴 Raindrops，白色的阳光就会折射出七种绚丽的色彩！下一次雨后天晴，记得抬头数一数红橙黄绿青蓝紫哦！",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · 四季流转的秘密（Four Seasons）",
                "objective": "掌握 Spring / Summer / Autumn / Winter 特征描述。",
                "vocab": [
                    {"en": "Spring & Blossom", "zh": "春天与花开", "example": "Flowers blossom in spring."},
                    {"en": "Autumn leaves", "zh": "秋天的落叶", "example": "Leaves turn gold and red in autumn."},
                    {"en": "Winter snow", "zh": "冬天的白雪", "example": "Snow covers the quiet mountains in winter."},
                ],
                "dialogue_script": "地球围绕太阳公转，给我们带来了美丽的四季：Spring, flowers blossom; Summer, bright sunshine and ice cream; Autumn, leaves turn golden; Winter, snowy days! Which season is your favorite?",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 神秘的海洋居民（Ocean Friends）",
                "objective": "了解鲸鱼、海豚和珊瑚礁的环保英语词汇。",
                "vocab": [
                    {"en": "Whale", "zh": "鲸鱼", "example": "The blue whale is the largest animal on Earth."},
                    {"en": "Dolphin", "zh": "海豚", "example": "Smart dolphins communicate with clicks and whistles."},
                    {"en": "Protect the ocean", "zh": "保护海洋", "example": "We should reduce plastic to protect the ocean."},
                ],
                "dialogue_script": "潜入蔚蓝深海吧！蓝鲸 Blue whale 是地球上最大的动物；聪明的小海豚 Dolphin 会用声音哨音彼此聊天！请记住我们的小口号：Let's protect the ocean!",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 太阳系太空漫游（Solar System）",
                "objective": "认识太阳、地球与木星的英文行星名字。",
                "vocab": [
                    {"en": "Planet", "zh": "行星", "example": "Earth is our blue planet."},
                    {"en": "Orbit", "zh": "围绕运行", "example": "Eight planets orbit around the Sun."},
                    {"en": "Gravity", "zh": "引力", "example": "Gravity keeps the Moon moving around Earth."},
                ],
                "dialogue_script": "准备发射小火箭！Eight planets orbit around the Sun. 我们的蓝色家园是 Earth 地球，地球周围绕着月亮，全靠神奇的引力 Gravity！What planet would you like to visit first?",
            },
        ],
    },
    {
        "title": "B1 · 少年独立听说与故事表达",
        "subtitle": "9-12岁 · 全英听力进阶、摘要复述与实用对话 4 课",
        "stage": "B1",
        "age_stage": "S4_9_12",
        "theme": "dialogue",
        "cover_emoji": "🧭",
        "description": "面向小学高年级：训练听懂完整英文小段落，并学会用 Beginning - Challenge - Solution 三步法组织英文表达。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 如何概括一个故事（Story Summary）",
                "objective": "掌握用起因、挑战与结局概括故事的核心逻辑句式。",
                "vocab": [
                    {"en": "Could you summarize the story?", "zh": "你能概括一下这个故事吗？", "example": "In the beginning, a young traveler got lost."},
                    {"en": "Challenge", "zh": "挑战与困难", "example": "The main challenge was crossing the foggy river."},
                    {"en": "Solution", "zh": "解决办法", "example": "Finally, teamwork led them to a smart solution."},
                ],
                "dialogue_script": "Hey there! Today we practice storytelling skills at B1 level. Whenever someone asks: Could you summarize the story? Try three easy steps: First, the beginning; second, the main challenge; and finally, how the hero found a solution. Try summarizing your favorite book out loud!",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · 像科学家一样提问（Scientific Method）",
                "objective": "学习观察、假设与实验验证的英文科普核心表达。",
                "vocab": [
                    {"en": "Observe", "zh": "观察", "example": "Carefully observe what happens when ice melts."},
                    {"en": "Hypothesis", "zh": "猜想 / 假设", "example": "Form a hypothesis before starting the experiment."},
                    {"en": "Evidence", "zh": "证据", "example": "Good scientists always check the evidence."},
                ],
                "dialogue_script": "Let's think like a scientist! First, observe the world carefully. Then form a hypothesis—a smart guess about why it happens. Test it, collect evidence, and share your conclusion!",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 图书馆与博物馆探索（Asking Politely）",
                "objective": "能在公共场馆流利使用礼貌英文询问与求助。",
                "vocab": [
                    {"en": "Excuse me, could you tell me...", "zh": "打扰一下，请问……", "example": "Excuse me, could you tell me where the science books are?"},
                    {"en": "Recommend", "zh": "推荐", "example": "Could you recommend an adventure novel?"},
                    {"en": "Borrow", "zh": "借阅", "example": "I would like to borrow this book for two weeks."},
                ],
                "dialogue_script": "Imagine you are visiting an international library! You can politely say: Excuse me, could you recommend a great science book? And at the counter: I would like to borrow this copy. Polite English opens every door!",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 描述一次难忘经历（Past Experiences）",
                "objective": "练习用一般过去时讲述周末见闻或旅行故事。",
                "vocab": [
                    {"en": "Unforgettable", "zh": "难忘的", "example": "Camping under the stars was unforgettable."},
                    {"en": "First... Then... Finally...", "zh": "首先……接着……最后……", "example": "First we set up the tent, then we cooked dinner."},
                    {"en": "I learned that...", "zh": "我学到了……", "example": "I learned that patience really matters."},
                ],
                "dialogue_script": "Think about an unforgettable day in your life. Use time connectors: First, what did you do? Then, what surprised you? Finally, what did you learn from that moment? Pause after this track and tell me your story!",
            },
        ],
    },
    {
        "title": "B2+ · 青少年原版思辨与演讲力",
        "subtitle": "12-18岁 · 全英深度思考、观点论证与批判性思维 4 课",
        "stage": "B2_PLUS",
        "age_stage": "S5_12_18",
        "theme": "science",
        "cover_emoji": "🎙️",
        "description": "面向初高中青少年：全英文沉浸讨论科技伦理、环境保护、跨文化沟通与结构化英文演讲技巧。",
        "lessons": [
            {
                "lesson_num": 1,
                "title": "Lesson 1 · 好奇心与科学突破（Curiosity & Innovation）",
                "objective": "围绕科学精神进行深度英文思辨与论点展开。",
                "vocab": [
                    {"en": "How does curiosity drive science?", "zh": "好奇心如何推动科学发展？", "example": "Every major breakthrough began with someone asking why."},
                    {"en": "Breakthrough", "zh": "重大突破", "example": "Penicillin was an accidental yet brilliant breakthrough."},
                    {"en": "Perspective", "zh": "视角 / 观点", "example": "Challenging old assumptions gives us a fresh perspective."},
                ],
                "dialogue_script": "Welcome to B2+ Critical Thinking Studio. Let's reflect on this question: How does curiosity drive science? Every major scientific breakthrough began with someone refusing to take the obvious for granted. What mystery in technology or nature fascinates you most right now?",
            },
            {
                "lesson_num": 2,
                "title": "Lesson 2 · AI 与人类创造力（AI & Human Creativity）",
                "objective": "辩证探讨人工智能时代的独立思考能力。",
                "vocab": [
                    {"en": "Augment", "zh": "增强 / 辅助", "example": "AI works best when it augments human judgment."},
                    {"en": "Critical thinking", "zh": "批判性思维", "example": "Critical thinking helps us verify information."},
                    {"en": "Empathy", "zh": "同理心", "example": "True storytelling requires human empathy and lived experience."},
                ],
                "dialogue_script": "In an era where AI writes essays and music, what makes human voices irreplaceable? Tools can calculate fast, yet critical thinking, ethical responsibility, and genuine empathy remain uniquely human. How should students use AI wisely without outsourcing their own thinking?",
            },
            {
                "lesson_num": 3,
                "title": "Lesson 3 · 地球可持续发展（Sustainable Future）",
                "objective": "流利使用新能源与低碳转型高频高阶词汇。",
                "vocab": [
                    {"en": "Sustainability", "zh": "可持续发展", "example": "Urban sustainability balances growth with ecology."},
                    {"en": "Renewable energy", "zh": "可再生能源", "example": "Solar and wind are pillars of renewable energy."},
                    {"en": "Trade-off", "zh": "权衡取舍", "example": "Every policy involves economic and environmental trade-offs."},
                ],
                "dialogue_script": "Sustainability is not just about recycling; it is about rethinking energy, cities, and daily habits. Notice the word trade-off: when balancing convenience and ecological impact, what small personal habit can create ripple effects in your community?",
            },
            {
                "lesson_num": 4,
                "title": "Lesson 4 · 高效英文观点表达（Structured Argument）",
                "objective": "运用 PEEL（Point-Evidence-Explanation-Link）模型进行 1 分钟英文微演讲。",
                "vocab": [
                    {"en": "From my perspective", "zh": "从我的角度来看", "example": "From my perspective, reading deeply builds focus."},
                    {"en": "For instance", "zh": "举例而言", "example": "For instance, long-form audiobooks train listening stamina."},
                    {"en": "Ultimately", "zh": "归根结底", "example": "Ultimately, consistent practice shapes fluency."},
                ],
                "dialogue_script": "Want to sound convincing in English debates or interviews? Use the PEEL framework: State your Point clearly, support it with Evidence—say, For instance...—give an Explanation, and Link it back. Try delivering a sixty-second mini speech on a topic you care about!",
            },
        ],
    },
]


_COURSE_STAGE_TAG = {
    "Pre_A1": "零基础韵律",
    "A1": "日常口语课",
    "A2": "自然科普课",
    "B1": "故事与思辨",
    "B2_PLUS": "故事与思辨",
}


async def _sync_course_to_album(conn: Any, course_id: int) -> None:
    """将新建/导入的英语系列课程同步至统一 media_albums / media_tracks，保持前台一致。"""
    ts = now_iso()
    cur = await conn.execute("SELECT * FROM english_courses WHERE id = ?", (course_id,))
    c = await cur.fetchone()
    if not c:
        return
    sub_tag = _COURSE_STAGE_TAG.get(c["stage"], "日常口语课")
    emoji = c["cover_emoji"] or "🎓"

    cur_a = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (c["title"],))
    arow = await cur_a.fetchone()
    if arow:
        aid = int(arow["id"])
    else:
        cur_ins = await conn.execute(
            """
            INSERT INTO media_albums
            (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, author, language, description, created_at)
            VALUES (?, 'english', ?, ?, ?, 'sequential', ?, 'EchoMind 英语教研', 'bilingual', ?, ?)
            """,
            (c["title"], sub_tag, c["age_stage"], c["stage"], emoji, c["description"] or c["subtitle"] or "", c["created_at"] or ts),
        )
        aid = int(cur_ins.lastrowid)

    cur_ls = await conn.execute("SELECT * FROM english_lessons WHERE course_id = ? ORDER BY lesson_num ASC, id ASC", (course_id,))
    for ls in await cur_ls.fetchall():
        guid = f"eng_lesson:{ls['id']}"
        cur_t = await conn.execute("SELECT id FROM media_tracks WHERE external_guid = ?", (guid,))
        if not await cur_t.fetchone():
            cur_ti = await conn.execute(
                """
                INSERT INTO media_tracks
                (album_id, external_guid, title, episode_num, duration_sec, file_path, source_url, text_content, vocab_json, objective, completed, lufs_normalized, play_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    aid,
                    guid,
                    ls["title"],
                    ls["lesson_num"],
                    ls["duration_sec"],
                    ls["audio_path"] or "",
                    guid,
                    ls["dialogue_script"] or "",
                    ls["vocab_json"] or "[]",
                    ls["objective"] or "",
                    ls["completed"],
                    ls["listen_count"],
                    ls["created_at"] or ts,
                ),
            )
            await conn.execute(
                "UPDATE media_albums SET last_track_id = COALESCE(last_track_id, ?) WHERE id = ?",
                (cur_ti.lastrowid, aid),
            )


async def seed_builtin_english_courses() -> dict[str, int]:
    """幂等导入覆盖 Pre_A1 -> B2_PLUS 的 6 套精品英语系列课，并同步核心词句入库。"""
    ts = now_iso()
    courses_added = 0
    lessons_added = 0
    vocab_added = 0

    async with get_db() as conn:
        for c in BUILTIN_ENGLISH_COURSES:
            cur = await conn.execute("SELECT id FROM english_courses WHERE title = ?", (c["title"],))
            row = await cur.fetchone()
            if row:
                course_id = int(row["id"])
            else:
                cur_ins = await conn.execute(
                    """
                    INSERT INTO english_courses (title, subtitle, stage, age_stage, theme, cover_emoji, description, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c["title"],
                        c["subtitle"],
                        c["stage"],
                        c["age_stage"],
                        c["theme"],
                        c["cover_emoji"],
                        c["description"],
                        ts,
                    ),
                )
                course_id = int(cur_ins.lastrowid)
                courses_added += 1

            for lesson in c["lessons"]:
                cur_l = await conn.execute(
                    "SELECT id FROM english_lessons WHERE course_id = ? AND lesson_num = ?",
                    (course_id, lesson["lesson_num"]),
                )
                if not await cur_l.fetchone():
                    await conn.execute(
                        """
                        INSERT INTO english_lessons
                        (course_id, lesson_num, title, objective, vocab_json, dialogue_script, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            course_id,
                            lesson["lesson_num"],
                            lesson["title"],
                            lesson["objective"],
                            json.dumps(lesson["vocab"], ensure_ascii=False),
                            lesson["dialogue_script"],
                            ts,
                        ),
                    )
                    lessons_added += 1

                # 将本课重点词条幂等写入 english_items，供 AI 语音日常练习联动
                for v in lesson["vocab"]:
                    cur_v = await conn.execute("SELECT id FROM english_items WHERE phrase = ?", (v["en"],))
                    if not await cur_v.fetchone():
                        cat = c["theme"] if c["theme"] in ("daily", "animal", "nature", "science", "dialogue") else "daily"
                        await conn.execute(
                            """
                            INSERT INTO english_items (phrase, zh_meaning, stage, category, audio_prompt, listen_count, mastery_level)
                            VALUES (?, ?, ?, ?, ?, 0, 0)
                            """,
                            (v["en"], v["zh"], c["stage"], cat, v["example"]),
                        )
                        vocab_added += 1

        for cid_row in await (await conn.execute("SELECT id FROM english_courses")).fetchall():
            await _sync_course_to_album(conn, int(cid_row["id"]))

        await conn.commit()

    return {
        "courses_added": courses_added,
        "lessons_added": lessons_added,
        "vocab_added": vocab_added,
    }


async def _llm_generate_course_spec(topic: str, stage: str) -> dict[str, Any] | None:
    """若配置了外部大模型 Key，调用 LLM 按兴趣主题生成 4 节系列课 JSON。"""
    settings = load_settings()
    if not (settings.llm_api_key.strip() or settings.llm_provider == "ollama"):
        return None
    prompt = (
        f"你是一位专业少儿与青少年英语教研专家。请围绕主题「{topic}」为英语水平【{stage}】的学习者设计一套共 4 节的听力伴学系列课。"
        "严格输出如下 JSON（不要包含 Markdown 代码块围栏）：\n"
        '{"title":"课程标题","subtitle":"副标题","cover_emoji":"一个合适Emoji","description":"一句话简介",'
        '"lessons":[{"lesson_num":1,"title":"Lesson 1 ...","objective":"本课目标",'
        '"vocab":[{"en":"词句1","zh":"中文","example":"英文例句"}],'
        '"dialogue_script":"适合智能音箱无屏朗读的 80-120 字伴学讲稿（含自然慢速带读与提问）"}]}'
    )
    try:
        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key.strip():
            headers["Authorization"] = f"Bearer {settings.llm_api_key.strip()}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                url,
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1600,
                },
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("lessons"):
                return data
    except Exception:
        return None
    return None


def _template_generate_course_spec(topic: str, stage: str) -> dict[str, Any]:
    """当未配置大模型或超时时，按主题与阶段高质量模板生成 4 节完整伴学课程。"""
    if stage in ("B1", "B2_PLUS"):
        lessons = [
            {
                "lesson_num": 1,
                "title": f"Lesson 1 · Exploring {topic}（概念导入与背景）",
                "objective": f"建立围绕「{topic}」的英文核心表达与话题兴趣。",
                "vocab": [
                    {"en": "Fascinating", "zh": "极有吸引力的", "example": f"{topic} is a truly fascinating subject."},
                    {"en": "Discover", "zh": "发现 / 探索", "example": f"Let's discover the secrets behind {topic}."},
                    {"en": "Key feature", "zh": "关键特征", "example": "Notice the key feature carefully."},
                ],
                "dialogue_script": f"Welcome to our custom English series about {topic}! In Lesson 1, we explore why {topic} is so fascinating and listen to three key expressions you can use right away.",
            },
            {
                "lesson_num": 2,
                "title": f"Lesson 2 · Inside {topic}（细节与原理拆解）",
                "objective": "学会用因果连接词阐述现象与机制。",
                "vocab": [
                    {"en": "Mechanism", "zh": "机制 / 原理", "example": "Every system follows a clear mechanism."},
                    {"en": "Because of", "zh": "由于……", "example": "Changes happen because of hidden forces."},
                    {"en": "Compare", "zh": "对比", "example": "Let's compare different examples together."},
                ],
                "dialogue_script": f"In Lesson 2 of our {topic} journey, let's look closer! Practice saying 'because of' and 'compare' while picturing how {topic} works in real life.",
            },
            {
                "lesson_num": 3,
                "title": f"Lesson 3 · Real-World Stories on {topic}",
                "objective": "听懂真实生活应用场景中的英语问答。",
                "vocab": [
                    {"en": "For instance", "zh": "举例而言", "example": f"For instance, {topic} appears in daily life."},
                    {"en": "Challenge", "zh": "挑战", "example": "What challenge should we solve next?"},
                    {"en": "Improve", "zh": "改进 / 提升", "example": "Practice helps us steadily improve."},
                ],
                "dialogue_script": f"Lesson 3 brings {topic} into real conversations! Imagine explaining {topic} to an English-speaking friend using 'For instance'—give it a try out loud!",
            },
            {
                "lesson_num": 4,
                "title": f"Lesson 4 · Share Your View on {topic}",
                "objective": "完成一段 30 秒以上的英文主题总结陈述。",
                "vocab": [
                    {"en": "In my opinion", "zh": "在我看来", "example": f"In my opinion, {topic} changes our future."},
                    {"en": "Summarize", "zh": "总结", "example": "Let's summarize what we learned today."},
                    {"en": "Keep exploring", "zh": "保持探索", "example": "Stay curious and keep exploring!"},
                ],
                "dialogue_script": f"Congratulations on reaching Lesson 4 of {topic}! Put everything together starting with 'In my opinion' and share your final thoughts with EchoMind.",
            },
        ]
    else:
        lessons = [
            {
                "lesson_num": 1,
                "title": f"Lesson 1 · 初遇「{topic}」（Hello & Look）",
                "objective": f"建立孩子对「{topic}」中英文声音映射的兴趣。",
                "vocab": [
                    {"en": "Look!", "zh": "看呀！", "example": f"Look! A wonderful {topic} world!"},
                    {"en": "Hello!", "zh": "你好！", "example": f"Say hello to {topic}!"},
                    {"en": "Cool!", "zh": "太酷啦！", "example": "Wow, that is so cool!"},
                ],
                "dialogue_script": f"宝贝来听听今天的新主题系列课：{topic}！我们先竖起小耳朵打招呼：Hello! Look! 发现精彩的东西就大声欢呼：Cool! 准备好了吗？",
            },
            {
                "lesson_num": 2,
                "title": f"Lesson 2 · 观察「{topic}」的小细节（Big & Fun）",
                "objective": "用形容词短句描述大小、颜色与快乐感受。",
                "vocab": [
                    {"en": "So big", "zh": "好大呀", "example": "Look at that, it is so big!"},
                    {"en": "So fun", "zh": "太有趣啦", "example": f"Learning about {topic} is so fun!"},
                    {"en": "I like it", "zh": "我喜欢", "example": "I really like it!"},
                ],
                "dialogue_script": f"欢迎来到「{topic}」第2课！看到大大的东西，我们可以赞叹说：So big! 玩得开心的时候，笑着大声说：So fun! I like it!",
            },
            {
                "lesson_num": 3,
                "title": f"Lesson 3 · 一起玩转「{topic}」（Let's Play）",
                "objective": "结合生活小动作与简单英文问句互动。",
                "vocab": [
                    {"en": "What is this?", "zh": "这是什么？", "example": "Point and ask: What is this?"},
                    {"en": "Let's play", "zh": "我们一起玩吧", "example": f"Let's play a {topic} game!"},
                    {"en": "Good job", "zh": "干得真棒", "example": "High five! Good job!"},
                ],
                "dialogue_script": f"「{topic}」第3课互动游戏时间！手指指着好奇的东西问一句：What is this? 跟爸爸妈妈说：Let's play! 回答完记得击掌表扬自己：Good job!",
            },
            {
                "lesson_num": 4,
                "title": f"Lesson 4 · 「{topic}」毕业小剧场（Review）",
                "objective": "复习巩固前三课核心短句，建立成就感。",
                "vocab": [
                    {"en": "I know!", "zh": "我知道！", "example": "Raise your hand: I know!"},
                    {"en": "Thank you", "zh": "谢谢", "example": "Thank you for listening!"},
                    {"en": "See you next time", "zh": "下次见", "example": "Bye-bye, see you next time!"},
                ],
                "dialogue_script": f"太厉害啦！我们完成了「{topic}」系列课的全部 4 节旅程！大声自信地说出：I know! 最后我们一起说：Thank you, see you next time!",
            },
        ]

    return {
        "title": f"{stage.replace('_', '-')} · {topic}（定制系列课）",
        "subtitle": f"围绕「{topic}」生成的 4 节渐进伴学课",
        "cover_emoji": "✨",
        "description": f"根据兴趣主题「{topic}」实时创建的 {stage} 阶段沉浸伴学系列课程。",
        "lessons": lessons,
    }


async def generate_custom_english_course(topic: str, stage: str) -> dict[str, Any]:
    clean_topic = topic.strip() or "快乐生活"
    spec = await _llm_generate_course_spec(clean_topic, stage) or _template_generate_course_spec(clean_topic, stage)

    ts = now_iso()
    base_title = str(spec.get("title") or f"{stage} · {clean_topic}").strip()
    age_stage = STAGE_TO_AGE.get(stage, "S3_6_9")

    async with get_db() as conn:
        # 避免同名冲突
        cur_exist = await conn.execute("SELECT id FROM english_courses WHERE title = ?", (base_title,))
        if await cur_exist.fetchone():
            base_title = f"{base_title} ({uuid.uuid4().hex[:4]})"

        cur = await conn.execute(
            """
            INSERT INTO english_courses (title, subtitle, stage, age_stage, theme, cover_emoji, description, created_at)
            VALUES (?, ?, ?, ?, 'custom', ?, ?, ?)
            """,
            (
                base_title,
                str(spec.get("subtitle") or f"围绕「{clean_topic}」定制"),
                stage,
                age_stage,
                str(spec.get("cover_emoji") or "✨"),
                str(spec.get("description") or ""),
                ts,
            ),
        )
        course_id = int(cur.lastrowid)

        for idx, l in enumerate(spec.get("lessons", [])[:6], start=1):
            await conn.execute(
                """
                INSERT INTO english_lessons
                (course_id, lesson_num, title, objective, vocab_json, dialogue_script, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_id,
                    int(l.get("lesson_num") or idx),
                    str(l.get("title") or f"Lesson {idx}"),
                    str(l.get("objective") or ""),
                    json.dumps(l.get("vocab") or [], ensure_ascii=False),
                    str(l.get("dialogue_script") or ""),
                    ts,
                ),
            )
        await _sync_course_to_album(conn, course_id)
        await conn.commit()

    return await get_course_detail(course_id)


async def get_course_detail(course_id: int) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM english_courses WHERE id = ?", (course_id,))
        c_row = await cur.fetchone()
        if not c_row:
            raise ValueError("课程不存在")
        course = dict(c_row)
        cur_l = await conn.execute(
            "SELECT * FROM english_lessons WHERE course_id = ? ORDER BY lesson_num ASC, id ASC",
            (course_id,),
        )
        lessons = []
        for lr in await cur_l.fetchall():
            d = dict(lr)
            try:
                d["vocab"] = json.loads(d.get("vocab_json") or "[]")
            except Exception:
                d["vocab"] = []
            d["stream_url"] = f"/api/english/lessons/{d['id']}/stream"
            lessons.append(d)
        course["lessons"] = lessons
        course["total_lessons"] = len(lessons)
        course["completed_lessons"] = sum(1 for x in lessons if int(x.get("completed") or 0) == 1)
        return course


async def synthesize_lesson_audio(lesson_id: int, force: bool = False) -> tuple[Path, float]:
    """按课程分级音色合成单节课时伴学 MP3（-16 LUFS 护耳），并持久化磁盘路径。"""
    ENGLISH_LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT l.*, c.stage AS course_stage
            FROM english_lessons l
            JOIN english_courses c ON l.course_id = c.id
            WHERE l.id = ?
            """,
            (lesson_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError("课时不存在")
        lesson = dict(row)

    existing_path = Path(lesson["audio_path"]) if lesson.get("audio_path") else None
    if not force and existing_path and existing_path.exists() and existing_path.stat().st_size > 256:
        return existing_path, float(lesson.get("duration_sec") or 0.0)

    stage = lesson.get("course_stage", "Pre_A1")
    if stage in ("B1", "B2_PLUS"):
        voice = "en-US-AriaNeural"
        rate = "+0%"
    else:
        voice = "zh-CN-XiaoxiaoNeural"
        rate = "-6%"

    script = lesson.get("dialogue_script") or lesson["title"]
    raw_tmp = MEDIA_RAW_DIR / f"eng_lesson_{lesson_id}_{uuid.uuid4().hex[:6]}.mp3"
    dst = ENGLISH_LESSONS_DIR / f"course{lesson['course_id']}_lesson{lesson['lesson_num']}_{lesson_id}.mp3"

    try:
        await synthesize_speech(script, voice=voice, rate=rate, output_path=raw_tmp, normalize_lufs=False)
        _, dur = await normalize_audio_to_lufs(raw_tmp, dst)
    finally:
        raw_tmp.unlink(missing_ok=True)

    async with get_db() as conn:
        await conn.execute(
            "UPDATE english_lessons SET audio_path = ?, duration_sec = ? WHERE id = ?",
            (str(dst), dur, lesson_id),
        )
        await conn.commit()

    return dst, dur
