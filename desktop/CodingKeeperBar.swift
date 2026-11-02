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
//   空闲   → 3px 绿色细线贴在菜单栏行 (无文字)
//   悬停   → 光标进入细线条带, 弹出状态计数 (logo+客户端+运行数+待处理数)
//   闪现   → 新任务蓝闪 4s / 完成绿闪 4s (10s 去重), 自动收回
//   待处理 → ⛔ 停止 / ⏸ 自动循环暂停: 琥珀计数常驻
//   点击   → 任务卡片表格, 高度随行数封顶半屏, 超出滚动; 点别处 resignKey 收起
// 渲染为单一状态机: expanded > flash > (hover∨attention)=counts > idle,
// 每轮刷新只走一个分支, 子视图 frame 按状态显式设置, 动画仅在高度变化时发生。

final class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: KeyablePanel!
    var contentView: KeeperContentView!
    var bannerText: NSTextField!
    var flashTitle: NSTextField!
    var flashBody: NSTextField!
    var detailScroll: NSScrollView!
    var detailText: NSTextView!
    var collapseTimer: Timer?
    var userExpanded = false
    var flashUntil = Date.distantPast
    var flashIsDone = false
    var lastFlashAt: [String: TimeInterval] = [:]
    var lastRunningKeys = Set<String>()
    var lastDoneKeys = Set<String>()
    var didBaseline = false
    var hoverActive = false
    var hoverMonitor: Any?
    var notifyPanel: NSPanel!
    var notifyTitle: NSTextField!
    var notifyBody: NSTextField!
    var notifyTimer: Timer?
    var lastNotifyKey = ""
    var spinnerIdx = 0
    var spinnerTimer: Timer?
    var lastCountsModel: [(tool: String, run: Int, pend: Int)] = []
    var spinnerFrames: [NSImage] = []
    var pauseIcon: NSImage?

    let hIdle: CGFloat = 3        // 空闲: 细线
    let hSmall: CGFloat = 22      // 小横幅: 状态计数
    let hFlash: CGFloat = 48      // 闪现横幅
    let barW: CGFloat = 480
    let freshWindow: TimeInterval = 120   // status.json 心跳视为存活的窗口

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.setActivationPolicy(.accessory)
        guard let screen = NSScreen.screens.first else { return }   // 无屏环境(如 SSH 启动)直接退出, 防越界崩溃
        let bx = (screen.frame.width - barW) / 2

        panel = KeyablePanel(contentRect: NSRect(x: bx, y: screen.frame.maxY - hIdle,
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

        bannerText = NSTextField(labelWithString: "⚙︎")
        bannerText.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        bannerText.textColor = .secondaryLabelColor
        bannerText.lineBreakMode = .byTruncatingTail
        bannerText.frame = NSRect(x: 10, y: 3, width: barW - 20, height: 15)
        bannerText.isHidden = true
        contentView.addSubview(bannerText)

        flashTitle = NSTextField(labelWithString: "")
        flashTitle.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        flashTitle.textColor = NSColor.white
        flashTitle.lineBreakMode = .byTruncatingTail
        flashTitle.frame = NSRect(x: 10, y: hFlash - 20, width: barW - 20, height: 16)
        flashTitle.isHidden = true
        contentView.addSubview(flashTitle)

        flashBody = NSTextField(labelWithString: "")
        flashBody.font = NSFont.systemFont(ofSize: 12)
        flashBody.textColor = NSColor(white: 0.88, alpha: 1)
        flashBody.lineBreakMode = .byTruncatingTail
        flashBody.frame = NSRect(x: 10, y: 4, width: barW - 20, height: 15)
        flashBody.isHidden = true
        contentView.addSubview(flashBody)

        detailScroll = NSScrollView(frame: NSRect(x: 10, y: 6, width: barW - 20, height: 60))
        detailScroll.hasVerticalScroller = true
        detailScroll.drawsBackground = false
        detailText = NSTextView(frame: NSRect(x: 0, y: 0, width: barW - 20, height: 1))
        detailText.font = NSFont.systemFont(ofSize: 12)
        detailText.textColor = NSColor.white
        detailText.backgroundColor = .clear
        detailText.isEditable = false
        detailText.isVerticallyResizable = true
        detailText.isHorizontallyResizable = false
        detailText.textContainer?.containerSize = NSSize(width: barW - 20, height: .greatestFiniteMagnitude)
        detailScroll.documentView = detailText
        detailScroll.isHidden = true
        contentView.addSubview(detailScroll)

        let click = NSClickGestureRecognizer(target: self, action: #selector(toggleExpand))
        contentView.addGestureRecognizer(click)
        contentView.contentRect = NSRect(x: 0, y: 0, width: barW, height: hFlash)

        panel.contentView = contentView

        NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification,
                                               object: panel, queue: .main) { [weak self] _ in
            guard let self = self, self.userExpanded else { return }
            self.userExpanded = false
            self.refresh()
        }

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
        notifyBody.textColor = NSColor(white: 0.88, alpha: 1)
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

        // 悬停检测: 全局监听鼠标移动 (只读坐标, 不拦截事件 — 菜单栏照常可点)
        hoverMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]) { [weak self] _ in
            guard let self = self, let s0 = NSScreen.screens.first else { return }
            let p = NSEvent.mouseLocation
            let bx = (s0.frame.width - self.barW) / 2
            let inStrip = p.x >= bx - 40 && p.x <= bx + self.barW + 40
                          && p.y >= s0.frame.maxY - 24
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
        // 与 ck-common register_project 的 /tmp 过滤对齐 (含 realpath 的 /private/tmp 与系统 TMPDIR)
        let tmpPrefixes = ["/tmp/", "/private/tmp/", NSTemporaryDirectory()]
        return s.split(separator: "\n").map(String.init).filter { path in
            FileManager.default.fileExists(atPath: path) && !tmpPrefixes.contains { path.hasPrefix($0) }
        }
    }

    struct ProjStatus {
        var name = ""
        var task = ""
        var tool = ""
        var active = false
        var parked = false
        var running = false
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

    // 任务文本剥掉状态前缀 — 状态由卡片色点表达, 不重复
    func cleanTask(_ s: String) -> String {
        for p in ["▶️ ", "✅ 完成: ", "⛔ codex 停了: ", "⛔ 停了: ", "📋 ", "✅ ", "⛔ "] {
            if s.hasPrefix(p) { return String(s.dropFirst(p.count)) }
        }
        return s
    }

    func duration(_ startedAt: TimeInterval) -> String {
        guard startedAt > 0 else { return "—" }
        let d = max(0, Int(Date().timeIntervalSince1970 - startedAt))
        if d < 60 { return "\(d)s" }
        if d < 3600 { return "\(d / 60)m" }
        return "\(d / 3600)h\(String(format: "%02d", d % 3600 / 60))m"
    }

    func completionTime(_ ts: TimeInterval) -> String {
        guard ts > 0 else { return "—" }
        let d = Date().timeIntervalSince1970 - ts
        if d < 60 { return "刚刚" }
        let f = DateFormatter()
        f.dateFormat = d < 86400 ? "HH:mm" : "MM-dd HH:mm"
        return f.string(from: Date(timeIntervalSince1970: ts))
    }

    // 转圈图标: 8 帧弧线 (缺口旋转), 每帧惰性渲染一次。
    // 画布 14x12 弧心居中 (x=7): 左右各 ~2.5px 对称留白, 图标不前贴后宽
    func spinnerAttach() -> NSAttributedString {
        if spinnerFrames.isEmpty {
            spinnerFrames = (0..<8).map { i in
                let size = NSSize(width: 14, height: 12)
                return NSImage(size: size, flipped: false) { _ in
                    let a = CGFloat(i) / 8 * 360
                    let p = NSBezierPath()
                    p.appendArc(withCenter: NSPoint(x: 7, y: 6), radius: 4.5,
                                startAngle: a, endAngle: a + 300)
                    p.lineWidth = 2
                    NSColor.systemGreen.setStroke()
                    p.stroke()
                    return true
                }
            }
        }
        let att = NSTextAttachment()
        att.image = spinnerFrames[spinnerIdx % spinnerFrames.count]
        att.bounds = NSRect(x: 0, y: -1, width: 14, height: 12)
        return NSAttributedString(attachment: att)
    }
    func pauseAttach() -> NSAttributedString {
        if pauseIcon == nil {
            let size = NSSize(width: 14, height: 12)
            pauseIcon = NSImage(size: size, flipped: false) { _ in
                let p = NSBezierPath(roundedRect: NSRect(x: 1.5, y: 0, width: 11, height: 12), xRadius: 3, yRadius: 3)
                NSColor.systemOrange.setFill()
                p.fill()
                NSColor.white.setFill()
                NSRect(x: 4.5, y: 3, width: 1.8, height: 6).fill()
                NSRect(x: 7.7, y: 3, width: 1.8, height: 6).fill()
                return true
            }
        }
        let att = NSTextAttachment()
        att.image = pauseIcon
        att.bounds = NSRect(x: 0, y: -1, width: 14, height: 12)
        return NSAttributedString(attachment: att)
    }

    // 计数横幅重建: [logo]tool [⟳N] [⏸N] — 转圈在数字前面。
    // 图标两侧用细空格对称留白: 此前左缘仅靠 icon 内边距 (~1.5px) 前贴后宽
    func rebuildCountsBanner() {
        let m = NSMutableAttributedString()
        let thin = NSAttributedString(string: "\u{2009}")
        for (i, c) in lastCountsModel.enumerated() {
            if i > 0 { m.append(NSAttributedString(string: "  ·  ", attributes: [.foregroundColor: NSColor.secondaryLabelColor])) }
            m.append(toolChip(c.tool))
            m.append(NSAttributedString(string: " \(c.tool)", attributes: [.foregroundColor: NSColor.white]))
            if c.run > 0 {
                m.append(thin)
                m.append(spinnerAttach())
                m.append(NSAttributedString(string: "\u{2009}\(c.run)", attributes: [.foregroundColor: NSColor.white]))
            }
            if c.pend > 0 {
                m.append(thin)
                m.append(pauseAttach())
                m.append(NSAttributedString(string: "\u{2009}\(c.pend)", attributes: [.foregroundColor: NSColor.white]))
            }
        }
        bannerText.attributedStringValue = m
    }
    func spinnerTick() {
        guard !bannerText.isHidden && !lastCountsModel.isEmpty else { return }
        spinnerIdx = (spinnerIdx + 1) % 8
        rebuildCountsBanner()
    }

    // 工具 logo: 优先 ~/.codingkeeper/assets/<tool>.png (真品牌图放这里即生效),
    // 缺省绘制品牌色圆角章 + 白色首字母
    func toolChip(_ tool: String) -> NSAttributedString {
        let size = NSSize(width: 18, height: 14)   // 14px 章体 + 4px 呼吸空间
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
                let p = NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: 14, height: 14), xRadius: 3.5, yRadius: 3.5)
                color.setFill()
                p.fill()
                let para = NSMutableParagraphStyle()
                para.alignment = .center
                (glyph as NSString).draw(in: NSRect(x: 0, y: 1, width: 14, height: 12),
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

    func refresh() {
        let projects = registry()
        var running: [ProjStatus] = []
        var attention: [(name: String, tool: String, reason: String)] = []
        var doneItems: [(name: String, tool: String, task: String, ts: TimeInterval)] = []
        var events: [(String, String)] = []
        var flashCandidate: (kind: String, title: String, body: String)?

        var nowRunningKeys = Set<String>()
        var nowDoneKeys = Set<String>()
        for proj in projects {
            let st = readStatus(proj)
            if st.parked {
                events.append(("⏸ \(st.name) 自动循环已暂停", "加任务到 queue.md 或 rm loop.halt 复燃"))
                attention.append((name: st.name, tool: st.tool.isEmpty ? "codex" : st.tool,
                                  reason: "自动循环已暂停 (rm loop.halt 复燃)"))
            } else if st.task.hasPrefix("⛔") {
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

        // 小横幅: 按客户端分段 — logo 章 + 名称 + 转圈运行数 + 暂停待处理数
        var counts: [String: (run: Int, pend: Int)] = [:]
        for st in running { counts[st.tool.isEmpty ? "codex" : st.tool, default: (0, 0)].run += 1 }
        for a in attention { counts[a.tool, default: (0, 0)].pend += 1 }
        lastCountsModel = counts.sorted { $0.key < $1.key }
            .map { (tool: $0.key, run: $0.value.run, pend: $0.value.pend) }
        let lastDone = doneItems.max { $0.ts < $1.ts }

        // 展开面板: 任务卡片 (状态色点 + 加粗工具名 + 灰色项目/时长 + 任务文本)
        let detailAttr = NSMutableAttributedString()
        var cardCount = 0
        let cardPara = NSMutableParagraphStyle()
        cardPara.paragraphSpacing = 7
        cardPara.lineSpacing = 2
        cardPara.alignment = .left
        let dim = NSColor(white: 0.85, alpha: 1)   // 次要信息: 亮灰 (替代 secondaryLabelColor)
        func cardHeader(_ color: NSColor, _ tool: String, _ name: String, _ tail: String) {
            let font12 = NSFont.systemFont(ofSize: 12)
            detailAttr.append(NSAttributedString(string: "● ", attributes: [.foregroundColor: color, .font: NSFont.systemFont(ofSize: 11), .paragraphStyle: cardPara]))
            detailAttr.append(NSAttributedString(string: tool, attributes: [.foregroundColor: NSColor.white, .font: NSFont.systemFont(ofSize: 13, weight: .semibold), .paragraphStyle: cardPara]))
            detailAttr.append(NSAttributedString(string: " · \(name)", attributes: [.foregroundColor: dim, .font: font12, .paragraphStyle: cardPara]))
            if !tail.isEmpty {
                detailAttr.append(NSAttributedString(string: " · \(tail)", attributes: [.foregroundColor: dim, .font: font12, .paragraphStyle: cardPara]))
            }
            detailAttr.append(NSAttributedString(string: "\n", attributes: [.paragraphStyle: cardPara]))
        }
        func cardBody(_ text: String) {
            detailAttr.append(NSAttributedString(string: "    \(text)\n", attributes: [.foregroundColor: dim, .font: NSFont.systemFont(ofSize: 12), .paragraphStyle: cardPara]))
        }
        for st in running.sorted(by: { $0.startedAt < $1.startedAt }) {
            cardHeader(.systemGreen, st.tool.isEmpty ? "codex" : st.tool, st.name, duration(st.startedAt))
            cardBody(cleanTask(st.task))
            cardCount += 1
        }
        for a in attention {
            cardHeader(.systemOrange, a.tool, a.name, "")
            cardBody(a.reason)
            cardCount += 1
        }
        for d in doneItems.sorted(by: { $0.ts > $1.ts }) {
            cardHeader(.secondaryLabelColor, d.tool.isEmpty ? "codex" : d.tool, d.name, completionTime(d.ts))
            cardBody(cleanTask(d.task))
            cardCount += 1
        }
        if cardCount == 0 {
            detailAttr.append(NSAttributedString(string: "暂无任务 — 在任意项目里提交一个任务, 这里就会亮起来",
                attributes: [.foregroundColor: NSColor.secondaryLabelColor, .font: NSFont.systemFont(ofSize: 11), .paragraphStyle: cardPara]))
        }


        DispatchQueue.main.async {
            guard let screen = NSScreen.screens.first else { return }
            let bx = (screen.frame.width - self.barW) / 2
            let now = Date()

            // ── 单一状态机: expanded > flash > (hover∨attention)=counts > idle ──
            let state: String
            if self.userExpanded { state = "expanded" }
            else if now < self.flashUntil { state = self.flashIsDone ? "flashDone" : "flashStart" }
            else if self.hoverActive || !attention.isEmpty { state = "counts" }
            else { state = "idle" }

            // ── 每状态的子视图显式布局 (不依赖固定 frame 叠放) ──
            self.bannerText.frame = NSRect(x: 10, y: (self.hSmall - 17) / 2, width: self.barW - 20, height: 17)
            self.flashTitle.frame = NSRect(x: 10, y: self.hFlash - 22, width: self.barW - 20, height: 18)
            self.flashBody.frame = NSRect(x: 10, y: 4, width: self.barW - 20, height: 17)
            self.contentView.contentRect = NSRect(x: 0, y: 0, width: self.barW, height: self.hFlash)

            self.bannerText.isHidden = state != "counts"
            self.flashTitle.isHidden = !(state == "flashStart" || state == "flashDone")
            self.flashBody.isHidden = self.flashTitle.isHidden
            self.detailScroll.isHidden = state != "expanded"

            switch state {
            case "counts":
                self.rebuildCountsBanner()
            case "idle":
                var idle = "⚙︎ 空闲"
                if let last = lastDone { idle += " · 上次完成 \(self.completionTime(last.ts))" }
                self.bannerText.attributedStringValue = NSAttributedString(
                    string: idle, attributes: [.foregroundColor: NSColor.secondaryLabelColor])
            case "flashStart", "flashDone":
                self.flashTitle.stringValue = self.flashCandidateTitle ?? ""
                self.flashBody.stringValue = self.flashCandidateBody ?? ""
            case "expanded":
                break
            default: break
            }

            // 明细内容只在变化时写入 (避免每轮重置滚动位置)
            let plain = detailAttr.string
            if self.detailText.string != plain {
                self.detailText.textStorage?.setAttributedString(detailAttr)
            }
            self.detailText.layoutManager?.ensureLayout(for: self.detailText.textContainer!)
            let used = self.detailText.layoutManager!.usedRect(for: self.detailText.textContainer!).size
            self.detailText.frame.size.height = max(used.height + 8, 1)

            // ── 高度: 展开态按实测排版高度 (长文本折行不再被截), 其余按状态 ──
            var h: CGFloat
            if state == "expanded" {
                h = min(used.height + 26, screen.frame.height / 2)
            } else if state == "flashStart" || state == "flashDone" {
                h = self.hFlash
            } else if state == "counts" {
                h = self.hSmall
            } else {
                h = self.hIdle
            }
            self.detailScroll.frame = NSRect(x: 10, y: 6, width: self.barW - 20, height: max(h - 12, 1))

            // ── 背景色 (与状态一致) ──
            let bg: NSColor
            switch state {
            case "flashStart": bg = NSColor.systemBlue.withAlphaComponent(0.35)
            case "flashDone":  bg = NSColor.systemGreen.withAlphaComponent(0.35)
            case "counts":     bg = attention.isEmpty ? NSColor.systemGreen.withAlphaComponent(0.18) : NSColor.systemOrange.withAlphaComponent(0.32)
            case "expanded":   bg = NSColor.systemGray.withAlphaComponent(0.22)
            default:           bg = NSColor.systemGreen.withAlphaComponent(0.3)
            }
            self.contentView.layer?.backgroundColor = bg.cgColor

            // ── 位置: 菜单栏行顶边; 高度没变就不重发动画 ──
            let y = screen.frame.maxY - h
            let target = NSRect(x: bx, y: y, width: self.barW, height: h)
            if self.panel.frame != target {
                self.panel.setFrame(target, display: true, animate: self.panel.frame.size.height != h)
            }
            self.panel.orderFrontRegardless()

            // 闪现到期 → 收回; 已到期则清掉计时器
            if now < self.flashUntil && self.collapseTimer == nil {
                let remain = self.flashUntil.timeIntervalSince(now) + 0.1
                self.collapseTimer = Timer.scheduledTimer(withTimeInterval: remain, repeats: false) { _ in
                    self.collapseTimer = nil
                    self.refresh()
                }
            } else if now >= self.flashUntil && self.collapseTimer != nil {
                self.collapseTimer?.invalidate()
                self.collapseTimer = nil
            }

            // 转圈动画: 计数态且有运行任务时以 0.15s 步进旋转 (待处理只有静态暂停章)
            let runTotal = self.lastCountsModel.reduce(0) { $0 + $1.run }
            if state == "counts" && runTotal > 0 {
                if self.spinnerTimer == nil || self.spinnerTimer?.isValid != true {
                    self.spinnerTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { _ in
                        self.spinnerTick()
                    }
                }
            } else if self.spinnerTimer != nil {
                self.spinnerTimer?.invalidate()
                self.spinnerTimer = nil
            }
        }

        // 触发闪现; 同一事件 10s 内不重复 (防状态高频变化导致大横幅常驻)。
        // key 含任务文本: 同项目 10s 内换新任务仍要闪, 只压同一任务的重复抖动
        if let c = flashCandidate {
            let now = Date().timeIntervalSince1970
            let fkey = c.kind + "|" + c.title + "|" + c.body
            if now - (lastFlashAt[fkey] ?? 0) >= 10 {
                lastFlashAt[fkey] = now
                flashCandidateTitle = c.title
                flashCandidateBody = c.body
                flashIsDone = c.kind == "done"
                flashUntil = Date().addingTimeInterval(4.0)
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
    var flashCandidateBody: String?
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
