import AppKit

// 可聚焦面板
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

// 穿透视图: 空白区域鼠标穿透，内容区域可点击
final class KeeperContentView: NSVisualEffectView {
    var contentRect: NSRect = .zero
    override func hitTest(_ point: NSPoint) -> NSView? {
        let local = convert(point, from: nil)
        return contentRect.contains(local) ? self : nil
    }
}

// CodingKeeperBar — 双屏模式的顶部状态条:
//   小横幅(常驻) → 空闲: 暗色图标; 有任务: 🔥 客户端×数量 (紧凑一行)
//   大横幅(闪现) → 收到新任务时自动展开 ~4s 显示项目+任务, 然后收回小横幅
//   点击小横幅   → 常驻明细面板 (所有项目 + 队列); 点别处 resignKey 收起

final class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: KeyablePanel!
    var contentView: KeeperContentView!
    var bannerText: NSTextField!
    var detailText: NSTextView!
    var flashTitle: NSTextField!
    var flashBody: NSTextField!
    var timer: Timer?
    var collapseTimer: Timer?
    var userExpanded = false
    var flashUntil = Date.distantPast
    var lastRunningKeys = Set<String>()
    var notifyPanel: NSPanel!
    var notifyTitle: NSTextField!
    var notifyBody: NSTextField!
    var notifyTimer: Timer?
    var lastNotifyKey = ""

    let hSmall: CGFloat = 20      // 小横幅: 图标 / 客户端计数
    let hFlash: CGFloat = 44      // 大横幅闪现: 收到任务
    let hExpanded: CGFloat = 100  // 点击明细
    let barW: CGFloat = 480
    let freshWindow: TimeInterval = 120   // status.json 心跳视为存活的窗口

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let screen = NSScreen.screens[0].frame
        let bx = (screen.width - barW) / 2

        panel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.maxY - hSmall,
                                                 width: barW, height: hSmall),
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.hasShadow = false

        contentView = KeeperContentView(frame: NSRect(x: 0, y: 0, width: barW, height: hSmall))
        contentView.material = .hudWindow
        contentView.state = .active
        contentView.wantsLayer = true
        contentView.layer?.cornerRadius = 0
        contentView.layer?.backgroundColor = NSColor.systemGray.withAlphaComponent(0.25).cgColor
        contentView.autoresizingMask = [.width]

        bannerText = NSTextField(labelWithString: "⚙︎")
        bannerText.font = NSFont.systemFont(ofSize: 12, weight: .medium)
        bannerText.textColor = .secondaryLabelColor
        bannerText.lineBreakMode = .byTruncatingTail
        bannerText.frame = NSRect(x: 10, y: 3, width: barW - 20, height: hSmall - 6)
        bannerText.autoresizingMask = [.width]
        contentView.addSubview(bannerText)

        // 大横幅闪现: 标题行 + 任务文本行
        flashTitle = NSTextField(labelWithString: "")
        flashTitle.font = NSFont.systemFont(ofSize: 12, weight: .semibold)
        flashTitle.textColor = NSColor.white
        flashTitle.lineBreakMode = .byTruncatingTail
        flashTitle.frame = NSRect(x: 10, y: hFlash - 20, width: barW - 20, height: 16)
        flashTitle.autoresizingMask = [.width]
        flashTitle.isHidden = true
        contentView.addSubview(flashTitle)

        flashBody = NSTextField(labelWithString: "")
        flashBody.font = NSFont.systemFont(ofSize: 11)
        flashBody.textColor = .secondaryLabelColor
        flashBody.lineBreakMode = .byTruncatingTail
        flashBody.frame = NSRect(x: 10, y: 4, width: barW - 20, height: 15)
        flashBody.autoresizingMask = [.width]
        flashBody.isHidden = true
        contentView.addSubview(flashBody)

        // 详情区域
        detailText = NSTextView(frame: NSRect(x: 10, y: 6, width: barW - 20, height: hExpanded - hSmall - 10))
        detailText.font = NSFont.systemFont(ofSize: 11)
        detailText.textColor = NSColor.white
        detailText.backgroundColor = .clear
        detailText.isEditable = false
        detailText.autoresizingMask = [.width]
        detailText.isHidden = true
        contentView.addSubview(detailText)

        // 点击内容区域切换展开
        let click = NSClickGestureRecognizer(target: self, action: #selector(toggleExpand))
        contentView.addGestureRecognizer(click)
        contentView.contentRect = NSRect(x: 0, y: 0, width: barW, height: hFlash)

        panel.contentView = contentView

        // 失焦收起
        NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification,
                                               object: panel, queue: .main) { [weak self] _ in
            guard let self = self, self.userExpanded else { return }
            self.userExpanded = false
            self.refresh()
        }

        // 通知卡片
        let nW: CGFloat = 380, nH: CGFloat = 64
        notifyPanel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.maxY - hFlash - nH - 4,
                                                       width: nW, height: nH),
                                   styleMask: [.borderless, .nonactivatingPanel],
                                   backing: .buffered, defer: false)
        notifyPanel.isOpaque = false
        notifyPanel.backgroundColor = .clear
        notifyPanel.level = .floating
        notifyPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

        notifyTitle = NSTextField(labelWithString: "")
        notifyTitle.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        notifyTitle.textColor = NSColor.white
        notifyTitle.frame = NSRect(x: 14, y: nH - 26, width: nW - 28, height: 20)

        notifyBody = NSTextField(labelWithString: "")
        notifyBody.font = NSFont.systemFont(ofSize: 12)
        notifyBody.textColor = .secondaryLabelColor
        notifyBody.frame = NSRect(x: 14, y: 8, width: nW - 28, height: nH - 36)

        let nbg = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: nW, height: nH))
        nbg.material = .hudWindow
        nbg.state = .active
        nbg.wantsLayer = true
        nbg.layer?.cornerRadius = 10
        nbg.addSubview(notifyTitle)
        nbg.addSubview(notifyBody)

        let closeBtn = NSButton(title: "✕", target: self, action: #selector(dismissNotify))
        closeBtn.isBordered = false
        closeBtn.frame = NSRect(x: nW - 28, y: nH - 24, width: 20, height: 18)
        nbg.addSubview(closeBtn)
        notifyPanel.contentView = nbg

        refresh()
        Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in self.refresh() }
    }

    @objc func toggleExpand() {
        userExpanded.toggle()
        refresh()
    }

    @objc func dismissNotify() { notifyPanel.orderOut(nil) }

    func registry() -> [String] {
        let reg = NSHomeDirectory() + "/.codingkeeper/projects"
        guard let s = try? String(contentsOfFile: reg, encoding: .utf8) else { return [] }
        return s.split(separator: "\n").map(String.init).filter {
            FileManager.default.fileExists(atPath: $0)
        }
    }

    struct ProjStatus {
        var name = ""
        var task = ""
        var tool = ""
        var active = false
        var parked = false
        var running = false   // active 且存活 (loop.pid 活着 或 心跳新鲜)
    }

    func readStatus(_ proj: String) -> ProjStatus {
        var st = ProjStatus()
        st.name = proj.split(separator: "/").last.map(String.init) ?? proj
        let kd = proj + "/.codingkeeper"
        var ts: TimeInterval = 0
        if let data = FileManager.default.contents(atPath: kd + "/status.json"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            st.task = obj["task"] as? String ?? ""
            st.tool = obj["tool"] as? String ?? ""
            st.active = obj["active"] as? Bool ?? false
            ts = obj["ts"] as? TimeInterval ?? 0
        }
        let pidAlive = pidAlive(kd + "/loop.pid")
        let fresh = Date().timeIntervalSince1970 - ts < freshWindow
        st.parked = FileManager.default.fileExists(atPath: kd + "/loop.halt")
        st.running = st.active && !st.parked && (pidAlive || fresh)
        return st
    }

    func pidAlive(_ f: String) -> Bool {
        guard let s = try? String(contentsOfFile: f, encoding: .utf8),
              let pid = Int32(s.trimmingCharacters(in: .whitespacesAndNewlines)) else { return false }
        return kill(pid, 0) == 0
    }

    func refresh() {
        let projects = registry()
        var running: [ProjStatus] = []
        var attention: [(String, String)] = []   // 需要人类协助/决策的项目 (常驻)
        var events: [(String, String)] = []
        var detail: [String] = []
        var flashCandidate: (String, String)?

        // 收到新任务检测: (项目|任务) 键不在上一轮的运行集合里 → 闪现大横幅
        var nowRunningKeys = Set<String>()
        for proj in projects {
            let st = readStatus(proj)
            if st.parked {
                // parked 是监督器状态 (自动循环停机待复燃), 不是任务状态 —
                // 文案与任务态 (▶️/✅/⛔) 明确区分
                events.append(("⏸ \(st.name) 自动循环已暂停", "加任务到 queue.md 或 rm loop.halt 复燃"))
                attention.append((st.name, "自动循环已暂停"))
            } else if st.task.hasPrefix("⛔") {
                // 不可自动续跑的停止: 常驻警示到人处理为止
                attention.append((st.name, String(st.task.dropFirst("⛔ codex 停了: ".count)).trimmingCharacters(in: .whitespaces)))
            }
            if st.running {
                running.append(st)
                let key = "\(st.name)|\(st.task)"
                nowRunningKeys.insert(key)
                if !lastRunningKeys.contains(key) {
                    flashCandidate = ("▶️ \(st.tool.isEmpty ? st.name : st.tool) · \(st.name)", st.task)
                }
                detail.append("🔥 [\(st.tool)] \(st.name): \(st.task)")
            } else if !st.task.isEmpty {
                detail.append("·  [\(st.tool)] \(st.name): \(st.task)")
            }
        }
        lastRunningKeys = nowRunningKeys
        detailLines = detail

        // 收到新任务 → 置闪现状态 (4s 后由 collapseTimer 收回小横幅)
        if let (title, body) = flashCandidate {
            flashCandidateTitle = title
            flashCandidateText = body
            flashUntil = Date().addingTimeInterval(4.0)
        }

        // 各客户端运行计数
        var counts: [String: Int] = [:]
        for st in running { counts[st.tool.isEmpty ? "codex" : st.tool, default: 0] += 1 }
        let countText = counts.sorted { $0.key < $1.key }
            .map { "\($0.key)×\($0.value)" }
            .joined(separator: " · ")

        DispatchQueue.main.async {
            let screen = NSScreen.screens[0].frame
            let bx = (screen.width - self.barW) / 2
            let now = Date()
            let flashing = now < self.flashUntil && self.flashCandidateText != nil

            let h: CGFloat
            if self.userExpanded {
                h = self.hExpanded
            } else if flashing {
                h = self.hFlash
            } else {
                h = self.hSmall
            }

            if flashing {
                self.flashTitle.stringValue = self.flashCandidateTitle ?? ""
                self.flashBody.stringValue = self.flashCandidateText ?? ""
                self.flashTitle.isHidden = false
                self.flashBody.isHidden = false
                self.bannerText.isHidden = true
            } else {
                self.flashTitle.isHidden = true
                self.flashBody.isHidden = true
                self.bannerText.isHidden = false
                var parts: [String] = []
                if !running.isEmpty { parts.append("🔥 " + countText) }
                for (name, reason) in attention {
                    parts.append("⚠️ \(name): \(reason)")
                }
                if parts.isEmpty {
                    self.bannerText.stringValue = "⚙︎"
                    self.bannerText.textColor = .secondaryLabelColor
                } else {
                    self.bannerText.stringValue = parts.joined(separator: "  ·  ")
                    self.bannerText.textColor = .white
                }
            }

            self.detailText.string = self.detailLines.joined(separator: "\n")
            self.detailText.isHidden = !self.userExpanded

            // 背景色: 闪现蓝 / 运行绿 / 空闲灰
            if self.userExpanded {
                self.contentView.layer?.backgroundColor = NSColor.systemGray.withAlphaComponent(0.22).cgColor
            } else if flashing {
                self.contentView.layer?.backgroundColor = NSColor.systemBlue.withAlphaComponent(0.35).cgColor
            } else if !attention.isEmpty {
                self.contentView.layer?.backgroundColor = NSColor.systemOrange.withAlphaComponent(0.32).cgColor
            } else if !running.isEmpty {
                self.contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.18).cgColor
            } else {
                self.contentView.layer?.backgroundColor = NSColor.systemGray.withAlphaComponent(0.25).cgColor
            }

            // 位置: 贴在屏幕最顶端
            let y = screen.maxY - h
            self.contentView.contentRect = NSRect(x: 0, y: 0, width: self.barW, height: h)
            self.panel.setFrame(NSRect(x: bx, y: y, width: self.barW, height: h),
                                display: true, animate: true)
            self.panel.orderFrontRegardless()

            // 闪现到期 → 收回小横幅
            if now < self.flashUntil && self.collapseTimer == nil {
                let remain = self.flashUntil.timeIntervalSince(now) + 0.1
                self.collapseTimer = Timer.scheduledTimer(withTimeInterval: remain, repeats: false) { _ in
                    self.collapseTimer = nil
                    self.refresh()
                }
            }
        }

        // 停靠通知
        if let (title, body) = events.last {
            let key = title + body
            if key != lastNotifyKey {
                lastNotifyKey = key
                DispatchQueue.main.async {
                    self.notifyTitle.stringValue = title
                    self.notifyBody.stringValue = body
                    self.notifyPanel.orderFrontRegardless()
                    self.notifyTimer?.invalidate()
                    self.notifyTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { _ in
                        self.notifyPanel.orderOut(nil)
                    }
                }
            }
        }
    }

    var flashCandidateTitle: String?
    var flashCandidateText: String?
    var detailLines: [String] = []
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
