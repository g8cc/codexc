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

// CodingKeeperBar — 三态:
//   空闲   → 3px 绿线贴在屏幕顶边（穿透不挡操作）
//   燃烧中 → 自动弹出到 22px 显示当前任务
//   点击   → 展开到 ~100px 显示所有项目明细
//   点别处 → resignKey 自动收起

final class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: KeyablePanel!
    var contentView: KeeperContentView!
    var bannerText: NSTextField!
    var detailText: NSTextView!
    var timer: Timer?
    var userExpanded = false
    var notifyPanel: NSPanel!
    var notifyTitle: NSTextField!
    var notifyBody: NSTextField!
    var notifyTimer: Timer?
    var lastNotifyKey = ""

    let hIdle: CGFloat = 3
    let hBurning: CGFloat = 22
    let hExpanded: CGFloat = 100
    let barW: CGFloat = 480

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let screen = NSScreen.screens[0].frame
        let bx = (screen.width - barW) / 2

        panel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.maxY - hIdle,
                                                 width: barW, height: hIdle),
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.hasShadow = false

        contentView = KeeperContentView(frame: NSRect(x: 0, y: 0, width: barW, height: hIdle))
        contentView.material = .hudWindow
        contentView.state = .active
        contentView.wantsLayer = true
        contentView.layer?.cornerRadius = 0
        contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.3).cgColor
        contentView.autoresizingMask = [.width]

        bannerText = NSTextField(labelWithString: "")
        bannerText.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        bannerText.textColor = NSColor.white
        bannerText.lineBreakMode = .byTruncatingTail
        bannerText.frame = NSRect(x: 10, y: 4, width: barW - 20, height: hBurning - 8)
        bannerText.autoresizingMask = [.width]
        bannerText.isHidden = true   // 初始隐藏
        contentView.addSubview(bannerText)

        // 详情区域
        detailText = NSTextView(frame: NSRect(x: 10, y: 6, width: barW - 20, height: hExpanded - hBurning - 10))
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
        contentView.contentRect = NSRect(x: 0, y: 0, width: barW, height: hBurning)

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
        notifyPanel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.maxY - hBurning - nH - 4,
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
        notifyBody.textColor = NSColor.secondaryLabelColor
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
        Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { _ in self.refresh() }
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

    func readStatus(_ proj: String) -> (task: String, parked: Bool, running: Bool) {
        let kd = proj + "/.codingkeeper"
        var task = ""
        if let data = FileManager.default.contents(atPath: kd + "/status.json"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            task = obj["task"] as? String ?? ""
        }
        let running = pidAlive(kd + "/loop.pid")
        let parked = FileManager.default.fileExists(atPath: kd + "/loop.halt")
        return (task, parked, running)
    }

    func pidAlive(_ f: String) -> Bool {
        guard let s = try? String(contentsOfFile: f, encoding: .utf8),
              let pid = Int32(s.trimmingCharacters(in: .whitespacesAndNewlines)) else { return false }
        return kill(pid, 0) == 0
    }

    func refresh() {
        let projects = registry()
        var burning: [String] = []
        var events: [(String, String)] = []

        for proj in projects {
            let st = readStatus(proj)
            let name = proj.split(separator: "/").last.map(String.init) ?? proj
            if st.parked {
                events.append(("⏸ \(name) 已挂起", "加任务到 queue.md 或 rm loop.halt 复燃"))
            } else if st.running && !st.task.isEmpty {
                burning.append("🔥 \(name): \(st.task)")
            }
        }

        DispatchQueue.main.async {
            let screen = NSScreen.screens[0].frame
            let bx = (screen.width - self.barW) / 2

            let isBurning = !burning.isEmpty
            let h: CGFloat
            if self.userExpanded {
                h = self.hExpanded
            } else if isBurning {
                h = self.hBurning
            } else {
                h = self.hIdle
            }

            // 更新内容
            if isBurning {
                self.bannerText.stringValue = burning.joined(separator: "  │  ")
                self.bannerText.isHidden = false
            } else {
                self.bannerText.stringValue = ""
                self.bannerText.isHidden = true
            }
            self.detailText.string = self.detailLines.joined(separator: "\n")
            self.detailText.isHidden = !self.userExpanded

            // 背景色
            if self.userExpanded {
                self.contentView.layer?.backgroundColor = NSColor.systemGray.withAlphaComponent(0.22).cgColor
            } else if isBurning {
                self.contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.15).cgColor
            } else {
                self.contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.3).cgColor
            }

            // 位置: 贴在屏幕最顶端
            let y = screen.maxY - h
            self.contentView.contentRect = NSRect(x: 0, y: 0, width: self.barW, height: h)
            self.panel.setFrame(NSRect(x: bx, y: y, width: self.barW, height: h),
                                display: true, animate: true)
            self.panel.orderFrontRegardless()
        }

        // 通知
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

    // detailLines 供闭包使用
    var detailLines: [String] = []
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
