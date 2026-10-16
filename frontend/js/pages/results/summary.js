import { el } from "../../components/dom.js";
import { alert, barChart, dataTable, expander, metric } from "../../components/index.js";
import { num } from "../../format.js";

export function renderSummary(summary) {
  if (!summary)
    return alert({ message: "Không đọc được thống kê. Bạn vẫn có thể mở file bằng Excel." });
  const body = el("div", "stack", el("div", "results-metrics",
    metric({ label: "Video đã xuất", value: num(summary.total) }),
    metric({ label: "Mới", value: num(summary.new) }),
    metric({ label: "Đã lấy trước", value: num(summary.taken_before) }),
    metric({ label: "Tổng lượt xem", value: num(summary.views_total) })));
  if (!summary.total)
    body.append(alert({ message: "Không có video đạt ngưỡng. Xem tình hình quét bên dưới hoặc điều chỉnh ngưỡng." }));
  if (summary.channels?.length)
    body.append(expander({ title: "Video theo kênh", open: true, body: barChart({ data: summary.channels.map((row) => ({ label: row.name, value: row.count })), horizontal: true, integer: true, height: Math.max(240, summary.channels.length * 34 + 48) }) }));
  if (summary.top?.length)
    body.append(el("section", "stack", el("h3", "", "Top 10 video theo lượt xem"), dataTable({ rows: summary.top, columns: [
      { key: "stt", label: "STT" },
      { key: "channel", label: "Kênh" },
      { key: "transcript", label: "Nội dung thoại", format: (text) => text || "—" },
      { key: "views_text", label: "Lượt xem" },
      { key: "posted", label: "Ngày đăng" },
      { key: "status", label: "Tình trạng" },
      { key: "url", label: "Video", type: "link", format: () => "Mở video" }
    ] })));
  for (const [name, title, variant] of [["scan_lines", "Tình hình quét từng kênh", "info"], ["notes", "Ghi chú", "info"], ["errors", "Lỗi khi quét", "error"]]) {
    if (summary[name]?.length)
      body.append(expander({ title, open: true, body: el("div", "stack", summary[name].map((message) => alert({ variant, message }))) }));
  }
  return body;
}
