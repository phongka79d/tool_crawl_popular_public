import { el } from "../../components/dom.js";
import { button, card, numberInput, checkbox, radioGroup, alert, expander } from "../../components/index.js";

export function scanOptions(data, ctx, { onStart, isBusy }) {
  const values = structuredClone(data.defaults), root = el("div", "stack");
  const left = card({ title: "Video cần quét" }), right = card({ title: "Ngưỡng viral theo kênh" });
  left.body.classList.add("stack");
  right.body.classList.add("stack");
  const summary = el("p", "scan-summary"), problems = el("div", "stack"), terms = el("div");
  summary.setAttribute("aria-live", "polite");
  let disposed = false, timer, previewId = 0, canStart = false, acting = false;
  const start = button({ label: "Bắt đầu quét", variant: "primary", size: "large", icon: "scan", disabled: true, onClick: () => onStart(options()) });
  start.classList.add("scan-start");
  const dayInput = numberInput({ label: "Số ngày", value: values.days, min: 1, onChange: (value) => {
    values.days = value ?? 0;
    preview();
  } });
  const presets = data.presets.days;
  dayInput.hidden = presets.includes(values.days);
  left.body.append(radioGroup({ label: "Video đăng trong", options: [...presets.map((value) => ({ id: String(value), label: `${value} ngày` })), { id: "custom", label: "Tự nhập" }], value: dayInput.hidden ? String(values.days) : "custom", onChange: (value) => {
    dayInput.hidden = value !== "custom";
    values.days = value === "custom" ? dayInput.value ?? 0 : Number(value);
    preview();
  } }), dayInput);
  const kinds = el("div", "scan-kind-grid");
  for (const item of data.kinds)
    kinds.append(checkbox({ label: item.label, checked: values.video_kinds.includes(item.id), onChange: (checked) => {
      values.video_kinds = checked ? [...values.video_kinds, item.id] : values.video_kinds.filter((id) => id !== item.id);
      preview();
    } }));
  left.body.append(kinds, el("p", "hint", "Chép lời cục bộ bằng faster-whisper small, tiếng Việt. Lần đầu cần tải mô hình; không gửi âm thanh tới dịch vụ chép lời."));
  for (const [name, label, min, step, hint] of [
    ["min_views", "Lượt xem tối thiểu", 0, 1000, "Video phải đạt cả ngưỡng lượt xem và ngưỡng trung vị."],
    ["viral_factor", "Hệ số viral (× trung vị)", 0.1, 0.1, "Ví dụ 3×: lượt xem ít nhất gấp 3 mức trung vị của kênh trong khoảng ngày đã chọn."],
    ["max_per_channel", "Tối đa video mỗi kênh", 1, 1, "Giữ các video đạt ngưỡng có lượt xem cao nhất."]
  ]) right.body.append(numberInput({ label, value: values[name], min, step, thousands: name === "min_views", hint, onChange: (value) => {
    values[name] = value ?? 0;
    preview();
  } }));
  right.body.append(summary, problems);
  root.append(el("div", "scan-options-grid", left, right), terms, start);

  function options() {
    data.defaults = structuredClone(values);
    return structuredClone(values);
  }
  function sync() {
    root.querySelectorAll("input,button,select,textarea").forEach((node) => node.disabled = isBusy() || acting);
    start.disabled = isBusy() || acting || !canStart;
  }
  function preview() {
    clearTimeout(timer);
    canStart = false;
    sync();
    const id = ++previewId;
    timer = setTimeout(async () => {
      const result = await ctx.call("preview_scan", options());
      if (disposed || id !== previewId) return;
      summary.textContent = result.summary || "";
      problems.replaceChildren(...(result.problems || []).map((message) => alert({ variant: "error", message })));
      if (!result.ok) problems.append(alert({ variant: "error", message: result.error }));
      canStart = !!result.ok && !!result.can_start;
      sync();
    }, 250);
  }
  function renderTerms() {
    const notice = el("div", "stack", data.terms.paragraphs.map((text) => el("p", "", text)), el("ul", "", data.terms.bullets.map((text) => el("li", "", text))));
    const link = el("a", "", data.terms.link.label);
    link.href = data.terms.link.url;
    notice.append(link);
    if (data.terms.accepted_at) {
      terms.replaceChildren(expander({ title: "Lưu ý Facebook (đã xác nhận)", body: notice }));
    } else {
      const accept = checkbox({ label: "Tôi đã đọc và tự chịu trách nhiệm", onChange: async (checked) => {
        if (!checked) return;
        acting = true;
        sync();
        const result = await ctx.call("accept_terms");
        if (disposed) return;
        acting = false;
        if (result.ok) {
          data.terms.accepted_at = result.accepted_at;
          renderTerms();
          preview();
        } else {
          accept.value = false;
          ctx.toast(result.error, { variant: "error" });
        }
        sync();
      } });
      notice.append(accept);
      const warning = card({ title: "Lưu ý quan trọng trước khi quét", body: notice });
      warning.classList.add("scan-terms");
      terms.replaceChildren(warning);
    }
  }
  renderTerms();
  preview();
  return { root, sync, preview, destroy() {
    disposed = true;
    ++previewId;
    clearTimeout(timer);
  } };
}
