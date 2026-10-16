import { appState, updateApp } from "./app.js";
import { resetScanSettings } from "./scan.js";
let channelsText = new URLSearchParams(location.search).get("mockFresh") === "1" ? "" : [
  "https://www.facebook.com/BepNhaMinh", "https://www.facebook.com/SongKhoeMoiNgay", "https://www.facebook.com/YTuongNoiDung"
].join("\n");
let loginUntil = 0, loginNotice = null;
const providers = [
  { label: "OpenAI", url: "https://api.openai.com/v1" },
  { label: "Anthropic (Claude)", url: "https://api.anthropic.com/v1/" },
  { label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { label: "Khác (OpenAI-compatible, tự nhập)", url: "" }
];
let llm = { base_url: "", model: "", saved_mask: "", enabled: false, provider: "OpenAI" };
const lines = (text) => text.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
function problems(text) {
  return lines(text).flatMap((line) => {
    try {
      const url = new URL(line);
      if (!/^https?:$/.test(url.protocol) || !/(^|\.)facebook\.com$/i.test(url.hostname) || !url.pathname.replace(/\//g, "") || /\/(groups|watch|reel|videos)\//i.test(url.pathname)) throw Error();
    } catch { return [`Link page Facebook không hợp lệ: ${line}`]; }
    return [];
  });
}
function finishLogin() {
  if (loginUntil && Date.now() >= loginUntil) {
    loginUntil = 0;
    appState.logging_in = false;
    appState.guide.fb_ready = true;
    loginNotice = "Đã đăng nhập Facebook và lưu phiên.";
    updateApp();
  }
}
const busy = () => ({ ok: false, error: "Ứng dụng đang bận. Hãy chờ quét hoặc đăng nhập hoàn tất." });
export default {
  get_llm: async () => ({ ok: true, providers, storage_secure: true, recommended_models: {}, ...llm }),
  connect_llm: async (key, url) => {
    if (!key && !llm.saved_mask) return { ok: false, error: "Vui lòng nhập API key." };
    const id = url.includes("anthropic") ? "claude-haiku-4-5" : "gpt-4.1-mini";
    return { ok: true, models: [{ id, label: id }], default_id: id, recommended_id: id };
  },
  save_llm: async (key, base_url, model) => {
    if (appState.busy) return busy();
    llm = { base_url, model, saved_mask: "••••", enabled: true, provider: providers.find(p => p.url.replace(/\/$/, "") === base_url.replace(/\/$/, ""))?.label || providers[3].label };
    return { ok: true, message: "Bản xem thử: đã lưu cấu hình AI." };
  },
  remove_llm: async () => {
    if (appState.busy) return busy();
    llm = { base_url: "", model: "", saved_mask: "", enabled: false, provider: "OpenAI" };
    return { ok: true, message: "Đã xoá key." };
  },
  reset_configuration: async () => {
    if (appState.busy) return busy();
    channelsText = "";
    llm = { base_url: "", model: "", saved_mask: "", enabled: false, provider: "OpenAI" };
    appState.guide.channel_count = 0;
    resetScanSettings();
    updateApp();
    return { ok: true, message: "Đã đặt lại cài đặt và danh sách kênh. Excel và phiên Facebook được giữ nguyên." };
  },
  get_channels: async () => ({ ok: true, text: channelsText, count: lines(channelsText).length, problems: problems(channelsText) }),
  save_channels: async (text) => {
    if (appState.busy) return busy();
    const errors = problems(text);
    if (errors.length) return { ok: false, error: "Sửa các link không hợp lệ trước khi lưu.", problems: errors };
    channelsText = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).join("\n");
    appState.guide.channel_count = lines(channelsText).length;
    updateApp();
    return { ok: true, count: appState.guide.channel_count, message: `Đã lưu ${appState.guide.channel_count} kênh.` };
  },
  start_login: async () => {
    finishLogin();
    if (appState.busy) return busy();
    loginUntil = Date.now() + 3000;
    appState.logging_in = true;
    updateApp();
    setTimeout(finishLogin, 3000);
    return { ok: true };
  },
  get_login_state: async () => {
    finishLogin();
    const notice = loginNotice;
    loginNotice = null;
    return { ok: true, logging_in: Boolean(loginUntil), fb_ready: appState.guide.fb_ready, message: null, notice };
  },
  pick_cookie_file_and_import: async () => {
    if (appState.busy) return busy();
    appState.guide.fb_ready = true;
    updateApp();
    return { ok: true, message: "Bản xem thử: đã nạp phiên Facebook từ cookie mẫu." };
  }
};
