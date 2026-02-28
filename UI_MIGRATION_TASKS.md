# Old → New UI 风格迁移任务清单  
# UI Migration Task List (Old version → New version style)  
# 旧版→新版 UIスタイル移行タスク一覧

---

## 一、当前状态概览 / Current State / 現状

| 项目 Item | Agora old | Agora new |
|-----------|-----------|-----------|
| **技术栈** | 纯 HTML + CSS + JS，Flask 静态资源 | Vite + React + Tailwind + MUI + shadcn/ui + Emotion（Figma Make 脚手架） |
| **前端入口** | `static/index.html` + `style.css` + `script.js` | 配置指向 `./src`，但 **src 下暂无前端源码** |
| **UI 特点** | 深色主题、#4ecdc4 / #ff6b6b 强调色、启动加载、场景选择、Agent 定制、侧边栏、聊天界面 | 仅有依赖与构建配置，无实际页面可对照 |

**结论：**  
“New” 目前只有技术栈和设计系统倾向（Tailwind / shadcn / MUI），没有可复制的页面或组件代码。迁移需先 **定义“新风格”的视觉规范**，再在 old 的 HTML/CSS/JS 上落地。

---

## 二、建议任务拆解 / Recommended Tasks / 推奨タスク

### Phase 0：明确“新风格”来源（必做）

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 0.1 | **确定新版本 UI 参考** | 若有 Figma / 设计稿 / 新版本截图，请提供或放到项目内，作为 old 改版的唯一参照。若没有，则需在 0.2 中约定“新风格”规范。 |
| 0.2 | **定义新风格设计规范（无设计稿时）** | 约定：主色/辅色、字体与字号层级、圆角/阴影、间距（如 4/8/16/24）、按钮/输入框/卡片等组件样式，并写成简短设计 token 文档（可放在 `docs/design-tokens.md` 或项目根目录）。 |

---

### Phase 1：样式与主题（CSS / 视觉）

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 1.1 | **统一 CSS 变量（Design Tokens）** | 在 `Agora old/static/style.css` 顶部用 `:root` 定义颜色、间距、圆角、阴影等，替换当前散落的硬编码值（如 #1a1a1a、#4ecdc4、#ff6b6b 等）。 |
| 1.2 | **字体与排版** | 按新风格规范调整 `font-family`、标题/正文字号与行高，与 new 栈常见风格（如 system-ui + 清晰层级）对齐。 |
| 1.3 | **配色与背景** | 若有新设计稿则严格按稿；若无，则保持深色主题并微调配色（背景、边框、强调色）使观感更统一，必要时区分“旧版色/新版色”两套变量便于对比。 |
| 1.4 | **圆角、阴影、边框** | 统一按钮、卡片、输入框、弹窗的 `border-radius`、`box-shadow`、`border`，使其符合新风格规范。 |
| 1.5 | **滚动条与动效** | 保持或调整滚动条样式、过渡动画（如 sidebar、modal、loader），与整体新风格一致。 |

---

### Phase 2：布局与结构（HTML / 结构）

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 2.1 | **主框架与栅格** | 检查主容器、header、sidebar、chat 区域的 max-width / 间距，必要时按新规范增加 wrapper 或统一 padding/margin。 |
| 2.2 | **场景选择页** | 调整场景选择器布局与卡片样式（网格、间距、hover/选中态），对齐新风格。 |
| 2.3 | **Agent 定制页** | 统一定制页的卡片、表单项、折叠区域样式，与 1.x 的 token 一致。 |
| 2.4 | **聊天区与侧边栏** | 聊天列表、输入区、侧边栏（Agent 列表、Emotion、Decision Summary）的间距与层级，按新规范微调。 |
| 2.5 | **弹窗与 Modal** | 统一 Agent 配置弹窗、昵称设置弹窗的尺寸、内边距、标题/按钮区样式。 |

---

### Phase 3：组件级样式（按页面模块）

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 3.1 | **启动加载（Startup Loader）** | Logo、进度条、文案的排版与颜色，使用 CSS 变量。 |
| 3.2 | **按钮（.btn-primary / .btn-secondary）** | 尺寸、字重、圆角、hover/disabled 态，与设计规范一致。 |
| 3.3 | **输入框与 textarea** | 边框、focus 态、placeholder，统一风格。 |
| 3.4 | **Agent 卡片与头像** | 侧边栏与定制页中的 agent 卡片、头像边框/背景色。 |
| 3.5 | **消息气泡与打字指示** | 用户/Agent 气泡、打字动画的配色与圆角。 |
| 3.6 | **Toggle、Slider、Select** | Emotion / Decision 等面板内控件样式统一。 |

---

### Phase 4：脚本与行为（可选，仅涉及样式时）

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 4.1 | **类名与 data 属性** | 若为新风格增加新 class（如 `theme-new`），需在 `script.js` 中保留原有交互逻辑，仅切换类名或替换内联样式为 class。 |
| 4.2 | **响应式** | 若有新断点或布局变化，在 `script.js` 中检查与宽度相关的逻辑（如 sidebar 折叠），确保与 CSS 媒体查询一致。 |

---

### Phase 5：验收与文档

| # | 任务 Task | 说明 Description |
|---|-----------|------------------|
| 5.1 | **逐屏对比** | 启动加载 → 场景选择 → Agent 定制 → 主聊天界面 → 各弹窗，逐屏与设计稿或设计规范对照，查漏补缺。 |
| 5.2 | **更新 README / 注释** | 在 `Agora old/README.md` 或代码注释中注明“已按 new 风格更新 UI”，并附设计 token 或设计稿链接（若有）。 |

---

## 三、执行顺序建议 / Suggested Order / 推奨順序

1. **先做 Phase 0**：确定参考（Figma/设计稿）或写出简短设计规范。  
2. **再做 Phase 1**：在 old 的 `style.css` 里落 Design Tokens 并替换主要硬编码样式。  
3. **然后 Phase 2 → Phase 3**：按布局到组件的顺序改，减少反复。  
4. **最后 Phase 4、5**：按需改脚本与响应式，并做验收与文档。

---

## 四、若“New”后续补全了前端源码 / If "New" Gets UI Code Later

若之后在 `Agora new/src` 下有了 React 组件与样式：

- 可增加任务：**从 new 提取颜色、间距、组件样式** 到一份共用的 token 文档或 CSS 变量文件，再在 old 中引用同一套变量，实现“风格一致、实现分离”（old 仍为 HTML/CSS/JS，new 为 React）。

---

## 五、快速对照表 / Quick Reference

| 你现在有… | 建议先做 |
|-----------|-----------|
| Figma / 设计稿 / 新版本截图 | Phase 0.1 → 1.x 按稿改 → 2.x、3.x |
| 只有“想要更现代”的感觉 | Phase 0.2（写简短规范）→ Phase 1（tokens + 字体/配色/圆角）→ 2、3 |
| 想先小范围试水 | 只做 1.1 + 1.3 + 3.2（变量 + 配色 + 按钮），看一屏效果再铺开 |

如需我按上述某一 Phase 或某几条任务直接改 `Agora old` 的代码，可以说出 Phase 与任务编号（例如“先做 Phase 0.2 和 1.1”），我可以按该顺序具体改 CSS/HTML。
