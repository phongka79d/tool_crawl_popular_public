import { el } from "../../components/dom.js";
import { button, card, badge, textarea, alert, expander, select, textInput } from "../../components/index.js";
/** Settings retain unsaved form values while shell state refreshes. */
export function mount(target, ctx) {
  if (!document.getElementById("settings-styles")) {
    const link = document.createElement("link");
    link.id = "settings-styles";
    link.rel = "stylesheet";
    link.href = new URL("../../../css/pages/settings.css", import.meta.url).href;
    document.head.append(link);
  }
  let disposed = false, pending = false, loginBusy = false, loginTimer = null, loginPolling = false, loginState = null;
  let fbReady = Boolean((ctx.store.get().app || ctx.store.get().appState)?.guide?.fb_ready);
  const root = el("div", "settings-page stack"), controls = el("fieldset", "settings-controls stack");
  const channels = el("div"), facebook = el("div"), resetErrors = el("div");
  const busyHint = el("div");
  busyHint.hidden = true;
  controls.append(el("section", "stack", el("h2", "", "Kênh & Facebook"), el("div", "settings-connections", channels, facebook)));
  const llmArea = el("div");
  controls.append(llmArea);
  const resetButton = button({ label: "Đặt lại toàn bộ cấu hình", variant: "danger", onClick: async () => {
    if (isBusy())
      return;
    const confirmed = await ctx.confirm("Khôi phục cài đặt mặc định, xoá key AI và danh sách kênh? Excel, cache và phiên Facebook được giữ nguyên.", { danger: true, title: "Đặt lại cấu hình", confirmLabel: "Đặt lại cấu hình" });
    if (!confirmed || isBusy() || disposed)
      return;
    await run(resetButton, resetErrors, async () => {
      const result = await ctx.call("reset_configuration");
      if (result.ok && !disposed) {
        ctx.toast(result.message, { variant: "success" });
        await ctx.refreshApp();
        await loadAll();
      }
      return result;
    });
  } });
  controls.append(expander({ title: "Đặt lại cấu hình", body: el("div", "stack", el("p", "hint", "Khôi phục lựa chọn quét mặc định, xoá key AI và danh sách kênh. Không xóa Excel, cache hay phiên Facebook."), el("div", "row", resetButton), resetErrors) }));
  root.append(busyHint, controls);
  target.replaceChildren(root);
  function app() {
    return ctx.store.get().app || ctx.store.get().appState || {};
  }
  function isBusy() {
    return pending || loginBusy || Boolean(app().busy || ctx.store.get().busy);
  }
  function sync() {
    if (disposed)
      return;
    controls.disabled = isBusy();
    busyHint.replaceChildren();
    if (app().busy && !loginBusy)
      busyHint.append(alert({ message: "Ứng dụng đang quét hoặc đăng nhập. Bạn có thể xem cấu hình; hãy chờ hoàn tất trước khi thay đổi." }));
    busyHint.hidden = !busyHint.hasChildNodes();
    if (app().logging_in && !loginBusy) {
      loginBusy = true;
      scheduleLogin();
      renderFacebook();
      controls.disabled = true;
    }
    if (!loginBusy && fbReady !== Boolean(app().guide?.fb_ready)) {
      fbReady = Boolean(app().guide?.fb_ready);
      renderFacebook();
    }
  }
  async function run(control, errorArea, task) {
    if (disposed || isBusy())
      return;
    pending = true;
    control.setLoading(true);
    errorArea.replaceChildren();
    sync();
    try {
      const result = await task();
      if (!disposed && result && !result.ok)
        errorArea.replaceChildren(alert({ variant: "error", message: result.problems?.length ? "Chưa lưu. Sửa các dòng sau:" : result.error || "Không thể hoàn tất thao tác.", list: result.problems || [] }));
      return result;
    } catch {
      if (!disposed)
        errorArea.replaceChildren(alert({ variant: "error", message: "Không thể hoàn tất thao tác. Kiểm tra kết nối và thử lại." }));
    } finally {
      pending = false;
      control.setLoading(false);
      sync();
    }
  }
  async function loadChannels() {
    const result = await ctx.call("get_channels");
    if (disposed)
      return;
    if (!result.ok) {
      channels.replaceChildren(alert({ variant: "error", message: result.error }));
      return;
    }
    const field = textarea({ label: "Danh sách link kênh", value: result.text, rows: 8, placeholder: "https://www.facebook.com/ten-page" }), errors = el("div");
    field.classList.add("settings-channel-editor");
    const save = button({ label: "Lưu danh sách kênh", variant: "primary", onClick: () => run(save, errors, async () => {
      const saved = await ctx.call("save_channels", field.value);
      if (saved.ok && !disposed) {
        ctx.toast(saved.message, { variant: "success" });
        await ctx.refreshApp();
        await loadChannels();
      }
      return saved;
    }) });
    const body = el("div", "stack", el("p", "hint", "Mỗi dòng là link trang chính của một page (fanpage), ví dụ https://www.facebook.com/ten-page. Không hỗ trợ nhóm (group). Dòng bắt đầu bằng # là ghi chú."));
    if (result.problems?.length)
      body.append(alert({ variant: "warning", message: "Các link sau sẽ bị bỏ qua khi quét:", list: result.problems }));
    body.append(field, el("p", "hint", `Đang lưu ${result.count} kênh.`), el("div", "row", save), errors);
    channels.replaceChildren(card({ title: "Kênh cần quét", body }));
  }
  function renderFacebook() {
    if (disposed)
      return;
    const errors = el("div"), body = el("div", "stack", badge({ label: fbReady ? "Đã đăng nhập" : "Chưa đăng nhập", state: fbReady ? "success" : "warning" }), el("p", "hint", "Dùng tài khoản Facebook phụ để app quét được video. Cửa sổ trình duyệt sẽ mở để bạn tự đăng nhập; phiên được lưu cho lần quét sau."), el("p", "hint", "Không chia sẻ thư mục profile/ và file data/fb_cookies.txt: chúng chứa phiên đăng nhập Facebook của bạn."));
    const login = button({ label: fbReady ? "Đăng nhập lại" : "Đăng nhập Facebook", variant: fbReady ? "secondary" : "primary", onClick: () => run(login, errors, async () => {
      const result = await ctx.call("start_login");
      if (result.ok && !disposed) {
        loginBusy = true;
        loginState = null;
        renderFacebook();
        scheduleLogin();
        await ctx.refreshApp();
      }
      return result;
    }) });
    body.append(el("div", "row", login));
    if (loginBusy)
      body.append(alert({ message: "Đang chờ đăng nhập trong cửa sổ Facebook… Hoàn tất các bước xác minh nếu có." }));
    if (loginState?.message)
      body.append(alert({ variant: "error", message: loginState.message }));
    const cookie = button({ label: "Chọn file cookie…", onClick: () => run(cookie, errors, async () => {
      const result = await ctx.call("pick_cookie_file_and_import");
      if (result.ok && !result.cancelled && !disposed) {
        ctx.toast(result.message, { variant: "success" });
        await ctx.refreshApp();
        fbReady = Boolean(app().guide?.fb_ready);
        renderFacebook();
      }
      return result;
    }) });
    body.append(expander({ title: "Không đăng nhập được? Nạp file cookie", body: el("div", "stack", el("p", "hint", "Đăng nhập tài khoản Facebook phụ trên trình duyệt, dùng Cookie-Editor để xuất cookie của facebook.com ra file JSON hoặc TXT rồi chọn file ở đây. Không chia sẻ file cookie cho người khác."), el("div", "row", cookie)) }), errors);
    facebook.replaceChildren(card({ title: "Đăng nhập Facebook", body }));
  }
  function scheduleLogin() {
    clearTimeout(loginTimer);
    if (!disposed)
      loginTimer = setTimeout(pollLogin, 1000);
  }
  async function pollLogin() {
    if (disposed || loginPolling)
      return;
    loginPolling = true;
    try {
      const result = await ctx.call("get_login_state");
      if (disposed)
        return;
      if (!result.ok) {
        loginState = { message: result.error };
        renderFacebook();
        if (loginBusy)
          scheduleLogin();
        return;
      }
      loginState = result;
      loginBusy = Boolean(result.logging_in);
      fbReady = Boolean(result.fb_ready);
      renderFacebook();
      if (result.notice)
        ctx.toast(result.notice, { variant: "success" });
      if (loginBusy)
        scheduleLogin();
      else
        await ctx.refreshApp();
      sync();
    } finally {
      loginPolling = false;
    }
  }
  async function loadLlm() {
    const saved = await ctx.call("get_llm");
    if (disposed) return;
    if (!saved.ok) {
      llmArea.replaceChildren(alert({ variant: "error", message: saved.error }));
      return;
    }
    const errors = el("div"), modelsArea = el("div", "stack");
    let connected = false;
    const invalidate = () => { connected = false; modelsArea.replaceChildren(); };
    const endpoint = textInput({ label: "Endpoint HTTPS", value: saved.base_url, onChange: invalidate });
    const provider = select({ label: "Nhà cung cấp", options: saved.providers.map(p => ({ id: p.label, label: p.label })), value: saved.provider,
      onChange: () => { endpoint.hidden = !!saved.providers.find(p => p.label === provider.value)?.url; invalidate(); } });
    endpoint.hidden = !!saved.providers.find(p => p.label === provider.value)?.url;
    const key = textInput({ label: "API key", type: "password", hint: saved.saved_mask ? `Đã lưu ${saved.saved_mask}. Để trống để dùng key đã lưu.` : "Key chỉ được lưu sau khi kiểm tra thành công.", onChange: invalidate });
    const url = () => saved.providers.find(p => p.label === provider.value)?.url || endpoint.value.trim();
    const connect = button({ label: "Kết nối", onClick: () => run(connect, errors, async () => {
      const result = await ctx.call("connect_llm", key.value, url());
      if (result.ok && !disposed) {
        connected = true;
        const model = select({ label: "Model", options: result.models.map(m => ({ id: m.id, label: m.label + (m.id === result.recommended_id ? " · Đề xuất" : "") })), value: result.default_id });
        const save = button({ label: "Kiểm tra và lưu", variant: "primary", disabled: !saved.storage_secure, onClick: () => run(save, errors, async () => {
          if (!connected) return { ok: false, error: "Kết nối lại trước khi lưu." };
          const checked = await ctx.call("save_llm", key.value, url(), model.value);
          if (checked.ok && !disposed) { key.value = ""; ctx.toast(checked.message, { variant: "success" }); await loadLlm(); }
          return checked;
        }) });
        modelsArea.replaceChildren(model, el("div", "row", save));
      }
      return result;
    }) });
    const remove = button({ label: "Xoá key", variant: "danger", onClick: () => run(remove, errors, async () => {
      const result = await ctx.call("remove_llm");
      if (result.ok && !disposed) { key.value = ""; ctx.toast(result.message, { variant: "success" }); await loadLlm(); }
      return result;
    }) });
    const body = el("div", "stack",
      el("p", "hint", "Không bắt buộc. Có key, app nhờ AI sửa từ nghe nhầm và thêm dấu câu, giữ nguyên lời người nói. Lời thoại được gửi tới nhà cung cấp; nhà cung cấp có thể tính phí theo lượt dùng."),
      badge({ label: saved.enabled ? `Đã bật · ${saved.model}` : "Chưa bật — không bắt buộc", state: saved.enabled ? "success" : "neutral" }),
      provider, endpoint, key, el("div", "row", connect, remove), modelsArea, errors);
    if (!saved.storage_secure) body.prepend(alert({ variant: "warning", message: "Windows Credential Manager chưa khả dụng hoặc không an toàn. App từ chối lưu key; vẫn chép lời trên máy bình thường." }));
    llmArea.replaceChildren(card({ title: "Cải thiện lời thoại bằng AI (không bắt buộc)", body }));
  }
  async function loadAll() {
    await loadChannels();
    await loadLlm();
    if (!disposed) {
      renderFacebook();
      sync();
    }
  }
  const unsubscribe = ctx.store.subscribe(sync);
  sync();
  loadAll();
  pollLogin();
  return () => {
    disposed = true;
    clearTimeout(loginTimer);
    unsubscribe();
  };
}
