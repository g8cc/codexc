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

// CodingKeeperBar — 任务面板 (双屏模式):
//   小横幅(常驻) → 状态计数: ⚙︎ 空闲 · 上次完成 HH:mm / 🔥 N 跑 · ⚠️ N 待处理
//   闪现横幅     → 收到新任务蓝闪 4s / 任务完成绿闪 4s, 自动收回小横幅
//   点击展开     → 任务表格 (状态+工具·项目+时长+任务文本), 高度随行数封顶半屏,
//                  超出滚动; 点别处 resignKey 收起

final class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: KeyablePanel!
    var contentView: KeeperContentView!
    var bannerText: NSTextField!
    var flashTitle: NSTextField!
    var flashBody: NSTextField!
    var detailScroll: NSScrollView!
    var detailText: NSTextView!
    var timer: Timer?
    var collapseTimer: Timer?
    var userExpanded = false
    var flashUntil = Date.distantPast
    var flashIsDone = false
    var lastRunningKeys = Set<String>()
    var lastDoneKeys = Set<String>()
    var didBaseline = false
    var notifyPanel: NSPanel!
    var notifyTitle: NSTextField!
    var notifyBody: NSTextField!
    var notifyTimer: Timer?
    var lastNotifyKey = ""
    var hoverActive = false
    var hoverMonitor: Any?

    let hIdle: CGFloat = 3        // 空闲: 细线 (无文字)
    let hSmall: CGFloat = 20      // 小横幅: 状态计数
    let hFlash: CGFloat = 44      // 闪现横幅
    let barW: CGFloat = 480
    let freshWindow: TimeInterval = 120   // status.json 心跳视为存活的窗口

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let screen = NSScreen.screens[0]
        let bx = (screen.frame.width - barW) / 2

        panel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.frame.maxY - hIdle,
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

        // 闪现: 标题行 + 任务文本行
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

        // 明细: 滚动视图包裹的任务表格
        detailScroll = NSScrollView(frame: NSRect(x: 10, y: 6, width: barW - 20, height: 60))
        detailScroll.hasVerticalScroller = true
        detailScroll.drawsBackground = false
        detailScroll.autoresizingMask = [.width]
        detailText = NSTextView(frame: NSRect(x: 0, y: 0, width: barW - 20, height: 1))
        detailText.font = NSFont.systemFont(ofSize: 11)
        detailText.textColor = NSColor.white
        detailText.backgroundColor = .clear
        detailText.isEditable = false
        detailText.isVerticallyResizable = true
        detailText.isHorizontallyResizable = false
        detailText.textContainer?.containerSize = NSSize(width: barW - 20, height: .greatestFiniteMagnitude)
        detailScroll.documentView = detailText
        detailScroll.isHidden = true
        contentView.addSubview(detailScroll)

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
        notifyPanel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.frame.maxY - hSmall - nH - 4,
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

        // 悬停检测: 全局监听鼠标移动 (只读坐标, 不拦截事件 — 菜单栏照常可点)。
        // 光标进入横幅所在的菜单栏条带 → 弹出; 离开 → 收回细线
        hoverMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]) { [weak self] _ in
            guard let self = self else { return }
            let p = NSEvent.mouseLocation
            let bx = (NSScreen.screens[0].frame.width - self.barW) / 2
            let inStrip = p.x >= bx - 40 && p.x <= bx + self.barW + 40
                          && p.y >= NSScreen.screens[0].frame.maxY - 24
            if inStrip != self.hoverActive {
                self.hoverActive = inStrip
                DispatchQueue.main.async { self.refresh() }
            }
        }
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
        var startedAt: TimeInterval = 0
        var ts: TimeInterval = 0
    }

    func readStatus(_ proj: String) -> ProjStatus {
        var st = ProjStatus()
        st.name = proj.split(separator: "/").last.map(String.init) ?? proj
        let kd = proj + "/.codingkeeper"
        if let data = FileManager.default.contents(atPath: kd + "/status.json"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            st.task = obj["task"] as? String ?? ""
            st.tool = obj["tool"] as? String ?? ""
            st.active = obj["active"] as? Bool ?? false
            st.startedAt = obj["started_at"] as? TimeInterval ?? 0
            st.ts = obj["ts"] as? TimeInterval ?? 0
        }
        let pidAlive = pidAlive(kd + "/loop.pid")
        let fresh = Date().timeIntervalSince1970 - st.ts < freshWindow
        st.parked = FileManager.default.fileExists(atPath: kd + "/loop.halt")
        st.running = st.active && !st.parked && (pidAlive || fresh)
        return st
    }

    func pidAlive(_ f: String) -> Bool {
        guard let s = try? String(contentsOfFile: f, encoding: .utf8),
              let pid = Int32(s.trimmingCharacters(in: .whitespacesAndNewlines)) else { return false }
        return kill(pid, 0) == 0
    }

    // 工具 logo: 优先 ~/.codingkeeper/assets/<tool>.png (真品牌图放这里即生效),
    // 缺省绘制品牌色圆角章 + 白色首字母 (codex 绿=C, claude 橙=A, pi 蓝=π …)
    func toolChip(_ tool: String) -> NSAttributedString {
        let size = NSSize(width: 14, height: 14)
        var image: NSImage?
        let assetPath = NSHomeDirectory() + "/.codingkeeper/assets/\(tool).png"
        if FileManager.default.fileExists(atPath: assetPath),
           let img = NSImage(contentsOfFile: assetPath) {
            image = img
        } else {
            let (color, glyph): (NSColor, String) = {
                switch tool {
                case "codex":    return (NSColor(srgbRed: 0x10/255.0, green: 0xA3/255.0, blue: 0x7F/255.0, alpha: 1), "C")
                case "claude":   return (NSColor(srgbRed: 0xD9/255.0, green: 0x77/255.0, blue: 0x57/255.0, alpha: 1), "A")
                case "pi":       return (NSColor.systemBlue, "π")
                case "opencode": return (NSColor.systemIndigo, "O")
                case "zcode":    return (NSColor.systemPurple, "Z")
                case "dsh":      return (NSColor.systemGray, "D")
                default:         return (NSColor.systemTeal, "?")
                }
            }()
            image = NSImage(size: size, flipped: false) { _ in
                let p = NSBezierPath(roundedRect: NSRect(origin: .zero, size: size), xRadius: 3.5, yRadius: 3.5)
                color.setFill()
                p.fill()
                let para = NSMutableParagraphStyle()
                para.alignment = .center
                (glyph as NSString).draw(in: NSRect(x: 0, y: 1, width: size.width, height: size.height - 2),
                                         withAttributes: [.font: NSFont.systemFont(ofSize: 9, weight: .bold),
                                                          .foregroundColor: NSColor.white,
                                                          .paragraphStyle: para])
                return true
            }
        }
        let att = NSTextAttachment()
        att.image = image
        att.bounds = NSRect(x: 0, y: -2, width: size.width, height: size.height)
        return NSAttributedString(attachment: att)
    }

    // 回合时长: started_at 未知显示 "—"
    func duration(_ startedAt: TimeInterval) -> String {
        guard startedAt > 0 else { return "—" }
        let d = max(0, Int(Date().timeIntervalSince1970 - startedAt))
        if d < 60 { return "\(d)s" }
        if d < 3600 { return "\(d / 60)m" }
        return "\(d / 3600)h\(String(format: "%02d", d % 3600 / 60))m"
    }

    // 完成时刻: 1 分钟内 "刚刚", 当天 HH:mm, 更早 MM-dd HH:mm
    func completionTime(_ ts: TimeInterval) -> String {
        guard ts > 0 else { return "—" }
        let d = Date().timeIntervalSince1970 - ts
        if d < 60 { return "刚刚" }
        let f = DateFormatter()
        f.dateFormat = d < 86400 ? "HH:mm" : "MM-dd HH:mm"
        return f.string(from: Date(timeIntervalSince1970: ts))
    }

    func refresh() {
        let projects = registry()
        var running: [ProjStatus] = []
        var attention: [(name: String, tool: String, reason: String)] = []   // 需要人类协助/决策 (常驻)
        var doneItems: [(name: String, tool: String, task: String, ts: TimeInterval)] = []
        var events: [(String, String)] = []
        var flashCandidate: (kind: String, title: String, body: String)?

        var nowRunningKeys = Set<String>()
        var nowDoneKeys = Set<String>()
        for proj in projects {
            let st = readStatus(proj)
            if st.parked {
                // parked 是监督器状态 (自动循环停机待复燃), 不是任务状态
                events.append(("⏸ \(st.name) 自动循环已暂停", "加任务到 queue.md 或 rm loop.halt 复燃"))
                attention.append((name: st.name, tool: st.tool.isEmpty ? "codex" : st.tool,
                                  reason: "自动循环已暂停 (rm loop.halt 复燃)"))
            } else if st.task.hasPrefix("⛔") {
                // ⛔ 是心跳撑着的活状态: 会话退出后 status 过期, 警示随之消失
                let fresh = Date().timeIntervalSince1970 - st.ts < freshWindow
                if fresh {
                    attention.append((name: st.name, tool: st.tool.isEmpty ? "codex" : st.tool,
                                      reason: String(st.task.dropFirst("⛔ codex 停了: ".count)).trimmingCharacters(in: .whitespaces)))
                }
            }
            if st.running {
                running.append(st)
                let key = "\(st.name)|\(st.task)"
                nowRunningKeys.insert(key)
                if didBaseline && !lastRunningKeys.contains(key) {
                    flashCandidate = (kind: "start", title: "▶️ \(st.tool.isEmpty ? "codex" : st.tool) · \(st.name)", body: st.task)
                }
            } else if st.task.hasPrefix("✅") {
                doneItems.append((name: st.name, tool: st.tool, task: st.task, ts: st.ts))
                let key = "\(st.name)|\(st.task)"
                nowDoneKeys.insert(key)
                if didBaseline && !lastDoneKeys.contains(key) && flashCandidate == nil {
                    flashCandidate = (kind: "done", title: "✅ \(st.tool.isEmpty ? "codex" : st.tool) · \(st.name)", body: st.task)
                }
            }
        }
        lastRunningKeys = nowRunningKeys
        lastDoneKeys = nowDoneKeys
        didBaseline = true

        // 小横幅: 按客户端分段 — logo 章 + 名称 + 运行数 + 待处理数 (富文本)
        var counts: [String: (run: Int, pend: Int)] = [:]
        for st in running { counts[st.tool.isEmpty ? "codex" : st.tool, default: (0, 0)].run += 1 }
        for a in attention { counts[a.tool, default: (0, 0)].pend += 1 }
        let countAttr: NSAttributedString = {
            let m = NSMutableAttributedString()
            let segs = counts.sorted { $0.key < $1.key }
            for (i, (key, v)) in segs.enumerated() {
                if i > 0 { m.append(NSAttributedString(string: "  ·  ", attributes: [.foregroundColor: NSColor.secondaryLabelColor])) }
                m.append(toolChip(key))
                m.append(NSAttributedString(string: " \(key) \(v.run)",
                                            attributes: [.foregroundColor: NSColor.white]))
                if v.pend > 0 {
                    m.append(NSAttributedString(string: " ⚠️\(v.pend)",
                                                attributes: [.foregroundColor: NSColor.white]))
                }
            }
            return m
        }()
        let lastDone = doneItems.max { $0.ts < $1.ts }

        // 展开面板: 任务表格 (行数决定高度, 封顶半屏, 超出滚动)
        var rows: [String] = []
        for st in running.sorted(by: { $0.startedAt < $1.startedAt }) {
            rows.append("🔥 \(st.tool.isEmpty ? "codex" : st.tool) · \(st.name) · \(duration(st.startedAt))")
            rows.append("   \(st.task)")
        }
        for a in attention {
            rows.append("⚠️ \(a.tool) · \(a.name)")
            rows.append("   \(a.reason)")
        }
        for d in doneItems.sorted(by: { $0.ts > $1.ts }) {
            rows.append("✅ \(d.tool.isEmpty ? "codex" : d.tool) · \(d.name) · \(completionTime(d.ts))")
            rows.append("   \(d.task)")
        }
        let detailHeight: CGFloat = rows.isEmpty ? 24 : CGFloat(rows.count) * 15 + 16

        DispatchQueue.main.async {
            let screen = NSScreen.screens[0]
            let bx = (screen.frame.width - self.barW) / 2
            let now = Date()
            let flashing = now < self.flashUntil

            var h: CGFloat
            if self.userExpanded {
                h = min(detailHeight + 16, screen.frame.height / 2)
            } else if flashing {
                h = self.hFlash
            } else if self.hoverActive || !attention.isEmpty {
                h = self.hSmall                      // 悬停 / 有待处理: 弹出计数
            } else {
                h = self.hIdle                       // 默认: 3px 细线贴在菜单栏行
            }

            if self.userExpanded {
                // 展开态 = 只显示明细表, 小横幅文字与闪现全部让位 (否则重叠)
                self.flashTitle.isHidden = true
                self.flashBody.isHidden = true
                self.bannerText.isHidden = true
            } else if flashing {
                self.flashTitle.stringValue = self.flashCandidateTitle ?? ""
                self.flashBody.stringValue = self.flashCandidateBody ?? ""
                self.flashTitle.isHidden = false
                self.flashBody.isHidden = false
                self.bannerText.isHidden = true
            } else {
                self.flashTitle.isHidden = true
                self.flashBody.isHidden = true
                self.bannerText.isHidden = false
                if counts.isEmpty {
                    if let last = lastDone {
                        self.bannerText.attributedStringValue = NSAttributedString(
                            string: "⚙︎ 空闲 · 上次完成 \(self.completionTime(last.ts))",
                            attributes: [.foregroundColor: NSColor.secondaryLabelColor])
                    } else {
                        self.bannerText.attributedStringValue = NSAttributedString(
                            string: "⚙︎ 空闲",
                            attributes: [.foregroundColor: NSColor.secondaryLabelColor])
                    }
                } else {
                    self.bannerText.attributedStringValue = countAttr
                }
                if h == self.hIdle { self.bannerText.isHidden = true }   // 空闲细线无文字
            }

            // 任务表格内容与高度
            self.detailText.string = rows.joined(separator: "\n")
            self.detailText.layoutManager?.ensureLayout(for: self.detailText.textContainer!)
            let used = self.detailText.layoutManager!.usedRect(for: self.detailText.textContainer!).size
            self.detailText.frame.size.height = max(used.height + 8, 1)
            self.detailScroll.isHidden = !self.userExpanded
            self.detailScroll.frame.size.height = h - 12

            // 背景色: 蓝闪(新任务) / 绿闪(完成) / 琥珀(待处理) / 绿(运行) / 灰(空闲)
            if flashing {
                let c = self.flashIsDone ? NSColor.systemGreen : NSColor.systemBlue
                self.contentView.layer?.backgroundColor = c.withAlphaComponent(0.35).cgColor
            } else if self.userExpanded {
                self.contentView.layer?.backgroundColor = NSColor.systemGray.withAlphaComponent(0.22).cgColor
            } else if !attention.isEmpty {
                self.contentView.layer?.backgroundColor = NSColor.systemOrange.withAlphaComponent(0.32).cgColor
            } else if !running.isEmpty {
                self.contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.18).cgColor
            } else {
                self.contentView.layer?.backgroundColor = NSColor.systemGreen.withAlphaComponent(0.3).cgColor
            }

            // 位置: 菜单栏行 (顶边), 空闲时只剩 3px 细线
            let y = screen.frame.maxY - h
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

        // 触发闪现 (有新任务/新完成时); 首轮刷新只建立基线
        if let c = flashCandidate {
            flashCandidateTitle = c.title
            flashCandidateBody = c.body
            flashIsDone = c.kind == "done"
            flashUntil = Date().addingTimeInterval(4.0)
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
    var flashCandidateBody: String?
    var detailLines: [String] = []
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
