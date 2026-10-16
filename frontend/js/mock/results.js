import { appState, updateApp } from "./app.js";
const query = new URLSearchParams(location.search);
const folder = "C:\\Video Công Thức\\output";
const files = query.get("mockResults") === "empty" ? [] : [
  { name: "2026-10-15.xlsx", modified: "15/10/2026 09:30", modified_ts: 1792031400, size_text: "86 KB" },
  { name: "2026-10-14.xlsx", modified: "14/10/2026 16:00", modified_ts: 1791968400, size_text: "18 KB" }
];
function sampleSummary(total) {
  const names = ["Bếp Nhà Mình", "Sống Khỏe Mỗi Ngày", "Ý Tưởng Nội Dung"];
  const rows = Array.from({ length: total }, (_, i) => ({
    stt: i + 1, topic: "", transcript: `Nội dung thoại mẫu ${i + 1}: những thói quen nhỏ giúp chúng ta sống tốt hơn mỗi ngày.`,
    channel: names[i % names.length], views: Math.round(1260000 / (1 + i * 0.42)),
    views_text: `${Math.round(1260 / (1 + i * 0.42))} nghìn`, posted: "12/10/2026",
    url: `https://www.facebook.com/watch/?v=${100000 + i}`, status: i < Math.ceil(total * 0.75) ? "Mới" : "Đã lấy ngày 09/10"
  }));
  return {
    total, new: Math.ceil(total * 0.75), taken_before: total - Math.ceil(total * 0.75),
    views_total: rows.reduce((sum, row) => sum + row.views, 0),
    channels: names.map((name) => ({ name, count: rows.filter((row) => row.channel === name).length })).filter((row) => row.count).sort((a, b) => b.count - a.count),
    top: rows.slice(0, 10),
    scan_lines: names.map((name, i) => `${name} (facebook): quét 35 video, 20 video trong 14 ngày, mức thường 20 nghìn view, lấy ${rows.filter((row) => row.channel === name).length} video viral (ngưỡng ≥ x3 và ≥ 50 nghìn)`),
    notes: ["Bỏ qua (không có lời nói): https://www.facebook.com/watch/?v=999999"], errors: []
  };
}
const summaries = { "2026-10-15.xlsx": sampleSummary(12), "2026-10-14.xlsx": sampleSummary(0) };
export const resultExists = (name) => files.some((file) => file.name === name);
function syncResults() { appState.guide.has_result = files.length > 0; updateApp(); }
syncResults();
export function registerScanResult({ count }) {
  const now = new Date(), base = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  let name = `${base}.xlsx`, attempt = 2;
  while (resultExists(name)) name = `${base} (lần ${attempt++}).xlsx`;
  files.unshift({ name, modified: now.toLocaleString("vi-VN"), modified_ts: now.getTime() / 1000, size_text: "86 KB" });
  summaries[name] = sampleSummary(count);
  syncResults();
  return name;
}
const missing = () => ({ ok: false, error: "Không tìm thấy file Excel đã chọn." });
export default {
  list_results: async () => ({ ok: true, folder, files: structuredClone(files) }),
  get_result_summary: async (name) => resultExists(name) ? { ok: true, summary: structuredClone(summaries[name]) } : missing(),
  delete_result: async (name) => {
    const index = files.findIndex((file) => file.name === name);
    if (index < 0) return missing();
    files.splice(index, 1);
    delete summaries[name];
    syncResults();
    return { ok: true, message: `Đã xóa file ${name}.` };
  },
  open_result: async (name) => resultExists(name) ? { ok: true, message: "Bản xem thử: Excel sẽ mở trong ứng dụng trên máy." } : missing(),
  open_output_folder: async () => ({ ok: true, message: "Bản xem thử: thư mục kết quả sẽ mở trong ứng dụng trên máy." }),
  save_result_as: async (name) => !resultExists(name) ? missing() : query.get("mockSaveCancelled") === "1" ? { ok: true, cancelled: true } : { ok: true, message: "Bản xem thử: đã mô phỏng lưu bản sao Excel." }
};
