import { appState, updateApp } from "./app.js";
import { registerScanResult, resultExists } from "./results.js";
const initial = { days: 14, video_kinds: ["video", "reel"], min_views: 50000, viral_factor: 3, max_per_channel: 10 };
let defaults = structuredClone(initial), acceptedAt = null, session = null;
export function resetScanSettings() { defaults = structuredClone(initial); acceptedAt = null; }
const terms = { paragraphs: ["Công cụ đọc Facebook qua trình duyệt đã đăng nhập (thu thập tự động).", "Điều khoản Facebook hạn chế thu thập tự động khi chưa được phép."], bullets: ["Tài khoản có thể bị yêu cầu xác minh hoặc khóa. Nên dùng tài khoản phụ.", "Chỉ thu thập nội dung bạn được phép truy cập.", "Bạn tự chịu trách nhiệm khi sử dụng công cụ."], link: { label: "Điều khoản Facebook", url: "https://www.facebook.com/terms" } };
function preview(input) {
  const options = { ...defaults, ...input }, problems = [];
  if (!(Number.isInteger(options.days) && options.days >= 1)) problems.push("Số ngày phải lớn hơn 0.");
  if (!options.video_kinds?.length) problems.push("Chọn ít nhất một loại video để quét.");
  else if (options.video_kinds.some((kind) => !["video", "reel"].includes(kind))) problems.push("Loại video không hợp lệ.");
  if (!(options.min_views >= 0)) problems.push("Lượt xem tối thiểu không được âm.");
  if (!(Number.isFinite(options.viral_factor) && options.viral_factor > 0)) problems.push("Hệ số viral phải lớn hơn 0.");
  if (!(Number.isInteger(options.max_per_channel) && options.max_per_channel >= 1)) problems.push("Số video mỗi kênh phải lớn hơn 0.");
  return { ok: true, summary: `Trong ${options.days} ngày: giữ video có lượt xem ≥ ${options.viral_factor}× trung vị của kênh VÀ ≥ ${Number(options.min_views).toLocaleString("vi-VN")}; tối đa ${options.max_per_channel} video/kênh, ưu tiên lượt xem cao nhất.`, problems, can_start: !problems.length && !!acceptedAt && !session?.running };
}
function empty() {
  return { ok: true, running: false, stopping: false, elapsed_s: 0, item_label: "video", overall: 0, stage: null, lanes: [], message: "", channels: [], log: [], log_total: 0, errors: [], result: null, ended_without_result: false };
}
function snapshot(since = 0) {
  if (!session) return empty();
  const s = session;
  let elapsed = (Date.now() - s.started) / 1000;
  if (s.running && (elapsed >= 24 || s.stopping && Date.now() - s.stopAt >= 1000)) {
    s.running = false;
    s.elapsed = Math.min(elapsed, 24);
    s.ended = s.stopping;
  }
  if (!s.running) elapsed = s.elapsed;
  const total = s.count * s.perChannel;
  const scanned = Math.min(s.count, Math.floor(elapsed / (8 / s.count)));
  const done = Math.min(total, Math.max(0, Math.floor((elapsed - 8) / (14 / total))));
  const channels = Array.from({ length: s.count }, (_, i) => {
    const found = i < scanned ? 35 + i * 11 : null, passed = found === null ? null : s.perChannel;
    const transcribed = Math.max(0, Math.min(s.perChannel, done - i * s.perChannel));
    return { name: `Kênh mẫu ${i + 1}`, url: `https://www.facebook.com/page${i + 1}`, found, passed, transcribed,
      status: transcribed === s.perChannel ? "Đã chép lời" : transcribed ? "Đang chép lời" : found === null ? "Chờ quét" : "Chờ chép lời",
      progress: passed === null ? 0 : 0.6 + 0.4 * transcribed / passed };
  });
  const stage = !s.running ? "done" : elapsed < 8 ? "scan" : elapsed < 22 ? "transcribe" : "export";
  const tick = Math.floor(elapsed / 2);
  while (s.tick < tick) {
    s.tick++;
    s.log.push(s.tick < 4 ? "Đang quét Facebook và tính trung vị lượt xem." : s.tick < 11 ? "Đang tải âm thanh và chép lời tiếng Việt cục bộ." : "Đang lọc kịch bản trùng và xuất Excel.");
  }
  if (!s.running && !s.loggedEnd) {
    s.loggedEnd = true;
    s.log.push(s.ended ? "Đã dừng quét." : "Đã xuất Excel.");
  }
  if (!s.running && !s.ended && !s.registered) {
    s.registered = true;
    s.resultName = registerScanResult({ count: total });
  }
  appState.guide.running = s.running;
  updateApp();
  const result = s.resultName && resultExists(s.resultName) ? { name: s.resultName, count: total, elapsed_s: elapsed } : null;
  return { ...empty(), running: s.running, stopping: s.running && s.stopping, elapsed_s: elapsed,
    overall: s.running ? Math.min(0.97, elapsed / 24) : 1, stage, channels,
    lanes: [
      { id: "scan", title: "Quét Facebook", state: scanned === s.count || !s.running ? "done" : "current", fraction: scanned / s.count, label: `${scanned}/${s.count} kênh`, message: scanned === s.count ? "Đã quét xong." : "Đang đọc video và tính trung vị từng kênh." },
      { id: "transcribe", title: "Chép lời", state: !s.running || stage === "export" ? "done" : scanned ? "current" : "pending", fraction: done / total, label: `${done}/${total} video`, message: "Chép lời tiếng Việt bằng mô hình small trên máy." }
    ], message: stage === "export" ? "Đang xuất Excel…" : "", log: s.log.slice(Math.max(0, Number(since) || 0)), log_total: s.log.length,
    result, ended_without_result: !s.running && !result };
}
export default {
  get_scan_options: async () => ({ ok: true, defaults: structuredClone(defaults), kinds: [{ id: "video", label: "Video thường" }, { id: "reel", label: "Reel" }], presets: { days: [7, 14, 30] }, terms: { ...structuredClone(terms), accepted_at: acceptedAt } }),
  preview_scan: async (options) => preview(options),
  accept_terms: async () => ({ ok: true, accepted_at: acceptedAt ??= new Date().toISOString() }),
  start_scan: async (options) => {
    const checked = preview(options);
    if (!checked.can_start) return { ok: false, error: checked.problems[0] || (!acceptedAt ? "Vui lòng xác nhận lưu ý Facebook." : "Một lần quét đang chạy.") };
    if (appState.logging_in || !appState.guide.channel_count) return { ok: false, error: "Hoàn tất danh sách kênh và đăng nhập trước khi quét." };
    defaults = { ...defaults, ...structuredClone(options) };
    session = { started: Date.now(), running: true, stopping: false, tick: 0, count: appState.guide.channel_count, perChannel: Math.min(defaults.max_per_channel, 3), log: ["Bắt đầu lần quét mô phỏng."] };
    appState.guide.running = true;
    updateApp();
    return { ok: true };
  },
  stop_scan: async () => {
    if (session?.running) { session.stopping = true; session.stopAt = Date.now(); }
    return { ok: true };
  },
  get_scan_state: async (since) => snapshot(since)
};
