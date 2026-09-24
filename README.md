# TKGUI（MyTkUI）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![标准库](https://img.shields.io/badge/依赖-零第三方-green.svg)](#环境要求)

**一套用纯标准库封装 Tkinter 的轻量界面中间件，主打两件事：布局真的按比例，以及多线程真的能安全用。**

`my_tkui.py` 单文件、零第三方依赖，把这几个反复折磨人的问题一次解决掉：

- 分栏容器设了 **10:1**，实际却是 **1:1** —— 这里不会
- 严格按比例切完之后，**中间多出一条空隙** —— 这里没有
- 按钮被拉成一整格那么高 —— 这里有开关
- 子线程里弹个文件对话框，程序直接崩 —— 这里可以安全调用
- 给某一行日志上色，结果**整屏日志都变色**了 —— 这里按类别各归各色
- 文件写了一半出错，留下一个 **0 字节空文件** —— 这里不会

---

## 目录

- [特性一览](#特性一览)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [控件参考](#控件参考)
  - [AppWindow 主窗口](#appwindow-主窗口)
  - [HSplitFrame / VSplitFrame 分栏容器](#hsplitframe--vsplitframe-分栏容器)
  - [LogPanel 多行文本面板](#logpanel-多行文本面板)
  - [FileSelect 文件选择](#fileselect-文件选择)
  - [MyButton 按钮](#mybutton-按钮)
- [工具函数](#工具函数)
- [设计说明](#设计说明)
- [常见坑与对策](#常见坑与对策)
- [目录结构](#目录结构)
- [开发与验证](#开发与验证)
- [路线图](#路线图)
- [许可](#许可)

---

## 特性一览

| 能力 | 说明 |
|---|---|
| 统一 `.add()` 接口 | 所有容器都用 `容器.add(控件, expand=?)` 添加子元素，支持无限嵌套 |
| 严格比例分栏 | 比例严格等于权重之比，且**精确到 1 像素内**、无缝拼接、窗口缩放比例不变 |
| 无缝布局 | 容器空间被完全用满，不出现"多余的空隙/白边"；需要间隙用 `gap=` 显式指定 |
| 行号 | `LogPanel` 自带行号槽，随滚动跟随、增删自动重排、缩放字号自动对齐 |
| 语法高亮 | 正则规则给特定文本自动换色，可加粗/斜体/下划线，打字粘贴后自动重着色 |
| 分级日志 | `info` / `warn` / `error` / `plain` 各用各的颜色，互不干扰，深浅主题自动适配 |
| 可编辑 / 只读 | 同一个类靠 `read_only` 属性切换：只读时用户只能看、选中、复制 |
| 撤销重做 | `Ctrl+Z` / `Ctrl+Y`，日志按行撤销，整体写入不留撤销点 |
| 线程安全 | 子线程可安全调用文件选择（内部投递对话框到主线程并阻塞等结果） |
| 布局自保护 | 缩放字号不会撑坏父容器布局，分栏比例不会被文本内容带偏 |
| 安全写文件 | `safe_write_text()` 先写临时文件再替换，失败也不会留下 0 字节空文件 |
| 零依赖 | 只用 Python 标准库（`tkinter` / `pathlib` / `re` / `threading` / `typing`） |

---

## 环境要求

- **Python 3.8+**（开发与验证环境为 Python 3.13）
- 标准库 `tkinter`（Windows 官方安装包自带；Linux 上需装 `python3-tk`）
- 无需 `pip install` 任何东西

```bash
# Debian / Ubuntu 上如果没有 tkinter
sudo apt install python3-tk
```

---

## 快速开始

直接运行库文件即可看到一个完整示例窗口：

```bash
python my_tkui.py
```

在项目里使用：

```python
from my_tkui import AppWindow, HSplitFrame, VSplitFrame, LogPanel, FileSelect, MyButton

window = AppWindow('我的编辑器', 1000, 800, 800, 600)

# 左右分栏：严格 1:3
main = HSplitFrame(window.root)
window.add(main)

# 右侧再上下分栏：严格 4:1，无缝拼接
panes = VSplitFrame(main.right, 4, 1)
main.right.add(panes)

# 右上：可编辑的代码区（带行号）
editor = LogPanel(panes.top)
panes.top.add(editor)
editor.add_highlight(r'\b(NOP|HLT|CLR)\b', color='#FF6B6B', bold=True, name='指令')
editor.add_highlight(r'@\w+', color='#4EC9B0', name='标签')

# 右下：只读日志区，三级日志三色
log = LogPanel(panes.bottom, read_only=True, bg='#222222')
panes.bottom.add(log)
log.set_level_color('info', '#66CCFF')
log.info('窗口就绪')

# 左侧：文件选择 + 按钮（默认不填充，保持自身大小）
fs = FileSelect(main.left, '选择文件：')
main.left.add(fs)
main.left.add(MyButton(main.left, '保存', on_click=lambda: log.info('保存')))

window.mainloop()
```

---

## 控件参考

### AppWindow 主窗口

```python
window = AppWindow(title, width=700, height=400, min_w=400, min_h=250)
window.add(widget, expand=False)
window.mainloop()
```

| 成员 | 说明 |
|---|---|
| `window.root` | 底层 `tk.Tk()`，需要原生能力时用 |
| `window.add(widget, expand=False)` | 纵向添加一级控件；`expand=True` 纵向拉伸 |
| `window.on_close` | 关闭回调，返回 `False` 可阻止窗口关闭 |
| `window.mainloop()` | 启动消息循环，放在程序最后一行 |

> **提示**：如果一个控件都没声明 `expand=True`，第一个控件会自动占满剩余空间 —— 否则主容器只能按请求尺寸摆放，窗口拖大了容器却不跟着长大。

---

### HSplitFrame / VSplitFrame 分栏容器

```python
HSplitFrame(master, left_weight=1, right_weight=3, proportional=True, gap=0)
VSplitFrame(master, top_weight=4,  bottom_weight=1, proportional=True, gap=0)
# 提供 .left/.right 与 .top/.bottom 子容器
split.set_weights(4, 1)      # 运行时改比例，立即生效
```

| 参数 | 说明 |
|---|---|
| `*_weight` | 权重，决定比例 |
| `proportional=True` | **严格按权重比例切分**，窗口缩放比例不变 |
| `proportional=False` | 先满足内容固有尺寸，剩余空间再按权重分 |
| `gap` | 两块之间的间隙像素，默认 `0` = **无缝拼接** |

实测（1000×800 窗口，`VSplitFrame(right, 10, 1)`）：

| 窗口尺寸 | 上格 | 下格 | 比例 | 中缝 |
|---|---|---|---|---|
| 1000×800 | 718 | 72 | 9.97 | 0 |
| 1300×950 | 855 | 85 | 10.06 | 0 |
| 900×700 | 628 | 62 | 10.13 | 0 |

需要一条明显的分界线时：`VSplitFrame(master, 4, 1, gap=6)`（实测中缝正好 6 像素）。

---

### LogPanel 多行文本面板

一个类，三种用法：**代码编辑器** / **日志控制台** / **只读展示框**。

```python
LogPanel(master, font_name='Consolas', font_size=11, fg='black', bg='white',
         read_only=False, show_line_numbers=True, line_number_color=None)
```

#### 写内容

| 方法 | 说明 |
|---|---|
| `info(msg)` / `warn(msg)` / `error(msg)` | 按类别打印，自动滚到底部 |
| `safe_info(msg)` / `safe_warn(msg)` / `safe_error(msg)` | 子线程安全版本 |
| `pstr(msg, cl=True)` | 打印普通字符串 |
| `log(msg, color=None, prefix='')` | 打印一行并**只给这一行**指定颜色 |
| `safe_log(msg, color=None, prefix='')` | 子线程安全版本 |
| `set_text(content)` | 覆盖写入（清空原有内容） |
| `append(text, color=None)` | 末尾追加，不自动换行 |
| `append_line(text, color=None)` | 末尾追加一行（自动补换行） |
| `insert_text(content)` | 同 `append` |
| `clear()` | 清空 |
| `get_all_text(strip_last_newline=True)` | 取全部文本 |
| `get_selected_text()` | 取选中文本 |

#### 颜色与字体

| 方法 | 说明 |
|---|---|
| `set_fg(color)` | 设置**正文色**：普通文本 / `pstr` / `info` 一起跟随 |
| `set_bg(color)` | 设置背景色，并自动换用适配深浅主题的 warn/error 配色 |
| `set_level_color(level, color)` | 单独指定某类别颜色；传 `None` 恢复自动 |
| `get_level_colors()` | 查看各类别当前颜色（`None` 表示跟随正文色） |
| `set_font(font_name, font_size)` | 设置字体与字号 |
| `set_zoom(step)` | 按步长缩放字号（`Ctrl+滚轮` 的等价调用） |

```python
log.set_level_color('info',  '#1565C0')   # 信息恒为蓝
log.set_level_color('warn',  '#FFA500')   # 警告恒为黄
log.set_level_color('error', '#EE0000')   # 错误恒为红
log.info('文件已加载')       # 蓝
log.warn('未选择输出文件')   # 黄
log.error('编译失败')        # 红
```

> **重点**：`set_fg()` 改的是**整个面板的正文色**，不是"给某一行上色"。
> 想让某一行单独变色，用 `log(msg, color=...)`；想让某类消息长期用某个颜色，用 `set_level_color()`。

#### 行号

| 方法 / 属性 | 说明 |
|---|---|
| `show_line_numbers=True` | 构造参数，默认打开 |
| `set_line_numbers(True/False)` | 运行时开关 |
| `line_number_color` | 构造参数，行号颜色（默认按背景明暗自动选） |
| `.gutter` | 行号槽画布（`tk.Canvas`），需要原生定制时用 |

行号随滚动跟随、增删行自动重排、超过 9 行自动加宽、缩放字号后重新对齐。

#### 语法高亮

```python
add_highlight(pattern, color=None, background=None, bold=False, italic=False,
              underline=False, name=None, override_level=True) -> str
remove_highlight(name)
clear_highlights()
get_highlights()
refresh_highlights(from_index='1.0', to_index=None)
```

| 参数 | 说明 |
|---|---|
| `pattern` | 正则（字符串或已 `re.compile`），逐行匹配 |
| `color` / `background` | 文字色 / 背景色，`None` 表示不改 |
| `bold` / `italic` / `underline` | 加粗 / 倾斜 / 下划线 |
| `name` | 规则名，便于以后删除；不传自动生成 |
| `override_level` | `True`（默认）高亮**覆盖**日志类别色；`False` 则让类别色优先 |

```python
# 汇编器场景示例
editor.add_highlight(r'\b(ADD|SUB|AND|OR|XOR|SHL|SHR|MOVA|INC|DEC|MOVR)\b',
                     color='#569CD6', name='运算类')
editor.add_highlight(r'\b(JH|JX|JSE|JBE|JS|JZ|JNZ|JB|JE)\b',
                     color='#C586C0', name='跳转类')
editor.add_highlight(r'@\w+',   color='#4EC9B0', name='标签')
editor.add_highlight(r'\bR[0-6]\b', color='#DCDCAA', name='寄存器')
editor.add_highlight(r';.*$',   color='#6A9955', italic=True, name='注释')
```

打字、粘贴、撤销之后**都会自动重新着色**。

#### 只读模式

```python
viewer = LogPanel(panes.bottom, read_only=True)   # 构造时指定
viewer.set_read_only(True) / (False)              # 运行时切换
```

| 用户操作 | 只读时 |
|---|---|
| 键盘输入 / 退格 / Delete / 回车 | 改不动 |
| `Ctrl+V` 粘贴 / `Ctrl+X` 剪切 | 改不动 |
| 鼠标拖选 / `Ctrl+A` 全选 / `Ctrl+C` 复制 | **可以** |
| 滚动浏览、`Ctrl+滚轮` 缩放字号 | **可以** |
| 程序调用 `set_text` / `append` / `info` / `error` / `clear` | **照常可用** |

> 只读只挡"用户的手"。程序更新内容时内部会自动临时解锁、写完立刻锁回去，
> 所以显示区内容能随时刷新，界面上仍然是只读的。

#### 撤销 / 重做

| 快捷键 / 方法 | 行为 |
|---|---|
| `Ctrl+Z` / `undo()` | 撤销上一步编辑 |
| `Ctrl+Y` / `redo()` | 重做 |
| `clear_undo_history()` | 清空撤销历史 |

粒度设计：

| 操作 | 一次 `Ctrl+Z` 的效果 |
|---|---|
| 用户打字 | 撤掉一串连续输入 |
| `info()` / `warn()` / `log()` | **一行一行撤** |
| `append()` / `append_line()` | 撤掉一次追加 |
| `set_text()` / `clear()` | 不留撤销点，写入结果成为新起点 |

最后一条是刻意的：`set_text()` 常用来载入文件，若留撤销点，用户一路撤回上一份文件内容反而危险（与常见编辑器的做法一致）。

#### 快捷键汇总

| 快捷键 | 说明 |
|---|---|
| `Ctrl+A` | 全选 |
| `Ctrl+C` | 复制选中 |
| `Ctrl+X` | 剪切（只读时不生效） |
| `Ctrl+V` | 粘贴（只读时不生效） |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做（只读时不生效） |
| `Ctrl+S` | 触发 `.on_save` 回调（需自行绑定） |
| `Ctrl+滚轮 ↑/↓` | 放大 / 缩小字号（**只改字号，不改变控件占用空间**） |

#### 属性

| 属性 | 说明 |
|---|---|
| `.native_widget` | 底层 `ScrolledText`，需要原生能力时用 |
| `.on_save` | `Ctrl+S` 触发的回调 |
| `.read_only` | 是否只读 |
| `.font_name` / `.font_size` | 当前字体名与字号 |

---

### FileSelect 文件选择

```python
FileSelect(master, label='选择文件：', auto_create=False)
```

| 成员 | 说明 |
|---|---|
| `.on_select` | 选中文件后的回调，收到路径字符串 |
| `get_path()` / `set_path(path)` | 读写输入框内容 |
| `ensure_exists(path=None)` | 文件不存在时创建空文件，返回路径 |
| `.last_error` | 最近一次自动创建失败的原因 |
| `.native_entry` | 底层 `Entry` |
| `ask_file(...)` | **可在子线程安全调用**，返回文件路径 |

#### 线程安全的 `ask_file()`

```python
ask_file(title='选择文件', filetypes=None, initialdir=None,
         timeout=None, auto_create=None) -> str
```

子线程里像普通函数一样用，界面线程会在主线程弹出对话框，本线程阻塞等结果：

```python
import threading

def 汇编线程():
    path = fileselect.ask_file(title='选择要汇编的文件',
                               filetypes=[('汇编文件', '*.asm'), ('所有文件', '*.*')])
    if not path:
        return                       # 用户取消 / 超时 / 窗口已关闭
    logplace.safe_info(f'已选择：{path}')

threading.Thread(target=汇编线程, daemon=True).start()
```

- 返回选中的路径字符串；**取消、超时、窗口已关闭一律返回 `''`**，不抛异常
- 调用效果与点击【选择】按钮一致：回填输入框、按需创建文件、触发 `on_select`
- 主线程自己调用也可以（内部会直接弹窗，不会卡死）

#### 自动创建文件

`auto_create` 在构造和 `ask_file()` 上都能传（后者传 `None` 表示沿用构造设置）。

```python
fs = FileSelect(main.left, '输出文件：', auto_create=True)
path = fs.ask_file()                       # 这次也自动创建
path = fs.ask_file(auto_create=False)      # 这次不创建
```

| 行为 | 说明 |
|---|---|
| 文件不存在 | 创建**空文件**，文件类型由**路径后缀**决定（`demo.asm` → `.asm`，`notes.txt` → `.txt`，无后缀就原样创建） |
| 文件已存在 | 只做"不存在才建"，**绝不清空原有内容** |
| 对话框 | 开启自动创建时用**"保存"对话框**（原生"打开"对话框不允许输入不存在的文件名，用户没机会新建）；关闭时仍用"打开"对话框 |
| 默认后缀 | 传了 `filetypes` 时自动推导（只输入 `demo` → `demo.asm`） |
| 父目录不存在等失败 | **不抛异常**，路径照常返回，原因在 `fs.last_error` 里 |

---

### MyButton 按钮

```python
MyButton(master, text='保存', on_click=回调函数)
```

| 成员 | 说明 |
|---|---|
| `on_click` | 点击回调，无参数 |
| `.native_widget` | 底层 `tk.Button`，可改颜色字体 |

---

## 工具函数

| 函数 | 说明 |
|---|---|
| `safe_write_text(path, content, encoding='utf-8')` | 安全写文本：先写同目录临时文件、写完整了再替换。**要么是完整内容，要么保持原样**，不会留下 0 字节空文件。返回错误原因，成功返回 `''` |
| `safe_call(root, func, *args, **kwargs)` | 把 UI 任务投递到主线程（子线程安全），窗口已关闭时静默丢弃 |

```python
from my_tkui import safe_write_text

err = safe_write_text(asm_file, '\n'.join(asm))
if err:
    logplace.safe_error(f'写入失败：{err}')
else:
    logplace.safe_info('编译完成')
```

---

## 设计说明

### 布局为什么用 `place` 而不是 `grid`

`grid` 的规则是"**先满足控件自然尺寸，剩余空间再按 weight 分**"，权重只对"窗口变大后的增量"生效。
而文本框这类控件会把自身请求尺寸钉成当前像素尺寸，两个面板的请求之和正好等于容器高度，
`grid` 便认为没有剩余空间可分，最终按自然尺寸 `1:1` 排布 —— 这就是"设了 10:1 实际却一样高"的根源。

本库的做法：容器尺寸变化时**自己按权重算出每个单元格应得的像素尺寸**，用 `place` 精确摆放。

- 各单元格尺寸之和**严格等于容器尺寸**，一个像素都不剩 → 中间没有空隙、边缘没有白边
- 取整零头补给"最吃亏"的那一块（790 按 10:1 切得 `718:72` 而不是 `719:71`）
- 容器会主动上报"内容自然尺寸"，保证被放进主窗口或另一个分栏时不会被压成 1 像素

### `expand` 的语义

| 情况 | 行为 |
|---|---|
| `add(w, expand=True)` | 控件铺满所在格子，随窗口缩放 |
| `add(w)`（默认 `False`） | 控件保持自身大小，**格子也不会为它膨胀**，所以控件周围不会出现空白 |
| 本库自己的复合控件（`LogPanel` / 分栏容器） | 视为会铺满，漏写 `expand=True` 也不会出错 |
| 原生控件（`tk.Button` 等） | 按 `expand` 参数判定 |

### 缩放字号为什么不会撑坏布局

两层保护：

1. **内层**：文本框的请求尺寸被换算成"当前像素对应的字符数"并钉住，字号变大也不会膨胀出巨大的像素请求
2. **外层**：面板对外上报的尺寸精确等于当前像素尺寸，分栏比例在缩放时一个像素都不动

### 子线程为什么能安全弹对话框

`tkinter` 只能在主线程操作界面。`ask_file()` 内部把对话框投递到主线程执行（`root.after`），
子线程用 `threading.Event` 阻塞等待，再像普通函数一样返回路径。同时处理了三个边界：

- **主线程自己调用时直接弹窗** —— 若也走"投递 + 等待"，主线程自己阻塞住就没人执行那个回调，直接死锁
- **窗口已销毁时立即返回 `''`** —— Tk 在 `destroy()` 之后 `after()` 和 `StringVar.set()` 不报错但也不生效，不先拦一下会让子线程拿到"看着成功、其实界面早没了"的路径
- **`after()` 在主循环未运行时会抛 `RuntimeError`（不是 `TclError`）** —— 一并按"窗口不可用"处理，保证子线程不被异常打断

### 高亮的标签优先级

Tk 中同一段文字被多个标签覆盖时，**后创建的标签优先**。本库据此处理：

- 类别标签（`info`/`warn`/`error`/`plain`）先建，高亮标签后建 → 高亮默认生效
- 每次改动类别配色后重新排一次优先级（`set_fg` / `set_bg` / `set_level_color` 都会重配标签、把次序顶回去）
- `override_level=False` 的规则用 `tag_lower` 降到类别标签之下，保住日志本身的颜色

### 性能上的几个关键取舍

| 取舍 | 原因 |
|---|---|
| 行号画在 `Canvas` 上，且只画可见的几十行 | 不用第二个 `Text` 控件，省内存、免同步滚动条；长文本也不变慢 |
| 行号重画合并到 40ms 定时器 | 连续写日志时不必每行都重画 |
| 追加内容时只高亮新增的那几行 | 整篇重扫是 O(n)，每行都扫一次就退化成 O(n²)（实测 550 行从 60 秒降到 9 秒） |
| `tag_remove` 限定范围而不是到文末 | `tag_remove(tag, from, END)` 会一直扫到文章末尾，是写日志的主要瓶颈之一 |
| 数字宽度按 10 个字符量一次并缓存 | 每行都调 `font.measure()` 会白白多出几万个 Tcl 调用 |
| `see(END)` **立即**执行、不延后 | 它让 Tk 只对可见区排版；一旦推迟，排版范围扩散到全文，连续写入反而从线性退化成平方级（实测 2000 行 90 秒） |
| 内容变化用"长度 + 行数"廉价指标探测 | `edit_modified()` 在撤销后会被 Tk 复位成 `False`，会漏掉撤销 |

---

## 常见坑与对策

| 现象 | 原因 | 对策 |
|---|---|---|
| 设了 `10:1` 结果上下一样高 | `grid` 权重只对增量生效 | 用 `proportional=True`（默认） |
| 严格按比例后中间有空隙 | 单元格内边距 + 取整零头 | 本库已消除；需要间隙时显式传 `gap=` |
| 按钮被拉成一整格 | 控件铺满格子 | `add(w)` 不传 `expand`，并把分栏设成 `proportional=False` |
| 给一行日志上色后整屏都变色 | 用 `set_fg()` 改了整块面板的正文色 | 单行用 `log(msg, color=...)`；某类消息用 `set_level_color()` |
| 子线程弹对话框崩溃 | tkinter 非线程安全 | 用 `FileSelect.ask_file()` 或 `safe_*` 日志方法 |
| 文件建好了但内容是空的 | 先 `open(path,'w')` 清空，写的时候出错 → 留下 0 字节文件 | 用 `safe_write_text()` |
| 缩放字号后分栏比例被撑歪 | 文本框请求尺寸随字号膨胀 | 本库内置两层保护，无需处理 |
| 窗口关掉后子线程报 `TclError` | 子线程还在往主线程投递任务 | `safe_call` 已静默丢弃；面板销毁时会撤掉内部定时任务 |

---

## 目录结构

```
TKGUI/
├── my_tkui.py          # 库本体（单文件，零依赖）
├── LICENSE             # MIT 许可
└── README.md           # 本文档
```

在自己的项目里使用，只需把 `my_tkui.py` 拷到项目目录，或放到 `sys.path` 能搜到的位置：

```python
from my_tkui import AppWindow, LogPanel     # 同目录
```

---

## 开发与验证

本库的开发方式是**先实测再下结论**，README 里的每个数字和每条行为都来自实际运行：

- 布局：用真实像素测量各单元格坐标与尺寸，验证比例、中缝、残余空间
- 交互：用 `event_generate` 模拟真实键盘/鼠标，验证只读、选中复制、撤销重做
- 线程：用真实子线程 + 真实 `mainloop`，并用假对话框替换系统弹窗以便自动化
- 文件：用真实文件系统验证创建、覆盖、失败路径与临时文件清理
- 性能：用 `cProfile` 定位热点，逐项优化并复测

如果你改了库代码，建议按同样方式验证这几点：

1. 分栏比例（多个窗口尺寸下）、中缝为 0、按钮不被拉伸
2. 只读面板改不动、但能选中复制，程序仍可写
3. `Ctrl+Z` / `Ctrl+Y` 的粒度符合上表
4. 行号在滚动、增删行、缩放字号后都对齐
5. 高亮在打字、粘贴、撤销后都刷新
6. 连续写 1000 行日志的耗时（应接近线性）

---

## 路线图

已列入待办的想法（欢迎提 Issue）：

- [ ] 分栏支持拖动分隔条调节比例
- [ ] 行号槽支持点击选中整行、当前行高亮
- [ ] 高亮支持增量更新（只重算改动的那几行，进一步提速）
- [ ] 主题预设（浅色 / 深色一键切换）
- [ ] 括号匹配、自动缩进等编辑器增强
- [ ] `ttk` 风格支持

---

## 许可

[MIT License](LICENSE) © 2026 Bulehopejiang

宽松许可，可以放心使用：

- ✅ 商用、修改、分发、闭源再发布、私人使用都可以
- ✅ 唯一要求：保留版权声明与许可声明（仓库里的 `LICENSE` 文件）
- ⚠️ 作者不承担任何担保责任（软件按"现状"提供）

在你自己项目的 `LICENSE` 或文档里附上本项目的 MIT 声明即可，不需要额外联系作者。

---

> 仓库：<https://github.com/Bulehopejiang/TKGUI>
