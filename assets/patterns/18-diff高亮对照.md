# 18 · diff 高亮对照（逐行点亮，差别自己浮出来）

> 选型语境见 `references/02-动画流程选型.md`「一·补」；点亮累加机制与 `14` 同源，对照叙事与 `15 前后对照动画` 同源。成页 donor：`Skill微PBL1.2-04`（一致行垫底 + 三对差异行，恰好压在一半线上）。

**何时用**：两份产出**并排放着、差别藏在行与行之间**——同一句话有/没 skill 的两份纪要、改了 prompt 前后的两段输出、两条规章的差异。
**心理机制**：发现（读者自己看见「差别就在这几行」，比直接告知更有说服力）。
**判据**：两栏行数相近、逐行有对应关系；差别行 ≤ 总行数一半（差别过半就不是 diff，是两篇文章，用 `15`）。行间无对应关系的两段文字不用这个。

> 与 `15 前后对照` 的分界：`15` 是**同一位置**换内容（翻转感），`18` 是**两栏都在**、逐行标出哪里不一样（比对感）。
> 与三层首屏 `fix-cmp` 的分界：`fix-cmp` 静态两栏一眼看全；`18` 有播放、逐行点亮，放在动画区，**两者别同时用同一组内容**。

---

## 结构

```
┌──────────────┬──────────────┐
│ 没有 skill    │ 有 skill      │  ← 栏头，右栏用 --f-tint1 微底
│ 自己发挥格式   │ 5 块固定格式   │  ← 逐行亮：一致行灰、差异行亮
│ 替你指派李娜   │ 3 个 bug 进待确认│
└──────────────┴──────────────┘
字幕条：这一行为什么不一样 ← 指着正在亮的行说
```

**必须有：**

- **行对行对应**：两栏同高行绑定同一播放步；行高一致（同 padding、同 line-height），错位会毁掉比对感；
- 三种行状态：一致行（默认灰）/ **差异行-左**（`--danger` 系浅底）/ **差异行-右**（`--accent` 系浅底）；
- 播放时**先亮左、隔一拍再亮右**——先看见问题、再看见解法，顺序不能反；
- 收束字幕给规律（「差别的根源只有一个：有没有人替你定过格式」），不复数行数。

---

## 实现

### HTML 骨架

```html
<div class="diff-stage" id="diffStage">
  <div class="diff-cols">
    <div class="diff-col" id="diffL">
      <div class="diff-head">没有 skill</div>
      <div class="diff-line" data-di>自己发挥格式</div>
      <div class="diff-line" data-di>替你指派李娜</div>
    </div>
    <div class="diff-col good" id="diffR">
      <div class="diff-head">有 skill</div>
      <div class="diff-line" data-di>5 块固定格式</div>
      <div class="diff-line" data-di>3 个 bug 进待确认</div>
    </div>
  </div>
  <p class="diff-cap" id="diffCap" role="status" aria-live="polite">点「播放」，看差别在哪几行。</p>
</div>
```

### CSS 要点

```css
.diff-cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.diff-col{border:1.5px solid var(--hairline);background:var(--card)}
.diff-col.good{background:var(--f-tint1,rgba(var(--accent-rgb),.04))}
.diff-head{padding:8px 12px;font-weight:700;font-size:var(--fs-note);border-bottom:1.5px solid var(--hairline)}
.diff-line{padding:9px 12px;font-size:var(--fs-note);line-height:1.6;min-height:40px;
  display:flex;align-items:center;opacity:.55;transition:opacity .3s ease,background .3s ease}
.diff-line.hot-l{opacity:1;background:var(--danger-soft,rgba(226,75,74,.12))}
.diff-line.hot-r{opacity:1;background:var(--accent-soft,rgba(var(--accent-rgb),.14))}
.diff-cap{border-left:6px solid var(--accent);background:var(--surface);
  padding:12px 14px;font-size:var(--fs-sub);line-height:1.65;margin-top:12px;min-height:52px}
```

`--danger-soft` / `--accent-soft` 用页面已有的浅底变量；没有就 `rgba()` 现调，**饱和度必须低**（浅底 + 深字，不是色块）。

### JS（STEPS 时间轴，一左一右为一步）

```js
var STEPS = [
  { t: 400,  on: ['#diffL .diff-line:nth-child(2)'],
    cls: 'hot-l', text: '左边这句：格式是谁定的？——没人定，自己发挥。' },
  { t: 1500, on: ['#diffR .diff-line:nth-child(2)'],
    cls: 'hot-r', text: '右边同一行：SKILL.md 里早写死了 5 块。' },
  /* 每对行两步：先左后右 */
];
/* frame/finalState/REDUCED/重播全照抄 1.1-01；
   finalState：一致行 opacity .55，差异行各自 hot-*，收束字幕给规律。 */
```

一致行不用步进（保持灰即可）；只有差异行进 STEPS。差异行 ≤6 行，超过说明内容该拆页。

---

## 节拍

| 动作 | 间隔 |
|---|---|
| 每对差异行（先左后右） | 400ms 起，两步间隔 1100ms |
| 一致行 | 不占步，开场即灰态 |
| 收束字幕 | 最后一步 +300ms |

## 陷阱

- **行错位** → 两栏行高必须逐行相等（同 min-height、同 padding）；一边换行一边没换就对不齐，文案先在本地试排。
- **差异行过半** → 别标了，这不是 diff 是对照文，改用 `15` 或重写内容。
- **左右同时亮** → 顺序感没了；必须先问题后解法，隔一拍。
- **色底太饱和** → 差异行成了色块拼图，字反而读不清；浅底深字是硬线。
- **收束字幕复述「一共 3 处不同」** → 行数读者自己看得见；字幕要给「为什么差」，把行数升级成规律。
