# 19 · 分布曲线 morph（温度 / 概率分布专用）

**何时用**：内容的核心是一个**连续分布的变尖 / 拉平**——温度、Top-P 这类「旋钮一转，形状就变」的主题。概率条（`patterns/06` 的 `wts/wrow`）只表达「谁高谁低」，曲线 morph 才表达「整体形状在变」。

**成页 donor**：`智谱1.2.3-同一个问题为什么每次答案不一样-学习页.html`（`~/Desktop/智谱1.2html页面/`）。

## 机制（五拍切换式 + 常驻曲线）

曲线 SVG 是 `#animStage` 的**常驻第一行**，五拍文字块照旧切换（`grid-area:1/1` 堆叠），互不干扰：

```html
<svg id="distSvg" class="dist-svg dist" viewBox="0 0 1200 250" data-t="mid">
  <path class="dc" d="…mid 形…"/>
  <circle class="dot d1" cx="320" cy="54" r="7"/>   <!-- 抽中点，按态显隐 -->
  <text class="cx" x="320" y="232" text-anchor="middle">推荐</text> …
</svg>
```

拍机在 `showStep(i)` 里加一行：`ds.setAttribute('data-t', DIST_T[i])`，形状全走 CSS：

```css
.dist .dc{transition:d .55s ease}
.dist[data-t="low"]  .dc{d:path("…尖…")}
.dist[data-t="pick"] .dc{d:path("…尖…")}   /* 同 low */
.dist[data-t="high"] .dc{d:path("…平…")}
.dist[data-t="two"]  .dc{d:path("…平…")}   /* 同 high */
.dist[data-t="pick"] .d1{opacity:1}        /* 抽中点 */
```

## 硬线与陷阱

1. **每个 data-t 都要给 `.dc` 一条 d 规则**。CSS `d` 属性不匹配选择器时会**回退到元素上的 presentation attribute**（初始 mid 形），不是保留上一态——1.2.3 首版就栽在这：pick/two 态没写 d，曲线弹回 mid，抽中点悬在半空。
2. **dot 的 cy 必须对准该态曲线的实际峰值**：pick 用 low 峰（cy=54）、two 用 high 高度（cy≈150/172）；两个态各用独立的 circle，不要复用同一个点挪 cy。
3. `d:path()` 是 Chromium/Safari 17+ 支持；不支持的浏览器**直接跳变**，形状仍正确——这是可接受的降级，不必做 JS 补间。
4. 候选词标签是**常驻静态**的，只让曲线和抽中点动；轴和标签不动，动的东西才看得清。
5. 窄屏（≤700px）：`.anim-stage{overflow-x:auto}` + `.dist-svg{min-width:700px}` 卡内横滚，页面级不得溢出。
6. 验证方式跟切换式完全一样（同屏恰好一拍 / 终态判词 / 重播），另加一条探针：播放中采样 `distSvg` 的 `data-t`，确认随拍切换。
