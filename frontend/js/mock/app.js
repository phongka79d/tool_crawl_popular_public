const query = new URLSearchParams(location.search);
const fresh = query.get("mockFresh") === "1";
export const appState = {
  ok: true,
  browser: { ready: !query.has("mockBrowser"), error: query.get("mockBrowser") === "error" ? "Không thể chuẩn bị trình duyệt Chromium. Kiểm tra mạng và mở lại ứng dụng." : null },
  guide: { channel_count: fresh ? 0 : 3, fb_ready: !fresh, running: false, has_result: false, setup_done: !fresh },
  journey: [], next_step: {}, logging_in: false, busy: false
};
export function updateApp() {
  const g = appState.guide;
  g.setup_done = g.channel_count > 0 && g.fb_ready;
  appState.busy = g.running || appState.logging_in;
  appState.journey = [
    { title: "1 · Kênh & Facebook", state: g.setup_done ? "done" : "current" },
    { title: "2 · Chạy quét", state: g.running ? "current" : g.has_result ? "done" : g.setup_done ? "current" : "pending" },
    { title: "3 · Kết quả", state: g.has_result ? "done" : "pending" }
  ];
  appState.next_step = g.running ? { text: "Đang quét và chép lời. Theo dõi ở tab Chạy quét.", page: "scan" } : !g.setup_done ? { text: "Lưu danh sách kênh và đăng nhập Facebook trước khi quét.", page: "settings" } : g.has_result ? { text: "Đã có Excel. Xem thống kê và mở file ở Kết quả.", page: "results" } : { text: "Chọn ngưỡng viral và bắt đầu quét.", page: "scan" };
}
updateApp();
const records = ["2026-10-16 09:00:00  INFO     Đã chuẩn bị trình duyệt quét.", "2026-10-16 09:00:01  WARNING  Một kênh phản hồi chậm; hãy kiểm tra kết nối nếu kéo dài."];
export default {
  get_app_state: async () => { updateApp(); return structuredClone(appState); },
  get_logs: async (session = "current", problems_only = true) => ({ ok: true,
    sessions: [{ id: "current", label: "Lần mở này" }, { id: "previous", label: "Lần mở trước" }],
    session: session === "previous" ? "previous" : "current", path: "data/app.log",
    records: records.filter((line) => !problems_only || line.includes("WARNING")).slice().reverse() }),
  open_log_file: async () => ({ ok: true, message: "Bản xem thử: nhật ký sẽ mở trong ứng dụng trên máy." }),
  open_url: async (url) => /^https?:\/\/[^/]+/i.test(url) ? { ok: true, message: "Bản xem thử không mở liên kết bên ngoài." } : { ok: false, error: "Chỉ hỗ trợ liên kết http hoặc https hợp lệ." }
};
