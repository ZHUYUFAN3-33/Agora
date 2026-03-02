# Agora UI - Figma 设计规格 / Design Spec

用于在 Figma 中还原新 UI 的详细规格说明。

---

## 通用规范 / Global

| 属性 | 值 |
|-----|-----|
| 画布尺寸 | 390 × 844 px (iPhone 14 Pro) |
| 背景色 | #FFFFFF |
| 主字体 | Share Tech Mono (monospace) |
| 辅助字体 | Barlow Condensed, Roboto |

### 颜色 / Colors
- 黑色: `#000000` (r:0, g:0, b:0)
- 占位符灰: `#828282` (r:0.51, g:0.51, b:0.51)
- 白色: `#FFFFFF`
- 边框: `rgba(0,0,0,0.1)`
- 阴影: `0px 0px 3px rgba(0,0,0,0.08), 0px 2px 3px rgba(0,0,0,0.17)`

---

## 1. Landing 落地页

### 主 Frame
- 尺寸: 390 × 844
- 背景: #FFFFFF
- 内容区: 320px 宽，居中

### Logo 区域
- 宽度: 200px
- Logo 图标: 120×120 (splash) / 按比例
- 与文字 Logo 间距: 24px (可调 0–48)
- 底部 margin: 32px

### 按钮 (3 个)
1. **Continue with Google**
   - 高: 48px, 圆角: 10px
   - 背景: #FFFFFF
   - 边框: 1px rgba(0,0,0,0.1)
   - 阴影: 见上方
   - 文字: 14px, rgba(0,0,0,0.54)
   - 图标: 17×17 (Google 四色)

2. **Continue with Apple**
   - 高: 48px, 圆角: 10px
   - 背景: #000000
   - 文字: 14px, #FFFFFF
   - 图标: 17×17 (Apple 白)

3. **OR 分隔线**
   - 左右横线 + 中间 "OR" 文字
   - 字体: Barlow Condensed 14px

4. **Email 输入框**
   - 高: 48px, 圆角: 10px
   - 背景: #000000
   - 占位符: #828282, 13px

5. **Continue 按钮**
   - 高: 48px, 圆角: 10px
   - 背景: #000000
   - 文字: 13px #FFFFFF

### 间距
- 按钮之间: 12px (gap-3)
- 内容区 padding: 24px (px-6)

---

## 2. Onboarding 引导页

### 主 Frame
- 尺寸: 390 × 844
- 背景: #FFFFFF

### 内容区
- 最大宽: 320px
- Logo: 200px 宽, 底部 margin 16px

### 输入框
- 高: 48px
- 圆角: 10px
- 背景: #000000
- 占位符: "Enter your nickname..."
- 文字: 13px #828282

### Continue 按钮
- 高: 48px
- 圆角: 10px
- 背景: #000000
- 文字: 13px #FFFFFF
- 禁用态: opacity 40%

### 间距
- 输入框与按钮: 12px
- 整体 gap: 24px

---

## 3. Chat 聊天页

### 布局
- 顶部: Logo + 设置入口
- 左侧/主区域: 对话列表 或 聊天内容
- 底部: 输入框

### 主要组件
- **消息气泡**: 圆角 10px, 边框 rgba(0,0,0,0.1)
- **Agent 标签**: 7×7 小方块 + 11px 名字 (tracking-widest)
- **输入框**: 类似 Onboarding 样式
- **Toggle 开关**: 38×22px, 圆角 11px

### 颜色
- Agent A/B/C 各有区分色 (见 agents.ts)

---

## 快速创建步骤 (Figma)

1. 新建 Frame 390×844
2. 创建 320×? 内容容器，水平居中
3. 用 Rectangle (圆角 10) 做按钮
4. 用 Text 添加文案，字体 Share Tech Mono 13–14px
5. 复制 Frame 创建 3 个页面变体
