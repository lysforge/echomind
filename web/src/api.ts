export type AgeStage = "S1_0_3" | "S2_3_6" | "S3_6_9" | "S4_9_12" | "S5_12_18" | "S6_ALL";
export type EnglishLevel = "Pre_A1" | "A1" | "A2" | "B1" | "B2_PLUS" | "adult";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "user";
  is_active: number;
  created_at?: string;
  last_login_at?: string | null;
}

export interface FamilyMember {
  id: number;
  owner_user_id?: number;
  name: string;
  nickname: string;
  role: "child" | "adult";
  birth_date: string;
  age_months: number | null;
  age_label: string;
  age_stage: AgeStage;
  recommended_age_stage?: AgeStage;
  english_stage: EnglishLevel;
  tts_voice: string;
  tts_rate: string;
  voiceprint_samples: number;
  has_voiceprint: boolean;
  created_at: string;
}

export interface DeviceInfo {
  id: string;
  name: string;
  device_type: "speaker_xiaoai" | "esp32_robot";
  room: string;
  auth_token: string;
  pair_code: string;
  paired: number;
  online: number;
  volume: number;
  max_volume: number;
  wake_word: string;
  playing_title: string;
  client_ip: string;
  motion_locked: number;
  last_seen_at: string;
  connect_cmd?: string;
}

export interface MediaTrack {
  id: number;
  album_id: number;
  title: string;
  episode_num: number;
  duration_sec: number;
  file_path: string;
  source_url: string;
  text_content?: string;
  vocab?: Array<{ en: string; zh: string; example: string }>;
  objective?: string;
  completed?: number;
  last_position_sec?: number;
  last_played_at?: string | null;
  stream_url?: string;
  lufs_normalized: number;
  play_count: number;
  created_at: string;
}

export interface MediaAlbum {
  id: number;
  series_id?: number | null;
  season_num?: number;
  season_label?: string;
  title: string;
  category: "music" | "story" | "english" | "podcast";
  sub_tag?: string;
  age_stage: AgeStage;
  english_level: EnglishLevel;
  play_mode: "sequential" | "shuffle";
  cover_emoji?: string;
  author?: string;
  language?: string;
  is_inbox?: number;
  description: string;
  last_track_id: number | null;
  last_position_sec: number;
  track_count?: number;
  tracks?: MediaTrack[];
}

export interface SeriesResumeInfo {
  album_id: number;
  season_num: number;
  season_label: string;
  track_id: number;
  track_title: string;
  episode_num: number;
  position_sec: number;
  last_played_at: string | null;
}

export interface MediaSeries {
  id: number;
  title: string;
  channel: "music" | "story" | "english" | "podcast";
  level_code: string;
  cover_emoji: string;
  author: string;
  description: string;
  last_album_id: number | null;
  last_track_id: number | null;
  last_position_sec: number;
  last_played_at: string | null;
  created_at: string;
  seasons: MediaAlbum[];
  season_count: number;
  total_tracks: number;
  completed_tracks: number;
  resume_info: SeriesResumeInfo | null;
}

export interface CategoryTag {
  id: number;
  channel: MediaAlbum["category"];
  name: string;
  sort_order: number;
}

export interface RoomPlaybackSession {
  series_id?: number | null;
  season_num?: number;
  season_label?: string;
  album_id: number | null;
  album_title: string;
  status: "playing" | "paused" | "stopped";
  loop_mode: "sequential" | "repeat_one" | "shuffle";
  current_index: number;
  start_position_sec?: number;
  current_track: { id: number; title: string; episode_num?: number; duration_sec: number; stream_url: string } | null;
  queue: Array<{ id: number; title: string; episode_num?: number; duration_sec: number; stream_url: string }>;
  sleep_remaining_sec: number | null;
  sleep_remaining_episodes: number | null;
}

export interface RoomPlaybackState extends DeviceInfo {
  session: RoomPlaybackSession | null;
}

export interface BookChapter {
  id: number;
  book_id: number;
  chapter_num: number;
  title: string;
  text_content: string;
  file_path: string;
  duration_sec: number;
  lufs_normalized: number;
  play_count: number;
  created_at: string;
}

export interface BookItem {
  id: number;
  title: string;
  author: string;
  category: "picture_book" | "bridge_book" | "chapter_lit" | "science" | "english_graded";
  age_stage: AgeStage;
  english_level: EnglishLevel;
  language: "zh" | "en" | "bilingual";
  description: string;
  chapters: BookChapter[];
  progress?: { last_chapter_id: number; position_sec: number } | null;
}

export interface ContentSource {
  id: number;
  name: string;
  source_type: "podcast_rss" | "ytdlp_playlist";
  url: string;
  target_album_id: number | null;
  album_title?: string | null;
  age_stage: AgeStage;
  english_level: EnglishLevel;
  auto_sync: number;
  sync_interval_hours: number;
  max_items_per_sync: number;
  last_synced_at: string | null;
  last_status: string;
}

export interface EnglishItem {
  id: number;
  phrase: string;
  zh_meaning: string;
  stage: Exclude<EnglishLevel, "adult">;
  category: "daily" | "animal" | "nature" | "science" | "dialogue";
  audio_prompt: string;
  listen_count: number;
  mastery_level: number;
  last_played_at: string | null;
}

export interface EnglishVocabItem {
  en: string;
  zh: string;
  example: string;
}

export interface EnglishLesson {
  id: number;
  course_id: number;
  lesson_num: number;
  title: string;
  objective: string;
  vocab: EnglishVocabItem[];
  dialogue_script: string;
  audio_path: string;
  duration_sec: number;
  listen_count: number;
  completed: number;
  last_studied_at: string | null;
  stream_url: string;
}

export interface EnglishCourse {
  id: number;
  title: string;
  subtitle: string;
  stage: Exclude<EnglishLevel, "adult">;
  age_stage: AgeStage;
  theme: string;
  cover_emoji: string;
  description: string;
  lessons: EnglishLesson[];
  total_lessons: number;
  completed_lessons: number;
  created_at: string;
}

export interface LocalFolder {
  id: number;
  name: string;
  folder_path: string;
  media_type: "auto" | "music" | "story" | "book";
  age_stage: AgeStage;
  last_scanned_at: string | null;
  last_scan_summary: string;
  file_count: number;
  created_at: string;
}

export interface LocalFileItem {
  uid: string;
  id: number;
  kind: "track" | "chapter";
  sub_category: string;
  title: string;
  container_id: number;
  container_title: string;
  age_stage: AgeStage;
  duration_sec: number;
  play_count: number;
  file_path: string;
  stream_url: string;
  created_at: string;
}

export interface OnlineStreamItem {
  id: number;
  title: string;
  url: string;
  stream_kind: "direct_audio" | "playlist_url";
  category: "music" | "story" | "english" | "podcast";
  age_stage: AgeStage;
  description: string;
  cached_track_id: number | null;
  cached?: boolean;
  play_count: number;
  created_at: string;
}

export interface SourcePreset {
  name: string;
  source_type: "podcast_rss" | "ytdlp_playlist";
  url: string;
  age_stage: AgeStage;
  english_level: EnglishLevel;
  description: string;
}

export interface PodcastEpisode {
  guid: string;
  title: string;
  published: string;
  audio_url: string;
  cached: boolean;
  local_track_id: number | null;
  stream_url: string | null;
  duration_sec: number;
}

export interface ScheduleItem {
  id: number;
  name: string;
  cron_time: string;
  days_of_week: string;
  task_type: "play_album" | "play_book" | "english_immersion" | "bedtime_story" | "quiet_mode";
  target_device_id: string | null;
  album_id: number | null;
  book_id: number | null;
  album_title?: string | null;
  book_title?: string | null;
  device_name?: string | null;
  target_volume: number;
  max_episodes: number;
  fade_out: number;
  enabled: number;
  last_run_at: string | null;
}

export interface MemoryItem {
  id: number;
  member_id: number | null;
  member_name?: string | null;
  scope: "personal" | "family" | "growth";
  category: string;
  content: string;
  importance: number;
  created_at: string;
}

export interface DownloadJob {
  id: number;
  job_type: string;
  source_url: string;
  target_album_id: number | null;
  album_title?: string | null;
  status: "pending" | "running" | "done" | "failed";
  progress_text: string;
  error_msg: string;
  tracks_added: number;
  created_at: string;
}

export interface DashboardData {
  brand: string;
  home_name: string;
  assistant_name: string;
  onboarding_completed: boolean;
  lan_ip: string;
  server_port: number;
  quiet_hours_active: boolean;
  llm_configured: boolean;
  members: FamilyMember[];
  devices: DeviceInfo[];
  pending_devices: DeviceInfo[];
  english_items: EnglishItem[];
  albums: MediaAlbum[];
  book_count: number;
  source_count: number;
  schedules: ScheduleItem[];
  growth_summary: {
    today_interactions: number;
    today_english_count: number;
    total_media_plays: number;
    recent_moments: Array<{ user_text: string; assistant_text: string; time: string }>;
  };
}

export interface SettingsPayload {
  home_name: string;
  assistant_name: string;
  onboarding_completed: boolean;
  llm_provider: "deepseek" | "openai" | "ollama";
  llm_base_url: string;
  llm_model: string;
  has_llm_key: boolean;
  llm_api_key_masked: string;
  tts_voice_child: string;
  tts_rate_child: string;
  tts_voice_adult: string;
  tts_rate_adult: string;
  asr_mode: "local_or_fallback" | "siliconflow";
  asr_base_url: string;
  asr_model: string;
  has_asr_key: boolean;
  asr_api_key_masked: string;
  voiceprint_api_url: string;
  voiceprint_threshold: number;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  quiet_hours_force_active: boolean;
  loudnorm_target_lufs: number;
  public_base_url?: string;
  resolved_public_base_url?: string;
  music_dl_url: string;
  music_dl_sources: string;
  mi_user?: string;
  has_mi_pass?: boolean;
  mi_pass_masked?: string;
  mi_poll_enabled?: boolean;
  mi_poll_interval_sec?: number;
  mi_trigger_keywords?: string;
  hardware_endpoints: {
    lan_ip: string;
    port: number;
    speaker_ws_url: string;
    robot_ota_url: string;
    robot_ws_url: string;
    mcp_url?: string;
  };
}

export interface XiaoAiDiscoveredDevice {
  mi_device_id: string;
  miot_did: string;
  name: string;
  hardware: string;
  mac: string;
  presence: string;
  online: boolean;
}

export interface XiaoAiBridgeStatus {
  library_available: boolean;
  configured: boolean;
  poll_enabled: boolean;
  poll_running: boolean;
  public_base_url: string;
  bound_count: number;
  bound_devices: Array<{ id: string; name: string; room: string; mi_device_id: string; hardware: string }>;
  recent_asks: Array<{ device_id: string; device_name: string; query: string; handled: boolean; time: string }>;
  last_error: string;
}

export interface WebDavMount {
  id: number;
  name: string;
  base_url: string;
  username: string;
  password: string;
  has_password?: boolean;
  remote_path: string;
  channel: "music" | "story" | "english" | "podcast";
  level_code: string;
  last_synced_at: string | null;
  last_status: string;
  tracks_synced: number;
  created_at: string;
}

export interface StorageOverview {
  data_dir: string;
  disk_total_gb: number;
  disk_used_gb: number;
  disk_free_gb: number;
  disk_used_pct: number;
  media_tracks_mb: number;
  raw_cache_mb: number;
  tts_cache_mb: number;
  duplicate_track_count: number;
  channel_usage_mb: Record<string, number>;
  series_usage: Array<{
    series_id: number;
    title: string;
    channel: string;
    cover_emoji: string;
    track_count: number;
    size_mb: number;
  }>;
}

export interface EnglishCheckinStats {
  member_key: string;
  streak_days: number;
  total_checkins: number;
  total_minutes: number;
  today_checked: boolean;
  last_7_days: Array<{ date: string; label: string; checked: boolean; count: number; minutes: number }>;
}

export interface CloudSong {
  id: string;
  source: string;
  name: string;
  artist: string;
  album: string;
  cover: string;
  duration: number;
  extra: Record<string, unknown>;
}

export interface CloudCollection {
  id: string;
  source: string;
  title: string;
  cover: string;
  creator: string;
  track_count: number;
  content_type: "playlist" | "album";
}

export interface CloudTopList {
  source: string;
  toplist_id: string;
  name: string;
  update_frequency: string;
  cover: string;
  description: string;
  track_count: number;
  play_count_text: string;
}

export interface CloudMusicStatus {
  ok: boolean;
  base_url: string;
  sources: string[];
  latency_ms: number;
  error: string;
  supported_sources: Array<{ id: string; label: string }>;
}

const TOKEN_KEY = "echomind_auth_token";
let onUnauthorizedCb: (() => void) | null = null;

export function setOnUnauthorized(cb: () => void) {
  onUnauthorizedCb = cb;
}

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setStoredToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401 && !url.startsWith("/api/auth/")) {
    setStoredToken("");
    onUnauthorizedCb?.();
  }
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try {
      const data = await res.json();
      msg = data.detail || data.message || msg;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authStatus: () => req<{ initialized: boolean; user_count: number; user: AuthUser | null }>("/api/auth/status"),
  register: (payload: { username: string; password: string; display_name?: string }) =>
    req<{ token: string; user: AuthUser }>("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  login: (payload: { username: string; password: string }) =>
    req<{ token: string; user: AuthUser }>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  logout: () => req("/api/auth/logout", { method: "POST" }),

  adminListUsers: () => req<AuthUser[]>("/api/admin/users"),
  adminCreateUser: (payload: { username: string; password: string; display_name: string; role: "admin" | "user" }) =>
    req<AuthUser>("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  adminUpdateUser: (id: number, payload: { display_name?: string; role?: "admin" | "user"; is_active?: boolean; new_password?: string }) =>
    req(`/api/admin/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  adminDeleteUser: (id: number) => req(`/api/admin/users/${id}`, { method: "DELETE" }),
  adminSeedSampleCatalog: () =>
    req<{
      books_added: number;
      chapters_added: number;
      albums_added: number;
      tracks_added: number;
      english_added: number;
      sources_added: number;
      courses_added?: number;
      lessons_added?: number;
    }>("/api/admin/seed-sample-catalog", {
      method: "POST",
    }),

  getDashboard: () => req<DashboardData>("/api/dashboard"),
  completeOnboarding: (payload: { home_name?: string; assistant_name?: string }) =>
    req("/api/onboarding/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  interact: (text: string, simulatedMemberId: number | null, deviceId: string) =>
    req<{
      user_text: string;
      reply_text: string;
      speaker: { name: string; safety_mode: string; confidence: number; age_stage: string; english_stage: string };
      memory_scope_used: string[];
      tts_url: string;
      play_track?: {
        id: number;
        title: string;
        album_id?: number;
        album_title?: string;
        series_id?: number;
        series_title?: string;
        season_num?: number;
        season_label?: string;
        episode_num?: number;
        start_position_sec?: number;
        duration_sec?: number;
        stream_url?: string;
        is_cached?: boolean;
        caching?: boolean;
        media_kind?: string;
      } | null;
      queue_tracks?: Array<{
        id: number;
        title: string;
        album_id?: number;
        album_title?: string;
        episode_num?: number;
        duration_sec?: number;
        stream_url?: string;
      }>;
      control_action?: {
        action: string;
        value?: number;
        delta?: number;
        delta_sec?: number;
        loop_mode?: "sequential" | "repeat_one" | "shuffle";
        minutes?: number;
        episodes?: number;
        album_id?: number;
        start_index?: number;
        index?: number;
        episode_num?: number;
      };
      background_job?: {
        job_id: number;
        status: string;
        query: string;
        preview?: {
          channel: string;
          series_title: string;
          season_num: number;
          season_label: string;
          level_code: string;
        };
      } | null;
      track_url?: string | null;
    }>("/api/interact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, simulated_member_id: simulatedMemberId, device_id: deviceId }),
    }),

  // Devices
  listDevices: () => req<{ devices: DeviceInfo[]; pending_devices: DeviceInfo[] }>("/api/devices"),
  createDevice: (payload: { name: string; device_type: "speaker_xiaoai" | "esp32_robot"; room: string; max_volume: number; wake_word: string }) =>
    req<DeviceInfo>("/api/devices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  claimDevice: (payload: { device_id?: string; pair_code?: string; name: string; room: string; max_volume: number }) =>
    req<DeviceInfo>("/api/devices/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateDevice: (id: string, payload: Partial<DeviceInfo>) =>
    req<DeviceInfo>(`/api/devices/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteDevice: (id: string) => req(`/api/devices/${id}`, { method: "DELETE" }),
  controlDevice: (id: string, command: "pause" | "stop" | "test_sound") =>
    req<{ tts_url?: string }>(`/api/devices/${id}/control`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    }),
  announceDevice: (id: string, text: string) =>
    req<{ tts_url: string }>(`/api/devices/${id}/announce`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  robotMotion: (id: string, action: string) =>
    req<{ motion: { allowed: boolean; blocked_reason?: string; action: string } }>(`/api/devices/${id}/motion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }),

  // Books
  listBooks: (params?: { age_stage?: string; category?: string; q?: string }) => {
    const qs = new URLSearchParams();
    if (params?.age_stage) qs.set("age_stage", params.age_stage);
    if (params?.category) qs.set("category", params.category);
    if (params?.q) qs.set("q", params.q);
    return req<BookItem[]>(`/api/books?${qs.toString()}`);
  },
  createBook: (payload: Partial<BookItem>) =>
    req<BookItem>("/api/books", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateBook: (id: number, payload: Partial<BookItem>) =>
    req(`/api/books/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteBook: (id: number) => req(`/api/books/${id}`, { method: "DELETE" }),
  addChapterFromText: (bookId: number, payload: { title: string; text_content: string; chapter_num?: number }) =>
    req<BookChapter>(`/api/books/${bookId}/chapters/from-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  addChapterUpload: async (bookId: number, title: string, file: File) => {
    const fd = new FormData();
    fd.append("title", title);
    fd.append("file", file);
    return req<BookChapter>(`/api/books/${bookId}/chapters/upload`, { method: "POST", body: fd });
  },
  deleteChapter: (chapterId: number) => req(`/api/books/chapters/${chapterId}`, { method: "DELETE" }),
  castChapter: (chapterId: number, deviceId: string) =>
    req(`/api/books/chapters/${chapterId}/cast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId }),
    }),

  // Series -> Season -> Track 三级树 API
  listSeries: (params?: { channel?: string; level_code?: string; q?: string; member_key?: string }) => {
    const qs = new URLSearchParams();
    if (params?.channel) qs.set("channel", params.channel);
    if (params?.level_code) qs.set("level_code", params.level_code);
    if (params?.q) qs.set("q", params.q);
    if (params?.member_key) qs.set("member_key", params.member_key);
    return req<MediaSeries[]>(`/api/media/series?${qs.toString()}`);
  },
  createSeries: (payload: {
    title: string;
    channel: MediaSeries["channel"];
    level_code?: string;
    cover_emoji?: string;
    author?: string;
    description?: string;
    auto_create_first_season?: boolean;
    first_season_label?: string;
  }) =>
    req<MediaSeries>("/api/media/series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateSeries: (
    id: number,
    payload: Partial<Pick<MediaSeries, "title" | "channel" | "level_code" | "cover_emoji" | "author" | "description">>
  ) =>
    req<MediaSeries>(`/api/media/series/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteSeries: (id: number) => req(`/api/media/series/${id}`, { method: "DELETE" }),
  createSeason: (
    seriesId: number,
    payload: { season_num?: number; season_label?: string; title?: string; description?: string; play_mode?: "sequential" | "shuffle" }
  ) =>
    req<MediaAlbum>(`/api/media/series/${seriesId}/seasons`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  aiCollect: (payload: {
    query: string;
    channel_hint?: MediaSeries["channel"];
    series_id?: number | null;
    album_id?: number | null;
    max_items?: number;
    device_id?: string;
    notify_speaker?: boolean;
  }) =>
    req<{
      job_id: number;
      status: string;
      query: string;
      preview?: { channel: string; series_title: string; season_num: number; season_label: string; level_code: string };
    }>("/api/media/collect/ai-collect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // Category Tags & Unified Media
  listTags: (channel?: string) => {
    const qs = new URLSearchParams();
    if (channel) qs.set("channel", channel);
    return req<CategoryTag[]>(`/api/media/tags?${qs.toString()}`);
  },
  createTag: (payload: { channel: MediaAlbum["category"]; name: string; sort_order?: number }) =>
    req<CategoryTag>("/api/media/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTag: (tagId: number) => req(`/api/media/tags/${tagId}`, { method: "DELETE" }),

  getAlbums: (params?: { category?: string; sub_tag?: string; age_stage?: string; q?: string; only_inbox?: boolean; exclude_inbox?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set("category", params.category);
    if (params?.sub_tag) qs.set("sub_tag", params.sub_tag);
    if (params?.age_stage) qs.set("age_stage", params.age_stage);
    if (params?.q) qs.set("q", params.q);
    if (params?.only_inbox) qs.set("only_inbox", "true");
    if (params?.exclude_inbox) qs.set("exclude_inbox", "true");
    return req<MediaAlbum[]>(`/api/media/albums?${qs.toString()}`);
  },
  createAlbum: (payload: Omit<Partial<MediaAlbum>, "is_inbox"> & { is_inbox?: number | boolean }) =>
    req<MediaAlbum>("/api/media/albums", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateAlbum: (id: number, payload: Omit<Partial<MediaAlbum>, "is_inbox"> & { is_inbox?: number | boolean }) =>
    req(`/api/media/albums/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteAlbum: (id: number) => req(`/api/media/albums/${id}`, { method: "DELETE" }),
  addTrackFromText: (albumId: number, payload: { title: string; text_content: string; language?: string; objective?: string }) =>
    req<MediaTrack>(`/api/media/albums/${albumId}/tracks/from-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateTrack: (id: number, payload: { title?: string; episode_num?: number; text_content?: string; completed?: boolean; album_id?: number }) =>
    req<MediaTrack>(`/api/media/tracks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTrack: (id: number) => req(`/api/media/tracks/${id}`, { method: "DELETE" }),

  // Connect / Sonos Style Room Playback Queue
  listPlaybackRooms: () => req<RoomPlaybackState[]>("/api/playback/rooms"),
  pushPlayback: (payload: {
    device_ids: string[];
    series_id?: number;
    album_id?: number;
    track_ids?: number[];
    start_index?: number;
    start_position_sec?: number;
    resume?: boolean;
    loop_mode?: "sequential" | "repeat_one" | "shuffle";
    sleep_minutes?: number | null;
    sleep_episodes?: number | null;
  }) =>
    req<{ status: string; rooms: RoomPlaybackState[] }>("/api/playback/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  controlRoomPlayback: (
    deviceId: string,
    payload: {
      action: "pause" | "resume" | "stop" | "next" | "prev" | "jump" | "replay" | "seek_delta" | "set_loop" | "set_sleep";
      index?: number;
      delta_sec?: number;
      loop_mode?: "sequential" | "repeat_one" | "shuffle";
      sleep_minutes?: number | null;
      sleep_episodes?: number | null;
    }
  ) =>
    req<RoomPlaybackState>(`/api/playback/rooms/${deviceId}/control`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  castTrack: (trackId: number, deviceId: string) =>
    req(`/api/media/tracks/${trackId}/cast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId }),
    }),
  saveProgress: (albumId: number, trackId: number, positionSec: number, memberKey = "") =>
    req(`/api/media/albums/${albumId}/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: trackId, position_sec: positionSec, member_key: memberKey }),
    }),
  searchOnline: (q: string) => req<Array<{ title: string; duration_sec: number; uploader: string; url: string }>>(`/api/media/search-online?q=${encodeURIComponent(q)}`),
  getJobs: () => req<DownloadJob[]>("/api/media/jobs"),
  collectYtdlp: (url: string, albumId: number, maxItems = 10) =>
    req("/api/media/collect/ytdlp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, album_id: albumId, max_items: maxItems }),
    }),
  collectRss: (rssUrl: string, albumId: number, limit = 5) =>
    req("/api/media/collect/rss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rss_url: rssUrl, album_id: albumId, limit }),
    }),
  uploadAudio: async (albumId: number, file: File) => {
    const fd = new FormData();
    fd.append("album_id", String(albumId));
    fd.append("file", file);
    return req("/api/media/collect/upload", { method: "POST", body: fd });
  },
  playAndCache: (payload: {
    title: string;
    url: string;
    category?: MediaAlbum["category"];
    album_id?: number | null;
    source_id?: number | null;
    external_guid?: string;
    age_stage?: AgeStage;
    device_id?: string;
    online_stream_id?: number | null;
  }) =>
    req<{
      track: { id: number; title: string; album_id?: number; album_title?: string; stream_url: string; duration_sec?: number };
      stream_url: string;
      is_cached: boolean;
      caching: boolean;
    }>("/api/media/play-and-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listLocalFolders: () =>
    req<{ folders: LocalFolder[]; suggested_paths: Array<{ name: string; path: string }> }>("/api/media/local-folders"),
  createLocalFolder: (payload: { name: string; folder_path: string; media_type: LocalFolder["media_type"]; age_stage: AgeStage }) =>
    req<LocalFolder>("/api/media/local-folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteLocalFolder: (id: number) => req(`/api/media/local-folders/${id}`, { method: "DELETE" }),
  scanLocalFolder: (id: number) =>
    req<{ folder_id: number; total_files: number; tracks_added: number; chapters_added: number; summary: string }>(
      `/api/media/local-folders/${id}/scan`,
      { method: "POST" }
    ),
  listLocalFiles: (kind = "all", q = "") => {
    const qs = new URLSearchParams();
    if (kind) qs.set("kind", kind);
    if (q) qs.set("q", q);
    return req<LocalFileItem[]>(`/api/media/local-files?${qs.toString()}`);
  },
  listOnlineStreams: () => req<OnlineStreamItem[]>("/api/media/online-streams"),
  createOnlineStream: (payload: Partial<OnlineStreamItem>) =>
    req<OnlineStreamItem>("/api/media/online-streams", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteOnlineStream: (id: number) => req(`/api/media/online-streams/${id}`, { method: "DELETE" }),

  // Content Sources (Admin & Podcast View)
  listSources: () => req<ContentSource[]>("/api/content-sources"),
  getSourcePresets: () => req<SourcePreset[]>("/api/content-sources/presets"),
  getSourceEpisodes: (id: number) =>
    req<{ source: ContentSource; remote_ok: boolean; remote_error: string; episodes: PodcastEpisode[] }>(
      `/api/content-sources/${id}/episodes`
    ),
  createSource: (payload: Omit<Partial<ContentSource>, "auto_sync"> & { auto_sync?: boolean | number }) =>
    req("/api/content-sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateSource: (id: number, payload: Record<string, unknown>) =>
    req(`/api/content-sources/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteSource: (id: number) => req(`/api/content-sources/${id}`, { method: "DELETE" }),
  probeSource: (sourceType: string, url: string) =>
    req<{ source_title: string; count: number; preview: Array<{ title: string }> }>("/api/content-sources/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_type: sourceType, url }),
    }),
  syncSource: (id: number) => req<{ message: string }>(`/api/content-sources/${id}/sync`, { method: "POST" }),

  // English Courses & Items
  listEnglishCourses: (stage?: string) => {
    const qs = new URLSearchParams();
    if (stage && stage !== "all") qs.set("stage", stage);
    return req<EnglishCourse[]>(`/api/english/courses?${qs.toString()}`);
  },
  seedBuiltinCourses: () =>
    req<{ courses_added: number; lessons_added: number; vocab_added: number }>("/api/english/courses/seed-builtin", {
      method: "POST",
    }),
  generateEnglishCourse: (payload: { topic: string; stage: Exclude<EnglishLevel, "adult"> }) =>
    req<EnglishCourse>("/api/english/courses/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteEnglishCourse: (id: number) => req(`/api/english/courses/${id}`, { method: "DELETE" }),
  playEnglishLesson: (lessonId: number, payload: { device_id?: string; mark_completed?: boolean }) =>
    req<{ lesson: EnglishLesson; stream_url: string }>(`/api/english/lessons/${lessonId}/play`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  patchEnglishLesson: (lessonId: number, completed: boolean) =>
    req<EnglishLesson>(`/api/english/lessons/${lessonId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed }),
    }),
  pronounceEnglish: (text: string, rate = "-8%", deviceId = "") =>
    req<{ text: string; tts_url: string }>("/api/english/pronounce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, rate, device_id: deviceId }),
    }),
  getEnglishStats: (memberKey = "") => {
    const qs = new URLSearchParams();
    if (memberKey) qs.set("member_key", memberKey);
    return req<EnglishCheckinStats>(`/api/english/stats?${qs.toString()}`);
  },
  recordEnglishCheckin: (payload: { track_id?: number | null; duration_min?: number; spoken_score?: number; note?: string; member_key?: string }) =>
    req<EnglishCheckinStats>("/api/english/checkin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  evaluateEnglishSpeech: async (expectedText: string, blob: Blob, trackId?: number | null, memberKey = "") => {
    const fd = new FormData();
    fd.append("expected_text", expectedText);
    if (trackId) fd.append("track_id", String(trackId));
    if (memberKey) fd.append("member_key", memberKey);
    fd.append("file", blob, "follow_read.webm");
    return req<{ expected_text: string; recognized_text: string; stars: number; feedback: string }>(
      "/api/english/evaluate-speech",
      { method: "POST", body: fd }
    );
  },

  // XiaoAi Cloud Bridge & MCP
  getXiaoAiStatus: () => req<XiaoAiBridgeStatus>("/api/devices/xiaoai/status"),
  discoverXiaoAiDevices: (payload: { mi_user?: string; mi_pass?: string; public_base_url?: string; save_credentials?: boolean }) =>
    req<{ devices: XiaoAiDiscoveredDevice[]; count: number }>("/api/devices/xiaoai/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  bindXiaoAiDevice: (payload: { mi_device_id: string; miot_did?: string; name: string; hardware?: string; room: string; max_volume: number }) =>
    req<DeviceInfo>("/api/devices/xiaoai/bind", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  toggleXiaoAiPolling: (payload: { enabled: boolean; poll_interval_sec?: number; trigger_keywords?: string }) =>
    req<XiaoAiBridgeStatus>("/api/devices/xiaoai/poll-toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listMcpTools: () =>
    req<{ server: string; protocolVersion: string; tools: Array<{ name: string; description: string }> }>("/api/mcp/tools"),

  // WebDAV & Storage Overview
  listWebDavMounts: () => req<WebDavMount[]>("/api/media/webdav-mounts"),
  previewWebDav: (payload: { base_url: string; remote_path?: string; username?: string; password?: string }) =>
    req<{ entries: Array<{ name: string; is_dir: boolean; size: number; path: string }>; count: number }>("/api/media/webdav-mounts/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  createWebDavMount: (payload: {
    name: string;
    base_url: string;
    username?: string;
    password?: string;
    remote_path?: string;
    channel: "music" | "story" | "english" | "podcast";
    level_code?: string;
  }) =>
    req<WebDavMount>("/api/media/webdav-mounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteWebDavMount: (id: number) => req(`/api/media/webdav-mounts/${id}`, { method: "DELETE" }),
  syncWebDavMount: (id: number, maxFiles = 80) =>
    req<{ mount_id: number; total_discovered: number; tracks_added: number; skipped: number; summary: string }>(
      `/api/media/webdav-mounts/${id}/sync?max_files=${maxFiles}`,
      { method: "POST" }
    ),
  getStorageOverview: () => req<StorageOverview>("/api/media/storage"),
  cleanStorageCache: () =>
    req<{ status: string; removed_files: number; freed_mb: number }>("/api/media/storage/clean-cache", { method: "POST" }),
  listEnglish: (stage?: string, q?: string) => {
    const qs = new URLSearchParams();
    if (stage) qs.set("stage", stage);
    if (q) qs.set("q", q);
    return req<EnglishItem[]>(`/api/english/items?${qs.toString()}`);
  },
  createEnglish: (payload: Partial<EnglishItem>) =>
    req("/api/english/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateEnglish: (id: number, payload: Partial<EnglishItem>) =>
    req(`/api/english/items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteEnglish: (id: number) => req(`/api/english/items/${id}`, { method: "DELETE" }),
  practiceEnglish: (id: number, recordSpoken: boolean, deviceId: string) =>
    req<{ item: EnglishItem; tts_url: string }>(`/api/english/items/${id}/practice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_spoken: recordSpoken, device_id: deviceId }),
    }),

  // Family & Memories
  listMembers: () => req<FamilyMember[]>("/api/members"),
  createMember: (payload: Partial<FamilyMember>) =>
    req<FamilyMember>("/api/members", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateMember: (id: number, payload: Partial<FamilyMember>) =>
    req<FamilyMember>(`/api/members/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteMember: (id: number) => req(`/api/members/${id}`, { method: "DELETE" }),
  previewTTS: (voice: string, rate: string, text?: string) =>
    req<{ tts_url: string }>("/api/members/preview-tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice, rate, text: text || "你好，这是当前选中音色的试听效果。" }),
    }),
  uploadVoiceprint: async (memberId: number, blob: Blob) => {
    const fd = new FormData();
    fd.append("file", blob, "voiceprint.webm");
    return req<{ voiceprint_samples: number }>(`/api/members/${memberId}/voiceprint`, { method: "POST", body: fd });
  },
  clearVoiceprint: (memberId: number) => req(`/api/members/${memberId}/voiceprint`, { method: "DELETE" }),
  identifyVoiceprint: async (blob: Blob) => {
    const fd = new FormData();
    fd.append("file", blob, "probe.webm");
    return req<{ name: string; safety_mode: string; confidence: number }>("/api/members/identify-audio", { method: "POST", body: fd });
  },
  listMemories: (scope?: string, q?: string) => {
    const qs = new URLSearchParams();
    if (scope) qs.set("scope", scope);
    if (q) qs.set("q", q);
    return req<MemoryItem[]>(`/api/memories?${qs.toString()}`);
  },
  createMemory: (payload: { member_id: number | null; scope: "personal" | "family" | "growth"; content: string }) =>
    req("/api/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateMemory: (id: number, content: string) =>
    req(`/api/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  deleteMemory: (id: number) => req(`/api/memories/${id}`, { method: "DELETE" }),

  // Schedules
  createSchedule: (payload: Record<string, unknown>) =>
    req("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  replaceSchedule: (id: number, payload: Record<string, unknown>) =>
    req(`/api/schedules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  toggleSchedule: (id: number, enabled: boolean) =>
    req(`/api/schedules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteSchedule: (id: number) => req(`/api/schedules/${id}`, { method: "DELETE" }),
  triggerSchedule: (id: number) => req<{ message: string }>(`/api/schedules/${id}/trigger`, { method: "POST" }),
  toggleQuietHours: (active: boolean) =>
    req<{ quiet_hours_active: boolean }>("/api/schedules/quiet-toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    }),

  // Settings
  getSettings: () => req<SettingsPayload>("/api/settings"),
  updateSettings: (payload: Record<string, unknown>) =>
    req<SettingsPayload>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testLLM: (payload: { llm_base_url?: string; llm_api_key?: string; llm_model?: string }) =>
    req<{ ok: boolean; latency_ms: number; reply_preview?: string; error?: string }>("/api/settings/test-llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testMusicDl: (music_dl_url?: string) =>
    req<CloudMusicStatus>("/api/settings/test-music-dl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ music_dl_url }),
    }),

  // Cloud Music (go-music-dl)
  cloudMusicStatus: () => req<CloudMusicStatus>("/api/cloud-music/status"),
  cloudMusicSearch: (q: string, searchType: "song" | "playlist" | "album" = "song", sources?: string[], page = 1) => {
    const qs = new URLSearchParams({ q, search_type: searchType, page: String(page) });
    if (sources && sources.length > 0) qs.set("sources", sources.join(","));
    return req<{
      songs: CloudSong[];
      collections: CloudCollection[];
      pagination: { page: number; total_pages: number; total: number };
    }>(`/api/cloud-music/search?${qs.toString()}`);
  },
  cloudMusicToplists: (sources?: string[]) => {
    const qs = new URLSearchParams();
    if (sources && sources.length > 0) qs.set("sources", sources.join(","));
    return req<CloudTopList[]>(`/api/cloud-music/toplists?${qs.toString()}`);
  },
  cloudMusicToplistSongs: (source: string, toplistId: string) =>
    req<CloudSong[]>(
      `/api/cloud-music/toplists/songs?source=${encodeURIComponent(source)}&toplist_id=${encodeURIComponent(toplistId)}`
    ),
  cloudMusicCollectionSongs: (source: string, id: string, kind: "playlist" | "album" = "playlist", page = 1) =>
    req<CloudSong[]>(
      `/api/cloud-music/collections/songs?source=${encodeURIComponent(source)}&id=${encodeURIComponent(id)}&kind=${kind}&page=${page}`
    ),
  cloudMusicStreamUrl: (song: Pick<CloudSong, "id" | "source" | "name" | "artist" | "album" | "extra">) => {
    const qs = new URLSearchParams({
      id: song.id,
      source: song.source,
      name: song.name || "",
      artist: song.artist || "",
      album: song.album || "",
      extra: JSON.stringify(song.extra || {}),
    });
    return `/api/cloud-music/stream?${qs.toString()}`;
  },
  cloudMusicBatchDownload: (payload: {
    songs: CloudSong[];
    series_id?: number | null;
    album_id?: number | null;
    new_series_title?: string;
    season_label?: string;
    new_album_title?: string;
    auto_group_by_artist?: boolean;
    category?: "music" | "story" | "english" | "podcast";
    age_stage?: AgeStage;
  }) =>
    req<{ job_id: number; album_id: number; album_title: string; total_requested: number; status: string }>(
      "/api/cloud-music/batch-download",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),
  cloudMusicJobs: (limit = 15) => req<DownloadJob[]>(`/api/cloud-music/jobs?limit=${limit}`),
};
