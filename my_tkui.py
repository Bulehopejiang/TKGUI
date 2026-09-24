# my_tkui.py
# ==============================
# 自制Tkinter简易中间件库（MyTkUI）
# 核心设计：统一 .add() 接口，支持无限嵌套布局，封装原生tkinter
# 规则：所有容器都使用 容器.add(控件, expand=?) 添加子元素
# expand=True：控件铺满所在容器/格子，窗口缩放自动拉伸（编辑器、日志面板、分栏容器）
# expand=False（默认）：控件保持自身需要的大小，不被拉伸（文件选择框、按钮）
#   备注 1：本库自己的控件（LogPanel、分栏容器、FileSelect、MyButton）天生就属于
#          其中一类，所以一般不用手写 expand：LogPanel 和分栏容器自动铺满，
#          FileSelect / MyButton 自动保持自身大小。原生控件（tk.Button 等）才需要显式指定。
#   备注 2：在分栏容器的格子（.left/.right/.top/.bottom）里也遵守同一套规则 ——
#          会铺满的控件充满整个格子；固定尺寸的控件只占自身大小，
#          格子也不会为它膨胀，所以控件周围不会留出一片空白。
#
# 可用控件清单：
#   AppWindow()      # 顶层主窗口
#   HSplitFrame()    # 水平左右分栏容器，提供 .left / .right 子容器
#                     # proportional=True(默认)：左右宽度严格等于权重之比
#                     # proportional=False：左侧保持控件自然宽度，多余宽度按权重给右侧
#   VSplitFrame()    # 垂直上下分栏容器，提供 .top / .bottom 子容器
#                     # proportional=True(默认)：上下高度严格等于权重之比（默认3:1），
#                     #   窗口最大化/缩放、字体缩放后比例都不变，不会失衡
#                     # proportional=False：先满足上下两块的固有高度，剩余空间再按权重分
#   # 说明：两种分栏的 proportional=True 都是"无缝切分"——
#   #   子单元格铺满容器，中间不留空隙、边缘不留白边，比例严格等于权重之比；
#   #   想要分栏之间存在间隙，用 gap= 参数指定（默认 0 = 无缝）；
#   #   运行时改比例用 split.set_weights(a, b)
#   LogPanel()       # 多行文本面板（代码编辑器 / 日志输出 / 只读展示）【快捷键、字体颜色】
#                     # Ctrl滚轮缩放只改字号，不会改变控件占用空间，父容器布局不会被撑坏
#                     # Ctrl+Z 撤销 / Ctrl+Y 重做（只读面板上这两个键不生效）
#                     # read_only=True 时用户只能查看、选中、复制，不能编辑：
#                     #   LogPanel(master, read_only=True) 或 panel.set_read_only(True)
#   FileSelect()     # 文件选择控件：标签+输入框+选择按钮
#   MyButton()       # 按钮控件，点击触发回调
# ==============================
import tkinter as tk
import tkinter.font as tkFont
from tkinter import filedialog, scrolledtext
from pathlib import Path
import threading
from typing import Callable, Optional, Any


def safe_call(root: tk.Tk, func: Callable, *args, **kwargs):
    """
    【线程安全UI调度工具函数】
    tkinter 禁止子线程直接操作UI控件。
    在子线程内调用此函数，把UI任务投递到主线程执行。
    参数：
        root: 主窗口tk对象
        func: 需要执行的UI函数
        *args,**kwargs: func对应的参数
    """
    try:
        root.after(0, lambda: func(*args, **kwargs))
    except tk.TclError:
        # 窗口已经被关闭（子线程还在往主线程投递日志），这条日志直接丢弃，
        # 否则子线程会抛出一堆看不懂的 TclError 堆栈
        pass


# 分栏容器左右/上下两个单元格之间的间隙（像素）。
# 默认 0：两个单元格无缝拼接，容器空间被完全用满，不出现任何"多余的空隙"。
# 如果希望两块面板之间有一条明显的分界线，构造分栏容器时传 gap=6 之类的值即可。
_DEFAULT_SPLIT_GAP = 0


def safe_write_text(path: str, content: str, encoding: str = "utf-8") -> str:
    """
    【工具函数】安全写文本文件：先写临时文件、写完整了再替换目标文件。

    为什么需要它：
        直接 open(path,'w') 会先把文件清空再写。如果写入过程中出问题
        （内容里有非法字符、文件被别的程序占用、磁盘写满……），
        磁盘上就留下一个 0 字节的空文件，看起来正是"文件建好了但内容没写进去"。
        本函数改成"先写同目录下的临时文件 → 成功后再替换"，
        于是要么目标文件是完整的新内容，要么保持原样，不会出现半截空文件。
    参数：
        path: 目标文件路径
        content: 要写入的文本
        encoding: 文件编码，默认 utf-8
    返回：
        出错原因字符串；成功时返回 ""（空字符串）
    """
    target = (path or "").strip()
    if not target:
        return "文件路径为空"
    tmp_path = None
    try:
        file_path = Path(target)
        tmp_path = file_path.with_name(file_path.name + ".tmp~")
        with tmp_path.open("w", encoding=encoding) as handle:
            handle.write(content)
        tmp_path.replace(file_path)  # 写完整了再替换，避免留下空文件
        return ""
    except (OSError, ValueError) as exc:
        # 清掉可能残留的临时文件，不给用户留垃圾
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return str(exc)


def _cell_capacities(cells, horizontal: bool) -> list:
    """
    【内部工具函数】判断每个单元格是否"吃得下更多空间"（自然尺寸模式用）。

    判断依据：该格子里的控件是不是按 expand=True 添加的（即会跟着格子一起变大）。
        有 expand=True 的控件 → 可以继续把富余空间分给这个格子；
        全是固定尺寸控件     → 格子不该为它膨胀，否则控件周围会空出一大片空白。
    参数：
        cells: 单元格列表（_BoxFrame）
        horizontal: True=横向分栏，看宽度方向
    返回：
        与 cells 等长的布尔列表
    """
    caps = []
    for cell in cells:
        if cell._has_expandable_child():
            caps.append(True)
            continue
        # 没有展开控件时，还可以看请求尺寸是否被外部撑大（例如嵌套的分栏容器）
        natural = cell._natural_size("w" if horizontal else "h")
        request = cell.winfo_reqwidth() if horizontal else cell.winfo_reqheight()
        caps.append(request - natural >= 2)
    return caps


def _split_one_axis(container: tk.Widget, cells, weights, horizontal: bool, gap: int,
                    proportional: bool, capacities=None):
    """
    【内部工具函数】算出各单元格在主轴（横向=宽 / 纵向=高）上应得的像素尺寸。

    返回的尺寸之和**严格等于容器主轴尺寸**，一个像素都不多、不少：
    容器空间被完全用满，中间不留空隙、边缘不留白边。

    两种模式的区别：
        严格比例（proportional=True）：完全按权重切分；取整丢掉的零头补给"最吃亏"
            的那一块，让每一块都最接近理论值（例如 790 像素高按 10:1 切，
            结果是 718:72 而不是 719:71）。
        非严格比例（proportional=False）：自然尺寸优先，并且只把富余空间分给
            capacities[i] 为 True 的格子（即内容 expand=True、还吃得下更多的格子）；
            更矮的格子保持自然尺寸，富余的像素留给排在后面的格子，
            不会在某个格子周围形成空白。

    参数：
        container: 分栏容器（HSplitFrame / VSplitFrame）
        cells: 单元格列表（_BoxFrame）
        weights: 各单元格权重，与 cells 一一对应
        horizontal: True=按宽度切分（左右分栏）；False=按高度切分（上下分栏）
        gap: 相邻单元格之间的间隙像素（0=无缝）
        proportional: True=严格按权重比例；False=自然尺寸优先
        capacities: 自然尺寸模式下各格子能否继续变大；None 表示按"全能变大"处理
    返回：
        各单元格的像素尺寸列表；容器尚未完成布局时返回 None
    """
    total = container.winfo_width() if horizontal else container.winfo_height()
    if total <= 1:
        return None  # 尚未完成布局，等下一次 Configure 再算
    # 间隙占用的空间先扣掉，剩下的全部切完
    usable = total - max(0, gap) * (len(cells) - 1)
    if usable < len(cells):
        return None  # 容器小到装不下任何内容，本次跳过，避免算出 0 或负数尺寸

    weight_sum = float(sum(weights))
    if weight_sum <= 0:
        ideals = [usable / float(len(cells))] * len(cells)  # 没设权重就平均分
    else:
        ideals = [usable * w / weight_sum for w in weights]
    sizes = [int(ideal) for ideal in ideals]  # 先向下取整

    axis_i = 0 if horizontal else 1
    # 各格子的"最小尺寸"：只由固定尺寸控件（expand=False 的按钮、文件选择框……）决定。
    # 可扩展控件（面板、分栏容器）本身能缩到任意大小，不给它设下限 ——
    # 否则它上报的尺寸会跟窗口一起变大，把权重带偏（设了 10:1 却分成一样高就是这么来的）。
    minimums = []
    for cell in cells:
        if cell._has_expandable_child():
            minimums.append(0)  # 有可扩展控件 → 可以缩小，不设下限
        else:
            minimums.append(max(1, cell._intrinsic_size(False)[axis_i]))

    if not proportional:
        intrinsic = minimums
        if capacities is None:
            capacities = [True] * len(cells)
        if sum(intrinsic) < usable:
            # 空间够放内容：先把固有尺寸分给每个格子，
            # 富余的部分只给"吃得下更多"的格子，按权重分
            extra = usable - sum(intrinsic)
            growable = [i for i, ok in enumerate(capacities) if ok]
            if weight_sum <= 0:
                shares = [extra // len(growable)] * len(growable) if growable else []
            else:
                grow_sum = float(sum(weights[i] for i in growable)) or 1.0
                shares = [int(extra * weights[i] / grow_sum) for i in growable]
            sizes = list(intrinsic)
            for i, share in zip(growable, shares):
                sizes[i] += share
            # 富余的取整零头，同样只补给能变大的格子
            rest = usable - sum(sizes)
            for i in growable:
                if rest <= 0:
                    break
                sizes[i] += 1
                rest -= 1
        elif sum(intrinsic) > 0:
            # 内容整体放不下：按固有尺寸等比压缩，保证每块都还看得见内容
            scale = usable / float(sum(intrinsic))
            sizes = [max(1, int(n * scale)) for n in intrinsic]
            overflow = sum(sizes) - usable
            if overflow > 0:
                sizes[-1] = max(1, sizes[-1] - overflow)
        # 若固有尺寸之和刚好等于可用空间，就直接用上面按权重算出的 sizes
        ideals = [float(s) for s in sizes]
    elif sum(minimums) < usable:
        # 比例模式：按权重切，但"装固定尺寸控件的格子"不会被切得比内容还小 ——
        # 这样只放按钮的格子就不会被按比例拉成一整格那么高。
        # 被补足的尺寸从其余格子按比例扣除，保证总和不变、比例尽量不动。
        too_small = [i for i in range(len(sizes)) if sizes[i] < minimums[i]]
        deficit = sum(minimums[i] - sizes[i] for i in too_small)
        donors = [i for i in range(len(sizes)) if i not in too_small]
        if donors and deficit > 0:
            pool = float(sum(sizes[i] for i in donors)) or 1.0
            for i in donors:
                sizes[i] -= int(deficit * sizes[i] / pool)
        for i in too_small:
            sizes[i] = minimums[i]
        # 取整误差修正：优先从还有富余的格子增减，保证总和精确等于可用空间
        while sum(sizes) != usable:
            need = usable - sum(sizes)
            step = 1 if need > 0 else -1
            donor = next((i for i in donors
                          if (sizes[i] - step) >= max(1, minimums[i])), None)
            if donor is None:
                break
            sizes[donor] += step
        ideals = [float(s) for s in sizes]

    # 比例模式下把取整丢掉的零头补给"最吃亏"的单元格：谁的小数部分大，谁就先补 1 像素。
    # 这样每一块都最接近理论大小（例如 790 按 10:1 切，得到 718:72，
    # 而不是把零头全丢给第一块的 719:71）。
    order = sorted(range(len(sizes)), key=lambda i: ideals[i] - sizes[i], reverse=True)
    for i in order:
        if sum(sizes) >= usable:
            break
        sizes[i] += 1
    # 兜底：总和精确对齐到可用空间，容器里不会剩下任何零散像素
    sizes[-1] = max(1, sizes[-1] + (usable - sum(sizes)))
    return sizes


def _layout_split(container: tk.Widget, cells, weights, horizontal: bool, gap: int,
                  proportional: bool):
    """
    【内部工具函数】把各单元格按算好的尺寸**精确摆进容器**。

    为什么用 place 而不用 grid：
        grid 会先满足控件的自然尺寸、再把剩余空间按 weight 分，权重只对"增量"生效；
        而 LogPanel 把自身请求尺寸钉成了当前像素尺寸，请求之和正好等于容器尺寸，
        grid 就认为没有剩余空间可分，于是一律按自然尺寸 1:1 排布 ——
        表现就是"设了 10:1，实际上下一样高"，格子外还会多出一圈空白。
        place 直接按像素坐标摆放，位置和尺寸完全由我们说了算：
        比例严格等于权重之比，且不留任何空隙。

    参数：同 _split_one_axis
    """
    # 自然尺寸模式下，只有"内容还吃得下更多空间"的格子才会被拉大
    capacities = None
    if not proportional:
        capacities = _cell_capacities(cells, horizontal)
    sizes = _split_one_axis(container, cells, weights, horizontal, gap, proportional,
                            capacities)
    if not sizes:
        return
    # 另一个方向：单元格铺满容器
    cross = container.winfo_height() if horizontal else container.winfo_width()
    if cross <= 0:
        return

    offset = 0
    for cell, size in zip(cells, sizes):
        size = max(1, size)
        if horizontal:
            cell.place(x=offset, y=0, width=size, height=cross)
        else:
            cell.place(x=0, y=offset, width=cross, height=size)
        offset += size + max(0, gap)


class _BoxFrame(tk.Frame):
    """
    【内部基础容器，用户不要直接实例化】
    HSplitFrame / VSplitFrame 的 left/right/top/bottom 都是该类型
    内置统一的add添加接口，实现所有容器API一致
    """
    def __init__(self, master):
        super().__init__(master)
        # 关闭尺寸传递：单元格的大小由分栏容器按比例指定，不允许内部控件反推，
        # 否则"内部控件按当前尺寸上报 → 单元格跟着变 → 比例被带偏"会形成循环
        self.pack_propagate(False)
        self.grid_propagate(False)
        # 已添加的子控件信息：(控件, 是否 expand, 控件真实需求尺寸)
        self._children_info = []

    def add(self, widget: tk.Widget, expand: bool = False):
        """
        向当前容器添加子控件

        :param widget: 子控件（LogPanel / FileSelect / MyButton / 其他分栏容器）
        :param expand: True=控件铺满本格子，随窗口缩放一起变大；
                       False（默认）=只占自身需要的大小，不被拉伸

        说明：
            expand=True 适合作编辑器 / 日志面板 / 嵌套分栏容器；
            expand=False（默认）适合按钮、文件选择框这类固定大小的控件：
                按自身尺寸摆放，并且格子也不会为它膨胀，
                所以严格比例分栏里，这样的控件不会被拉成一整格那么大。
        """
        filling = self._is_filling(widget, expand)
        widget.pack(fill=tk.BOTH if filling else tk.X, expand=filling)
        # 记住控件在"被铺满之前"的真实需求尺寸，作为格子的自然尺寸基准
        natural = self._child_natural(widget)
        self._children_info.append((widget, filling, natural))
        # 按当前内容刷新对外上报的请求尺寸与固有尺寸（分栏容器没被分配尺寸时也能撑开）
        self._report_natural_size()

    @staticmethod
    def _is_filling(widget: tk.Widget, expand: bool) -> bool:
        """
        【内部方法】判断某个子控件是否"会跟着格子一起变大"。

        规则：
            显式传了 expand=True → 会（铺满格子）；
            控件本身是自定义控件（LogPanel、分栏容器等本库的 Frame 子类）→ 会。
                这类控件天生就是用来占满可用空间的，即使调用时漏写 expand=True
                也按占满处理；
            其余原生控件（Button、Entry、Label……）→ 不会，按自身大小摆放。
        参数：
            widget: 子控件
            expand: 调用 add() 时传的 expand 参数
        返回：
            True 表示它会随格子一起变大
        """
        from_container = isinstance(widget, (LogPanel, HSplitFrame, VSplitFrame))
        return bool(expand) or from_container

    def _report_natural_size(self):
        """
        【内部方法】刷新本单元格对外上报的请求尺寸。

        为什么必须显式上报：
            单元格内部用 pack 摆放子控件，而 pack_propagate 已关闭，
            所以 Frame 自己不会把子控件的尺寸传上去。父容器（另一个分栏容器，
            甚至主窗口）正是通过 winfo_reqheight() 决定本单元格能拿多大，
            不上报的话它就只按 1×1 处理，整块区域会塌成一条线。

        上报口径与分栏模式对齐，避免两种模式互相打架：
            严格比例分栏：只上报固定尺寸控件的需求（expand=True 的控件反正会被铺满，
                上报它的尺寸会随窗口变大，把比例带偏）；
            自然尺寸分栏：上报全部内容的需求（面板才有一个合理的初始高度）。
        """
        if getattr(self.master, "proportional", False):
            width, height = self._intrinsic_size(False)
        else:
            width, height = self._natural_size("w"), self._natural_size("h")
        self.config(width=max(1, width), height=max(1, height))

    def _natural_size(self, axis: str) -> int:
        """
        【内部方法】量出本单元格"装下内容需要多大"（记下来的真实需求尺寸）。

        为什么不用 winfo_reqheight() 现算：
            单元格的 pack_propagate 已关闭（防止内部控件把尺寸反推上来），
            而且 LogPanel 这类控件会把自身请求尺寸钉成当前分配到的尺寸，
            现算出来的值会随窗口尺寸变化。所以在 add() 时就记下每个控件的真实需求，
            之后一律用这份记录，布局结果就与调用时机无关、也不会来回漂移。
        参数：
            axis: "h" 量高度；其它值量宽度
        返回：
            自然尺寸（像素），至少为 1
        """
        return self._sum_children(axis, only_fixed=False)

    def _has_expandable_child(self) -> bool:
        """【内部方法】本格子里是否有按 expand=True 添加的控件（它会跟着格子一起变大）"""
        return any(expanded for _, expanded, _ in self._children_info)

    def _has_fixed_child(self) -> bool:
        """【内部方法】本格子里是否有按 expand=False 添加的固定尺寸控件"""
        return any(not expanded for _, expanded, _ in self._children_info)

    def _intrinsic_size(self, for_grow: bool = False):
        """
        【内部方法】量出内容的"固有尺寸"，供分栏容器决定这个格子给多大。

        基于 add() 时记下的控件真实需求尺寸，所以结果与窗口尺寸无关、不会漂移。

        参数：
            for_grow: True=优先用 expand=True 控件的需求尺寸（没有展开控件时退回固定控件）；
                      False=只算 expand=False 的控件，即"内容至少要占这么大"
        返回：
            (固有宽度, 固有高度) 二元组；没有对应控件时为 0
        """
        if for_grow and self._has_expandable_child():
            only_fixed = False
        else:
            only_fixed = True
        return (self._sum_children("w", only_fixed),
                self._sum_children("h", only_fixed))

    def _sum_children(self, axis: str, only_fixed: bool) -> int:
        """
        【内部方法】累加子控件的请求尺寸。

        参数：
            axis: "h" 累加高度；其它值取宽度的最大值
            only_fixed: True=只统计 expand=False 的控件（固有尺寸）；
                        False=统计全部控件（当前自然尺寸）
        返回：
            像素尺寸，至少为 1
        """
        total = 0
        for child, expanded, natural in self._children_info:
            if only_fixed and expanded:
                continue
            info = child.pack_info()  # 取 pack 的 pady/padx，保证量出来的尺寸和实际摆放一致
            pady = 2 * int(info.get("pady", 0))
            padx = 2 * int(info.get("padx", 0))
            if natural is None:
                natural = (1, 1)
            if axis == "h":
                total += natural[1] + pady
            else:
                total = max(total, natural[0] + padx)
        # 补上 Frame 自身边框占用的像素
        border = 2 * int(self.cget("bd") or 0)
        return max(1, total + border)

    def _child_natural(self, child: tk.Widget):
        """
        【内部方法】量出某个子控件"装下自己的内容需要多大"。

        为什么要临时打开尺寸传递：
            本单元格关掉了 pack_propagate（不让子控件反推格子大小），
            而 LogPanel、其他分栏容器这类复合控件自己也关掉了尺寸传递，
            所以直接读它们的 winfo_reqheight() 只会得到 1，量不出真实需求。
            这里临时把尺寸传递打开、让 Tk 重新算一次请求尺寸，量完立刻还原，
            布局结果不受任何影响。
        参数：
            child: 子控件
        返回：
            (宽, 高)；量不出来时返回 None
        """
        try:
            child.pack_propagate(True)
            child.grid_propagate(True)
            # 先让 Tk 把"内容驱动"的请求尺寸算出来，再读；
            # 直接读会拿到切换前缓存的旧值，量出来的尺寸会随调用时机变化
            self.update_idletasks()
            size = (child.winfo_reqwidth(), child.winfo_reqheight())
        except tk.TclError:
            return None
        finally:
            try:
                child.pack_propagate(False)
                child.grid_propagate(False)
            except tk.TclError:
                pass
        return size


class LogPanel(tk.Frame):
    """
    多行文本面板，可作为代码编辑器、日志输出控制台，也可当只读文本框用
    【功能】快捷键、Ctrl+滚轮字体缩放、按类别着色、字体/前景/背景色配置、只读锁定
    只读属性：
        read_only=False（默认）：正常可编辑
        read_only=True：只读，用户不能输入/删除/粘贴/剪切，
                        但依然能查看、鼠标选中、Ctrl+A 全选、Ctrl+C 复制、滚动
        构造时直接传：LogPanel(master, read_only=True)
        运行中切换：  panel.set_read_only(True) / panel.set_read_only(False)
        说明：只读只挡"用户的手"，程序自己仍然可以用 set_text / append /
              clear / info / error 更新内容（内部会自动临时解锁再锁上）。
    方法：
        info(msg) / warn(msg) / error(msg)：主线程按类别打印日志，自动滚动到底部
        safe_info(msg) / safe_warn(msg) / safe_error(msg)：子线程安全打印日志
        pstr(msg)：打印普通字符串，自动换行
        log(msg, color=None, prefix="")：打印一行并只给这一行指定颜色
        clear()：清空全部文本
        get_all_text()：获取面板全部文本
        get_selected_text()：获取鼠标选中的文本，无选中返回空字符串
        set_text(content)：覆盖写入文本（清空原有内容，填入新内容）
        insert_text(content) / append(text, color=None)：在末尾追加文本
        set_read_only(True/False)：切换用户可否编辑
        undo() / redo()：撤销 / 重做上一步编辑（等价于 Ctrl+Z / Ctrl+Y）
        clear_undo_history()：清空撤销历史（载入新内容后不想让用户撤回去时用）
    颜色与字体方法：
        set_font(font_name, font_size)：设置全局字体和字号
        set_zoom(step)：按步长缩放字号（正数放大，负数缩小）
        set_fg(color)：设置正文颜色，普通文本 / pstr / info 一起跟随它
        set_bg(color)：设置背景色，并自动换用适配的 warn/error 配色
        set_level_color(level, color)：单独指定某一类别颜色；color 传 None 恢复自动
        get_level_colors()：查看各类别当前的自动配色
        【重要】set_fg 只改"正文色"，不会把整屏日志染成同一个颜色：
        正文、info 跟随它一起变，warn/error 始终保持各自的醒目色。
        【常见误区】不要用 set_fg 来给某一条日志上色 ——
        那会改掉整个面板的正文色，之后写入的所有内容都会变成这个颜色。
        想临时强调某一行，请用 log(msg, color=...)。
    类别配色（LEVELS = info / warn / error / plain）：
        info / plain 跟随正文色（由 set_fg 决定）；
        warn / error 自动按背景明暗选色：浅色背景 warn=深黄 error=深红，
        深色背景 warn=亮黄 error=亮红，保证深色主题下也看得清。
        想固定某类别颜色用 set_level_color，例如：
            panel.set_level_color("error", "#FF3B30")
    快捷键（面板激活时生效）
        Ctrl+A 全选文本
        Ctrl+C 复制选中
        Ctrl+X 剪切选中（只读时不生效）
        Ctrl+V 粘贴（只读时不生效）
        Ctrl+Z 撤销上一步编辑（只读时不生效）
        Ctrl+Y 重做（只读时不生效）
        Ctrl+S 触发 on_save 回调（需要自己绑定逻辑）
        Ctrl+鼠标滚轮 ↑：放大字体；↓：缩小字体【仅改字号，保留视口，布局不抖动】
    属性：
        .native_widget：底层原生 ScrolledText 对象，用于高级自定义
        .on_save：Ctrl+S触发的回调函数
        .read_only：是否只读（True/False，可直接改，也可以用 set_read_only）
    """
    # 字号允许范围（构造、缩放、set_font 都受此限制），防止字号失控
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 40
    # 文本类别标签（Text 的 tag 名），用来给不同类别的内容上不同颜色
    LEVELS = ("info", "warn", "error", "plain")
    # 两套预设配色：浅色背景用 False 那套，深色背景用 True 那套。
    # 只描述"类别配色"，正文颜色由 set_fg 决定。
    _PALETTES = {
        False: {  # 浅色背景（例如白底）
            "warn": "#A15C00",
            "error": "#C00000",
        },
        True: {  # 深色背景（例如 #222222）
            "warn": "#E8C547",
            "error": "#FF6B6B",
        },
    }

    def __init__(self, master, font_name="Consolas", font_size=11, fg="black",
                 bg="white", read_only: bool = False, **kwargs):
        super().__init__(master, **kwargs)
        self.root = self.winfo_toplevel()
        self.on_save: Optional[Callable[[], None]] = None  # Ctrl+S保存回调
        # 是否只读：True 时用户只能查看、选中、复制，改不动内容
        self.read_only = bool(read_only)

        # 字体配置
        font_size = max(self.MIN_FONT_SIZE, min(self.MAX_FONT_SIZE, int(font_size)))
        self.font_name = font_name
        self.font_size = font_size
        self.font = tkFont.Font(family=self.font_name, size=self.font_size)

        # 已经钉定的面板像素尺寸（0 表示尚未钉定）
        self._pin_w = 0
        self._pin_h = 0

        # undo=True 打开 Text 自带的撤销栈，Ctrl+Z / Ctrl+Y 才能撤销/重做。
        # 分隔符沿用 Tk 默认（autoseparators=True）：连续输入算一次撤销，
        # 关闭一次撤销范围由 Tk 自动按"操作时间/内容变化"划分
        self.text = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=self.font,
                                             fg=fg, bg=bg, undo=True)
        self.text.pack(fill=tk.BOTH, expand=True)

        # ========== 类别配色 ==========
        self._bg_color = bg
        self._fg_color = fg
        self._level_colors = {}
        # 用户用 set_level_color 手动指定的类别颜色（换背景色时不会被覆盖）
        self._manual_levels = {}
        # insert_line(..., color=...) 用的临时颜色标签序号，保证带色文本有独立标签
        self._custom_tag_seq = 0
        self._apply_palette()

        # ========== 关键：阻止字号变化影响父容器布局 ==========
        # 第1层（内）：文本框自身的请求尺寸不随字号膨胀
        self.text.bind("<Configure>", self._on_text_configure)
        # 第2层（外）：面板对外上报的尺寸精确等于当前像素尺寸，
        #             分栏比例在缩放时才能做到一个像素都不动
        self.bind("<Configure>", self._on_panel_configure)

        # ========== 绑定快捷键 ==========
        self.text.bind("<Control-a>", self._hotkey_select_all)
        self.text.bind("<Control-c>", self._hotkey_copy)
        self.text.bind("<Control-x>", self._hotkey_cut)
        self.text.bind("<Control-v>", self._hotkey_paste)
        self.text.bind("<Control-s>", self._hotkey_save)
        # 撤销 / 重做：Text 自带撤销栈（构造时 undo=True 开启）
        self.text.bind("<Control-z>", self._hotkey_undo)
        self.text.bind("<Control-y>", self._hotkey_redo)
        # Ctrl+鼠标滚轮缩放字体
        self.text.bind("<Control-MouseWheel>", self._mousewheel_zoom)

        # 只读面板最后才锁上：上面的配色和内容写入都需要控件处于可写状态
        if self.read_only:
            self.text.config(state="disabled")

    # ---------------- 字体颜色API ----------------
    def set_font(self, font_name: str, font_size: int):
        """设置面板全局字体名称和字号（同样不会撑坏父容器布局）"""
        font_size = int(font_size)
        font_size = max(self.MIN_FONT_SIZE, min(self.MAX_FONT_SIZE, font_size))
        self.font.config(family=font_name, size=font_size)
        self.font_name = font_name
        self.font_size = font_size
        # 换字体/字号后立即重钉请求尺寸，避免布局被撑变形
        self._pin_requested_size()

    def set_fg(self, color: str):
        """
        设置正文颜色，支持颜色名/十六进制 #RRGGBB。

        正文色同时作用于：普通文本、附加文本、info（这几个类别跟随正文色，
        不单独打颜色标签）。因为走的是 Text 的默认前景色，
        所以已写好的普通文本与 info 会一起变成新颜色，
        而 warn / error 的醒目色和用户手动指定的颜色不受影响。
        """
        self._fg_color = color
        self.text.config(fg=color)

    def set_bg(self, color: str):
        """
        设置背景色，支持颜色名/十六进制 #RRGGBB。

        同时会按新背景的明暗自动换用合适的警告/错误配色（深色背景用亮黄亮红，
        浅色背景用深黄深红），保证在深色主题下内容依然看得清。
        已经被 set_level_color 手动指定过的类别不会被覆盖。
        """
        self._bg_color = color
        self.text.config(bg=color)
        self._apply_palette()  # 只覆盖没被用户手动指定过的类别

    def set_level_color(self, level: str, color: Optional[str]):
        """
        设置某一类别文本的颜色。

        参数：
            level: "info" / "warn" / "error" / "plain"
            color: 颜色名或 #RRGGBB；传 None 表示恢复成自动配色
        示例：
            panel.set_level_color("error", "#FF3B30")   # 错误用亮红
            panel.set_level_color("info", None)         # 恢复自动配色
        """
        if level not in self.LEVELS:
            raise ValueError(f"类别名必须是 {self.LEVELS} 之一，收到 {level!r}")
        if color is None:
            self._manual_levels.pop(level, None)  # 撤销手动指定，回到自动配色
        else:
            self._manual_levels[level] = color
        self._apply_palette()

    def get_level_colors(self) -> dict:
        """返回当前各类别各自的颜色，便于调试或做主题切换"""
        return dict(self._level_colors)

    def _is_dark(self, color: str) -> bool:
        """
        【内部方法】判断给定颜色是深色还是浅色（决定用哪套配色）。
        做法：取 #RRGGBB 三通道按人眼敏感度加权求亮度，亮度低于中值算深色。
        参数：
            color: 颜色名或 #RRGGBB
        返回：
            True 表示深色
        """
        try:
            r, g, b = self.winfo_rgb(color)  # 拿到 0~65535 的三通道
            r, g, b = r >> 8, g >> 8, b >> 8
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
        except tk.TclError:
            return False  # 认不出来的颜色名按浅色处理

    def _apply_palette(self):
        """
        【内部方法】按当前背景明暗铺一套配色。

        只有 warn / error 需要独立颜色（醒目提示用），info / plain 记为 None ——
        表示"用面板的正文色"，也就是不单独打颜色标签，直接跟随 Text 的默认前景色。
        这样 set_fg 改正文色时，正文与 info 会一起变，而 warn/error 保持自己的颜色，
        已写好的内容也不会被整屏染成同一个色。
        用户用 set_level_color 手动指定过的类别，始终优先。
        """
        palette = self._PALETTES[self._is_dark(self._bg_color)]
        colors = {
            "info": None,   # None = 跟随正文色（set_fg）
            "plain": None,
            "warn": palette["warn"],
            "error": palette["error"],
        }
        colors.update(self._manual_levels)  # 用户指定过的覆盖预设
        self._level_colors = colors
        self._refresh_level_tags()

    def _refresh_level_tags(self):
        """
        【内部方法】把当前配色应用到 Text 的各个标签上。

        颜色为 None 的类别（默认的 info / plain）**不打颜色标签**，
        直接跟随 Text 的默认前景色（即 set_fg 设的正文色）。
        这一点很关键：如果给它们打上固定的颜色标签，之后 set_fg 改正文色时，
        已经写好的内容会被标签颜色"锁住"或被整屏重染，两种都不符合预期。
        """
        for level in self.LEVELS:
            color = self._level_colors.get(level)
            if color is None:
                # 清掉之前可能设过的颜色，让它回到跟随正文色
                self.text.tag_config(level, foreground="")
            else:
                self.text.tag_config(level, foreground=color)

    def insert_line(self, text: str, level: str = "plain", color: Optional[str] = None):
        """
        在末尾追加一段文本，并给它单独上色（其余内容不受影响）。

        参数：
            text: 要写入的文本
            level: 类别，LEVELS 之一；决定用哪套自动配色
            color: 直接指定颜色（优先于 level 的自动配色）；None 表示按 level 走
        说明：
            这是"临时强调某一段"的正确做法 —— 不用 set_fg 改整个面板的颜色，
            那样之后写入的所有内容都会跟着变。
        """
        start = self.text.index("end-1c")  # 注意不是 END：END 之后的位置取不到内容
        old_state = self._writable_state()
        self.text.insert(tk.END, text)
        if color is not None:
            # 一次性标签：只覆盖这一段，不影响已写好的内容和后面的内容
            tag = f"custom_{self._custom_tag_seq}"
            self._custom_tag_seq += 1
            self.text.tag_config(tag, foreground=color)
            self.text.tag_add(tag, start, "end-1c")
        elif self._level_colors.get(level) is not None:
            self.text.tag_add(level, start, "end-1c")
        self.text.see(tk.END)
        self.text.update_idletasks()
        self._restore_state(old_state)

    def append(self, text: str, color: Optional[str] = None):
        """
        在末尾追加文本（不额外加换行），可指定颜色。
        参数：
            text: 要追加的文本
            color: 颜色名或 #RRGGBB；None 表示用正文色
        """
        self.insert_line(text, level="plain", color=color)

    def clear(self):
        """
        清空面板内全部文本。

        清空之后撤销历史会重置（清空结果作为新的起点），
        所以之后按 Ctrl+Z 撤销的是清空之后新写入的内容，不会把面板还原成清空前
        那一大堆旧文本 —— 这是编辑器的通行做法（载入/清空等整体操作不留撤销点）。
        如果确实需要"清空前的内容"能撤回来，请在清空前自己备份
        （get_all_text() 存一份）。
        """
        old_state = self._writable_state()
        self.text.delete("1.0", tk.END)
        self._restore_state(old_state)
        self._reset_undo_baseline()

    def set_text(self, content: str):
        """
        覆盖式写入文本：清空原有内容，填入新文本，自动滚动到末尾。

        写入的内容跟随正文色（set_fg 设的颜色），不会被打上类别标签。
        与 clear 一样，写入后撤销历史会重置：这次写入的内容成为新起点，
        之后按 Ctrl+Z 撤销的是"写完之后又新写的内容"，
        不会把面板倒回上一份文件内容（导入新文件后不该还能撤回到旧文件）。
        需要保留旧内容时请自己先 get_all_text() 备份。
        """
        old_state = self._writable_state()
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.see(tk.END)
        self.text.update_idletasks()
        self._restore_state(old_state)
        self._reset_undo_baseline()

    def get_all_text(self, strip_last_newline: bool = True) -> str:
        """
        获取全部文本。
        参数：
            strip_last_newline: True（默认）=剔除末尾多余换行，方便直接拿去用；
                                False=原样返回（写回文件等场景更合适）
        返回：
            面板全部文本字符串
        """
        content = self.text.get("1.0", tk.END)
        return content.rstrip("\n") if strip_last_newline else content

    def get_selected_text(self) -> str:
        """获取鼠标选中的文本，未选中返回空串"""
        try:
            return self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return ""

    # ---------------- 快捷键事件处理 ----------------
    def _hotkey_select_all(self, event):
        self.text.tag_add(tk.SEL, "1.0", tk.END)
        self.text.mark_set(tk.INSERT, "1.0")
        return "break"

    def _hotkey_copy(self, event):
        self.text.event_generate("<<Copy>>")
        return "break"

    def _hotkey_undo(self, event):
        """
        Ctrl+Z 撤销上一步编辑。

        撤销的是零散编辑：用户自己敲进去的字、按类别打印的每一行日志、
        append / append_line 追加的内容，一次 Ctrl+Z 撤掉一步。
        整体写入（set_text / clear）不留撤销点，它们是新的起点，见这两个方法的说明。
        只读面板直接忽略（用户本来就不能改，没有需要撤销的内容）；
        撤销栈为空时什么都不做，也不会弹出 tkinter 报错。
        """
        if self.read_only:
            return "break"
        try:
            self.text.edit_undo()
        except tk.TclError:
            pass  # 撤销栈为空，忽略即可
        return "break"

    def _hotkey_redo(self, event):
        """Ctrl+Y 重做（把刚撤销掉的编辑重新做回来）"""
        if self.read_only:
            return "break"
        try:
            self.text.edit_redo()
        except tk.TclError:
            pass  # 没有可重做的内容，忽略
        return "break"

    def _reset_undo_baseline(self):
        """
        【内部方法】把当前内容作为撤销起点：清空历史，之后 Ctrl+Z 不会越过它。

        给 set_text / clear 这种"整体替换"用。Tk 内部把整块清空记成一步撤销，
        撤销它只会得到空内容（不是上一版内容），留着反而会造成困惑，
        所以整体写入后直接把历史重置掉。
        """
        try:
            self.text.edit_reset()
        except tk.TclError:
            pass

    def undo(self):
        """
        撤销上一步编辑（等价于按 Ctrl+Z）。

        说明：撤销的是"用户自己做的编辑"。程序写入的日志/文本（info、set_text 等）
        也会进入撤销栈，所以日志面板里 Ctrl+Z 也会逐步撤掉这些行；
        撤销到底后再按不会报错，只是内容不再变化。
        想清空撤销历史用 clear_undo_history()。
        """
        self._hotkey_undo(None)

    def redo(self):
        """重做被撤销的编辑（等价于按 Ctrl+Y）"""
        self._hotkey_redo(None)

    def clear_undo_history(self):
        """
        清空撤销历史：之后按 Ctrl+Z 不会再把内容改回去。

        适用场景：程序载入了新内容、重新渲染了整屏之后，
        不希望用户还能撤销到更早的状态时调用。
        说明：set_text / clear 内部已经会自动重置历史，
        这个方法用于"用 append/info 一行行写完之后"手动设一个新的撤销起点。
        """
        self._reset_undo_baseline()

    # ---------------- 字号缩放与布局保护 ----------------
    def _font_metrics(self):
        """返回当前字体的(单个字符宽度, 行高)，单位像素（内部方法）"""
        try:
            font = tkFont.Font(font=self.text.cget("font"))
            return max(1, font.measure("0")), max(1, font.metrics("linespace"))
        except tk.TclError:
            return max(1, self.font.measure("0")), max(1, self.font.metrics("linespace"))

    def _pin_requested_size(self):
        """
        【内部方法】把文本框向上汇报的"请求尺寸"钉死成当前实际像素尺寸。

        为什么需要它：
            Text 控件的请求尺寸是按"字符数 × 当前字体"换算的（默认 80 字符 × 24 行）。
            字号放大后，它换算出的像素请求会成倍膨胀，并沿 pack / grid 向上传播，
            抢走兄弟控件的空间 —— 表现就是分栏比例被破坏、左侧文件栏被挤没、
            滚动条错位。这里把请求尺寸换算成"当前分配到的像素对应的字符数"，
            于是不管字号怎么变，请求出去的像素尺寸都保持不变，布局完全不受影响。
        """
        try:
            px_w = self.text.winfo_width()
            px_h = self.text.winfo_height()
        except tk.TclError:
            return
        if px_w <= 1 or px_h <= 1:
            return  # 尚未完成布局，等下一次 Configure 再钉
        char_w, line_h = self._font_metrics()
        if px_w < 2 * char_w or px_h < 2 * line_h:
            # 尺寸小到连两个字都放不下，说明拿到的是"布局还没走完"的中间值，
            # 不是真实分配尺寸。此时如果照样钉住，面板之后的请求尺寸就永远是
            # 这个 2 像素，pack 也只给它 2 像素，面板会一直缩着长不回来。
            return
        want_w = max(1, px_w // char_w)
        want_h = max(1, px_h // line_h)

        try:
            cur_w = int(self.text.cget("width"))
            cur_h = int(self.text.cget("height"))
        except (tk.TclError, ValueError):
            cur_w = cur_h = -1
        if (want_w, want_h) == (cur_w, cur_h):
            return  # 已经是钉住的状态，避免反复设置引起布局抖动
        self.text.config(width=want_w, height=want_h)

    def _on_text_configure(self, event=None):
        """文本框尺寸变化回调，用于重新钉住请求尺寸（内部方法）"""
        self._pin_requested_size()

    def _on_panel_configure(self, event=None):
        """
        【内部方法】面板尺寸变化回调：把面板对外上报的尺寸钉成当前像素尺寸。

        为什么还需要这一层：
            文本框只能按"字符 × 字体"上报尺寸，换算时不足一行的零头会被丢掉
            （字号 40 时一行就是 60 多像素）。分栏容器拿到各分栏上报的尺寸后，
            会把"容器总高 - 各分栏上报之和"这个零头按权重重新分配，
            于是缩放字号时分栏比例会被轻微改动（实测约 30 像素的重排）。
            而 Frame 的 width/height 单位就是像素，可以做到精确相等：
            各分栏上报之和 == 容器尺寸 时零头为 0，分栏比例就一动不动了。
        """
        px_w = self.winfo_width()
        px_h = self.winfo_height()
        if px_w <= 1 or px_h <= 1:
            return  # 尚未完成布局，等下一次 Configure 再钉
        char_w, line_h = self._font_metrics()
        if px_w < 2 * char_w or px_h < 2 * line_h:
            # 同上：太小的尺寸是布局中间态，钉下去会让面板再也长不回来
            return
        if (px_w, px_h) == (self._pin_w, self._pin_h):
            return  # 已经钉好，避免反复设置引起布局抖动
        self._pin_w, self._pin_h = px_w, px_h
        self.config(width=px_w, height=px_h)
        # 关掉尺寸传递：本面板的大小由父容器决定，不再由内部文本框反推
        self.pack_propagate(False)

    def set_zoom(self, step: int):
        """
        按步长缩放字号（等价于 Ctrl+滚轮滚 step 格）。
        参数：
            step: 正数放大，负数缩小；字号自动限制在 MIN_FONT_SIZE ~ MAX_FONT_SIZE
        说明：
            只改字号和视口位置，不改变面板占用空间，父容器比例不会被打乱。
        """
        self._zoom_font(self.font_size + int(step))

    def _zoom_font(self, font_size: int):
        """【内部方法】应用新字号：只改字号与视口，不改控件占用空间"""
        font_size = max(self.MIN_FONT_SIZE, min(self.MAX_FONT_SIZE, int(font_size)))
        if font_size == self.font_size:
            return
        # 先记住当前视口相对位置，缩放后恢复，保证看到的内容不变
        y_top, _ = self.text.yview()

        self.font_size = font_size
        self.font.config(size=font_size)

        # 关键：字号变了，请求尺寸必须按新字体重新换算并钉住，
        # 否则 Text 会按新字号膨胀出巨大的像素请求，把父容器布局撑坏
        self._pin_requested_size()
        self.text.yview_moveto(y_top)

    def _mousewheel_zoom(self, event):
        """Ctrl+滚轮缩放字号：仅改字号，保留视口，布局不抖动"""
        step = 1 if event.delta > 0 else -1
        self._zoom_font(self.font_size + step)
        return "break"

    # ---------------- 日志文本API ----------------
    def pstr(self, msg: str, cl=True):
        """主线程打印普通字符串，自动换行（使用面板的正文颜色）"""
        self._writeln(f"{msg}\n" if cl else msg, "plain")

    def info(self, msg: str):
        """主线程打印INFO级别日志，自动滚动到底部（使用 info 类别颜色）"""
        self._writeln(f"[INFO] {msg}\n", "info")

    def warn(self, msg: str):
        """主线程打印WARN警告日志，自动滚动到底部（使用 warn 类别颜色，默认醒目黄）"""
        self._writeln(f"[WARN] {msg}\n", "warn")

    def error(self, msg: str):
        """主线程打印ERROR错误日志，自动滚动到底部（使用 error 类别颜色，默认醒目红）"""
        self._writeln(f"[ERROR] {msg}\n", "error")

    def log(self, msg: str, color: Optional[str] = None, prefix: str = ""):
        """
        打印一行文本，并**只给这一行**指定颜色（不动其它日志、也不改面板默认色）。

        这是"临时改一次颜色"的正确做法：不用 set_fg 改整个面板（那样之后写的
        所有内容都会跟着变），而是这一行单独上色。
        参数：
            msg: 文本内容
            color: 颜色名或 #RRGGBB；None 表示用正文色
            prefix: 行首前缀，例如 "[提示] "，默认为空
        示例：
            log.log("文件类型不是 .txt", color="#EE0000", prefix="[错误] ")
            log.log("已加载 120 行", color="#66CCFF", prefix="[提示] ")
        """
        self._writeln(f"{prefix}{msg}\n", "plain", color=color)

    def _writeln(self, text: str, level: str, color: Optional[str] = None):
        """
        【内部方法】写入一行日志：按类别上色，并滚动到底部。
        参数：
            text: 含结尾换行的文本
            level: 类别（info / warn / error / plain）
            color: 直接指定颜色（优先于类别配色）
        """
        self.insert_line(text, level=level, color=color)
        self.text.see(tk.END)
        self.text.update_idletasks()

    def safe_info(self, msg: str):
        """子线程安全版本info，子线程调用无需担心tk报错"""
        safe_call(self.root, self.info, msg)

    def safe_warn(self, msg: str):
        """子线程安全版本warn"""
        safe_call(self.root, self.warn, msg)

    def safe_error(self, msg: str):
        """子线程安全版本error"""
        safe_call(self.root, self.error, msg)

    def safe_log(self, msg: str, color: Optional[str] = None, prefix: str = ""):
        """子线程安全版本log（带颜色的单行日志）"""
        safe_call(self.root, self.log, msg, color, prefix)

    def insert_text(self, content: str):
        """追加文本，不会自动换行，在现有内容末尾添加（跟随正文色）"""
        self.append(content)

    def _hotkey_cut(self, event):
        """Ctrl+X 剪切（仅日志面板可编辑时需要）"""
        self.text.event_generate("<<Cut>>")
        return "break"

    def _hotkey_paste(self, event):
        """Ctrl+V 粘贴（仅日志面板可编辑时需要）"""
        self.text.event_generate("<<Paste>>")
        return "break"

    def _hotkey_save(self, event):
        """Ctrl+S 触发 on_save 回调"""
        if self.on_save is not None:
            self.on_save()
        return "break"

    # ---------------- 只读相关 ----------------
    def set_read_only(self, read_only: bool = True):
        """
        设置面板是否只读，并立即生效。

        只读时（True）：
            用户无法输入、退格删除、粘贴、剪切；
            但依然可以查看、鼠标选中、Ctrl+A 全选、Ctrl+C 复制、滚动浏览。
        只读不影响程序自身：
            set_text / clear / append / info / error 等仍然可以更新内容
            （内部会自动临时解锁、写完再锁上）。
        参数：
            read_only: True=只读；False=恢复可编辑
        示例：
            log = LogPanel(vsplit.bottom, read_only=True)   # 构造时直接只读
            log.set_read_only(False)                        # 临时允许编辑
        """
        self.read_only = bool(read_only)
        if self.read_only:
            # disabled 状态会挡掉用户的一切编辑操作，同时保留选中与复制
            self.text.config(state="disabled")
            self.text.update_idletasks()
        else:
            self.text.config(state="normal")

    def _writable_state(self) -> str:
        """
        【内部方法】准备写入内容：只读面板临时解锁，并返回需要还原的状态。

        同时会在撤销栈里插一个分隔符，把"这次写入"单独划成一步撤销 ——
        分隔符必须在写入**之前**插入：Tk 的 edit_undo 是回退到上一个分隔符处，
        写在后面会把这次写入和下一次写入算成同一步。
        返回 "normal" 表示本来就可写、无需还原；返回 "disabled" 表示
        这次是临时解锁的，写完必须调用 _restore_state 锁回去。
        """
        try:
            self.text.edit_separator()
        except tk.TclError:
            pass  # 控件已销毁或老版本 Tk，忽略
        if not self.read_only:
            return "normal"
        self.text.config(state="normal")
        return "disabled"

    def _restore_state(self, state: str):
        """【内部方法】写入完成后还原控件状态（只读面板重新锁上）"""
        if state == "disabled":
            self.text.config(state="disabled")
            self.text.update_idletasks()  # 立即重绘，避免锁上瞬间出现空白

    def append_line(self, text: str, color: Optional[str] = None):
        """
        在末尾追加一行内容（自动补换行），可指定这一行的颜色。
        参数：
            text: 文本内容，不需要自己带换行
            color: 颜色名或 #RRGGBB；None 表示跟随正文色
        """
        self.append(f"{text}\n", color=color)

    @property
    def native_widget(self):
        """底层原生ScrolledText控件，用来修改字体、颜色等原生属性"""
        return self.text


class FileSelect(tk.Frame):
    """
    文件选择控件：标签 + 输入框 + "选择"按钮
    点击【选择】按钮，弹出系统文件选择对话框，选中文件后触发on_select回调
    参数：
        master: 父容器
        label: 左侧显示的文字标签
        auto_create: 选中的文件不存在时是否自动创建空文件，默认 False 不创建。
                     要创建的文件类型由"用户填入的路径后缀"决定：
                     路径写成 D:\\x\\demo.asm 就创建 demo.asm，写成 demo.txt 就创建 demo.txt。
                     父目录不存在、没有写权限等情况不会报错，路径照常返回，
                     具体原因可以通过 last_error 查看。
    成员：
        .on_select: 回调函数，选中文件后自动调用，传入文件路径字符串
        .last_error: 最近一次自动创建失败的原因（没有失败则为空字符串）
    方法：
        get_path()：获取当前选择的文件路径
        set_path(path)：手动设置文件路径
        ensure_exists(path=None)：按需创建文件（不存在才建），返回文件路径
        ask_file(...)：弹出对话框让用户选文件，并返回文件路径字符串
                       【可以在子线程里安全调用，见下面的说明和示例】
    属性：
        .native_entry：底层原生Entry单行输入框
    """
    def __init__(self, master, label: str, auto_create: bool = False, **kwargs):
        super().__init__(master, **kwargs)
        self.root = self.winfo_toplevel()
        self.on_select: Optional[Callable[[str], Any]] = None
        # 选中的文件不存在时是否自动创建（文件类型由路径后缀决定）
        self.auto_create = bool(auto_create)
        # 最近一次自动创建失败的原因，方便调用方提示用户
        self.last_error = ""

        self.var = tk.StringVar()
        tk.Label(self, text=label).pack(side=tk.LEFT, padx=3)
        self.entry = tk.Entry(self, textvariable=self.var)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)
        tk.Button(self, text="选择", command=self._on_btn).pack(side=tk.LEFT, padx=2)
        # 对话框用的是 tkinter 的 askopenfilename：它只能选"已存在的文件"。
        # 所以绑上"保存文件"对话框，用户可以直接输入新文件名（例如 demo.asm），
        # 这样"自动创建"才有实际用武之地；没开自动创建时保持原来的选择行为。
        self._dialog_func = (filedialog.asksaveasfilename if self.auto_create
                             else filedialog.askopenfilename)

    def _on_btn(self):
        """内部按钮点击事件，用户不要直接调用"""
        path = self._dialog_func(title="选择文件")
        if not path:
            return
        self._accept_path(path)

    def ensure_exists(self, path: Optional[str] = None) -> str:
        """
        确保文件存在：文件不存在时按需创建（默认用输入框里的路径）。

        参数：
            path: 文件路径；None 表示用输入框当前内容
        返回：
            处理后的文件路径字符串；路径为空、已存在、或创建失败时会原样返回路径，
            不抛异常。创建失败的原因记在 self.last_error 里。
        说明：
            创建的是**空文件**；文件类型完全由路径后缀决定（.asm / .txt / …），
            本方法不限制后缀。父目录不存在时不会去创建目录，只会记录错误。
        """
        self.last_error = ""
        target = self.var.get() if path is None else path
        target = (target or "").strip()
        if not target:
            return ""
        try:
            file_path = Path(target)
            if not file_path.exists():
                # 只建文件、不建目录：用户给的目录不对时要让他知道，而不是悄悄造目录
                file_path.touch(exist_ok=True)
        except OSError as exc:
            # 父目录不存在、无写权限、路径非法等：不抛给调用方，只记录原因
            self.last_error = str(exc)
        return target

    def _accept_path(self, path: str, auto_create: Optional[bool] = None) -> str:
        """
        【内部方法】接收一个选中的路径：回填输入框、按需创建文件、触发回调。
        参数：
            path: 对话框返回的文件路径
            auto_create: 是否自动创建文件；None=沿用构造时的设置
        返回：
            处理后的路径（创建失败也照常返回，原因见 self.last_error）
        """
        self.var.set(path)
        if self.auto_create if auto_create is None else auto_create:
            self.ensure_exists(path)
        if self.on_select is not None:
            self.on_select(path)
        return path

    def _default_extension(self, filetypes) -> str:
        """
        【内部方法】从 filetypes 里取出默认后缀（例如 [("汇编", "*.asm")] → ".asm"）。

        作用：用了"保存"对话框时，用户只输入 demo，系统会自动补成 demo.asm，
        这样"文件类型由路径后缀决定"这件事对用户更省事。
        取不到就返回空串（不强制补后缀，用户写什么就是什么）。
        """
        if not filetypes:
            return ""
        try:
            pattern = str(filetypes[0][1])
        except (IndexError, TypeError, KeyError):
            return ""
        for part in pattern.replace(";", " ").split():
            if part.startswith("*.") and len(part) > 2:
                return part[1:]  # "*.asm" -> ".asm"
        return ""

    def ask_file(self, title: str = "选择文件",
                 filetypes=None,
                 initialdir: Optional[str] = None,
                 timeout: Optional[float] = None,
                 auto_create: Optional[bool] = None) -> str:
        """
        【可在子线程安全调用】弹出系统文件选择对话框，返回选中的文件路径。

        参数：
            title: 对话框标题，默认"选择文件"
            filetypes: 文件类型过滤，例如 [("文本文件", "*.txt"), ("所有文件", "*.*")]
            initialdir: 打开时定位到的目录，默认用输入框里当前的目录
            timeout: 等待主线程弹出对话框的秒数；None=一直等（默认）
            auto_create: 选中的文件不存在时是否自动创建空文件。
                         None（默认）=沿用构造 FileSelect 时的设置；
                         True/False=只对本次调用生效。
                         创建的文件类型由"用户填入的路径后缀"决定。
        返回：
            选中的文件路径字符串；用户取消或超时返回 ""（空字符串）

        为什么需要它：
            tkinter 只能在主线程操作界面，子线程直接弹对话框会报错甚至崩溃。
            这个方法内部把对话框投递到主线程执行，子线程**阻塞等待**结果，
            再像普通函数一样把路径返回给你，所以子线程里可以这样写：
                path = self.fileselect.ask_file(title="选择要汇编的文件")
                if path: ...
        调用效果：
            与点击【选择】按钮一致 —— 会把路径填进输入框、按需创建文件、
            并触发 on_select 回调。
        注意：
            子线程调用时会一直等到用户选完（或超时）才返回；
            主线程自己调用时会直接弹出对话框（不会卡死）；
            如果窗口已经关闭、或主线程还没启动消息循环（mainloop 未运行），
            会立即返回 ""。
        """
        result = {"path": "", "done": threading.Event()}
        # 本次调用是否自动创建：没显式指定就用构造时的设置
        want_create = self.auto_create if auto_create is None else bool(auto_create)

        # 窗口已经销毁就直接返回：销毁后 after()/StringVar.set() 不报错但也不生效，
        # 不先拦一下的话，子线程会拿到一个"看起来成功、其实界面已经没了"的路径。
        #
        # winfo_exists() 在两种情况会抛异常，都按"窗口不可用"处理：
        #   TclError    —— 窗口已经销毁；
        #   RuntimeError—— 该查询要注册 Tcl 命令，而主线程还没进 mainloop
        #                  （此时子线程既查不了、也没人执行投递过去的对话框）。
        # 如果这里放着不管，子线程会被异常打挂，这比返回空串糟糕得多。
        try:
            if not self.winfo_exists():
                return ""
        except (tk.TclError, RuntimeError):
            return ""

        def show_dialog() -> str:
            """【在主线程执行】真正弹出对话框，并返回选中的路径（取消为空串）"""
            try:
                # 要自动创建文件时用"保存"对话框：原生"打开"对话框不允许输入
                # 不存在的文件名，用户就没法指定一个新文件去创建
                dialog = (filedialog.asksaveasfilename if want_create
                          else filedialog.askopenfilename)
                path = dialog(
                    title=title,
                    filetypes=filetypes if filetypes is not None else (),
                    initialdir=self._dialog_initialdir(initialdir),
                    defaultextension=self._default_extension(filetypes) if want_create else "",
                )
                if path:
                    # 与点击【选择】按钮保持同样的行为：回填、按需创建、触发回调
                    self._accept_path(path, auto_create=want_create)
                result["path"] = path or ""
            except tk.TclError:
                result["path"] = ""  # 窗口已销毁，按"没选文件"处理
            except Exception:  # noqa: BLE001 - 对话框内部出错也不能把调用方卡死
                result["path"] = ""
            finally:
                result["done"].set()
            return result["path"]

        if threading.current_thread() is threading.main_thread():
            # 本来就是主线程：直接弹对话框就行。
            # 这里绝不能走下面的 after + wait —— 主线程一 wait 就没法处理消息循环，
            # 排好的对话框回调永远不会执行，会直接卡死。
            return show_dialog()

        # 子线程：把对话框投递到主线程执行，本线程阻塞等待结果
        try:
            self.root.after(0, show_dialog)
        except (tk.TclError, RuntimeError):
            # 窗口已销毁，或者主线程没在跑消息循环（mainloop 未启动）：
            # 这两种情况都弹不出对话框，直接按"没选文件"返回，不抛异常给子线程
            return ""

        if not result["done"].wait(timeout):
            return ""  # 等超时：返回空串，调用方按"没选文件"处理即可
        return result["path"]

    def _dialog_initialdir(self, initialdir: Optional[str]):
        """
        【内部方法】决定对话框打开时定位到哪个目录。

        优先用调用方传进来的 initialdir；没传就用输入框里当前文件所在目录；
        都没有就返回 None（交给系统记住上次打开的位置）。
        """
        if initialdir:
            return initialdir
        current = self.var.get().strip()
        if not current:
            return None
        try:
            parent = Path(current).parent
        except (ValueError, OSError):
            return None  # 输入框里的内容不是合法路径，交给系统决定
        # Path("abc.txt").parent 是 "."，这种没有实际意义的目录直接不用
        return str(parent) if str(parent) not in ("", ".") else None

    def get_path(self) -> str:
        """获取当前文件路径字符串"""
        return self.var.get()

    def set_path(self, path: str):
        """手动设置文件路径"""
        self.var.set(path)

    @property
    def native_entry(self):
        """底层原生Entry输入框，用于自定义字体颜色等"""
        return self.entry


class MyButton(tk.Frame):
    """
    按钮控件，适配统一.add()接口
    参数：
        master:父容器
        text:按钮显示文字
        on_click:点击回调函数，无参数
    属性：
        .native_widget：底层原生tk.Button对象
    """
    def __init__(self, master, text: str, on_click=None,** kwargs):
        super().__init__(master, **kwargs)
        self.on_click = on_click
        self.btn = tk.Button(self, text=text, command=self._click)
        self.btn.pack(fill=tk.BOTH, expand=True)

    def _click(self):
        """内部点击事件，用户不要直接调用"""
        if self.on_click is not None:
            self.on_click()

    @property
    def native_widget(self):
        """底层原生Button，可修改颜色、字体等原生属性"""
        return self.btn


class HSplitFrame(tk.Frame):
    """
    水平左右分栏容器，提供 .left / .right 两个子容器
    参数：
        master:父容器
        left_weight:左侧区域拉伸权重，默认1
        right_weight:右侧区域拉伸权重，默认3
        proportional:是否严格按权重比例分配宽度，默认True。
                     True（默认）：左右宽度严格等于权重之比，窗口缩放比例不变，
                     并且两块**无缝拼接**，容器空间被完全用满；
                     False：左侧保持控件自然宽度（适合放文件选择框这类
                     固定宽度控件），窗口变大时多余宽度按权重分给右侧。
        gap:左右两块之间的间隙像素，默认0=无缝拼接。
    属性：
        .left：左侧子容器（_BoxFrame类型，支持.add()）
        .right：右侧子容器（_BoxFrame类型，支持.add()）
    方法：
        set_weights(left_weight, right_weight)：运行时改比例，立即重新布局
    """
    def __init__(self, master, left_weight: int = 1, right_weight: int = 3,
                 proportional: bool = True, gap: int = _DEFAULT_SPLIT_GAP, **kwargs):
        super().__init__(master, **kwargs)
        self.root = self.winfo_toplevel()
        # 关闭尺寸传递：容器的大小由父容器（或主窗口加法）决定
        self.pack_propagate(False)
        self.grid_propagate(False)

        self.gap = max(0, int(gap))
        self._horizontal = True
        self.proportional = proportional
        # 先建单元格（比例模式由分栏决定格子大小，子控件需铺满格子），
        # 再设权重；set_weights 内部会立即布局
        self._left = _BoxFrame(self)
        self._right = _BoxFrame(self)
        # 位置和尺寸全部由 _layout_split 用 place 精确摆放（不用 grid：
        # grid 会先满足控件自然尺寸，权重只对增量生效，比例会被带偏）
        self._cells = (self._left, self._right)
        self.set_weights(left_weight, right_weight)  # 内部会立即布局，需先设好上面的属性
        self._sync_requested_size()  # 上报初始请求尺寸，父容器首次布局才分得到空间
        # 容器尺寸一变就重新切分；单元格内部变化冒泡上来也会走到这里
        self.bind("<Configure>", self._relayout)

    def set_weights(self, left_weight: int, right_weight: int):
        """设置左右权重并立即重新布局"""
        self.left_weight = max(0, left_weight)
        self.right_weight = max(0, right_weight)
        self.weights = (self.left_weight, self.right_weight)
        self._relayout()

    def _relayout(self, event=None):
        """
        【内部方法】重新切分两个单元格（Configure 回调，两种模式统一入口）。

        注意这里有两次布局：
            第 1 次按当前容器尺寸切分 → 控件铺满后，单元格自然尺寸随之变化；
            第 2 次在把新尺寸上报给父容器之后重算一遍，消除"按旧尺寸取整"
            留下的 1 像素偏差，让比例在任何窗口尺寸下都最接近权重之比。
        """
        _layout_split(self, self._cells, self.weights, self._horizontal, self.gap,
                      self.proportional)
        self._sync_requested_size()
        _layout_split(self, self._cells, self.weights, self._horizontal, self.gap,
                      self.proportional)

    def _sync_requested_size(self):
        """
        【内部方法】把本容器的请求尺寸设为"两个单元格自然尺寸之和 + 间隙"。

        为什么要这么做：
            padx/pady 一律为 0、单元格又是用 place 摆的，
            所以容器自身没有任何尺寸来源，不主动上报就只能按 1×1 参与父容器布局，
            被放进主窗口或另一个分栏时会直接塌成一条线。
        """
        w = self._left._natural_size("w") + self._right._natural_size("w") + self.gap
        h = max(self._left._natural_size("h"), self._right._natural_size("h"))
        self.config(width=max(1, w), height=max(1, h))

    @property
    def left(self) -> _BoxFrame:
        return self._left

    @property
    def right(self) -> _BoxFrame:
        return self._right


class VSplitFrame(tk.Frame):
    """
    垂直上下分栏容器，提供 .top / .bottom 两个子容器
    参数：
        master:父容器
        top_weight:上方区域高度权重，默认3
        bottom_weight:下方区域高度权重，默认1
        proportional:是否严格按权重比例分配高度，默认True。
                     True（默认）：上下高度严格等于权重之比（默认3:1），
                     窗口最大化、缩放、字体缩放时比例都保持不变，
                     并且上下两块**无缝拼接**，中间不会留下空隙；
                     False：先满足上下两块的自然高度，剩余空间再按权重分。
        gap:上下两块之间的间隙像素，默认0=无缝拼接。
    属性：
        .top：上方子容器（_BoxFrame类型，支持.add()）
        .bottom：下方子容器（_BoxFrame类型，支持.add()）
    方法：
        set_weights(top_weight, bottom_weight)：运行时改比例，立即重新布局
    """
    def __init__(self, master, top_weight: int = 3, bottom_weight: int = 1,
                 proportional: bool = True, gap: int = _DEFAULT_SPLIT_GAP, **kwargs):
        super().__init__(master, **kwargs)
        self.root = self.winfo_toplevel()
        # 关闭尺寸传递：容器的大小由父容器（或主窗口加法）决定
        self.pack_propagate(False)
        self.grid_propagate(False)

        self.gap = max(0, int(gap))
        self._horizontal = False
        self.proportional = proportional
        # 先建单元格（比例模式由分栏决定格子大小，子控件需铺满格子），
        # 再设权重；set_weights 内部会立即布局
        self._top = _BoxFrame(self)
        self._bottom = _BoxFrame(self)
        # 位置和尺寸全部由 _layout_split 用 place 精确摆放（不用 grid：
        # grid 会先满足控件自然尺寸，权重只对增量生效，比例会被带偏）
        self._cells = (self._top, self._bottom)
        self.set_weights(top_weight, bottom_weight)  # 内部会立即布局，需先设好上面的属性
        self._sync_requested_size()  # 上报初始请求尺寸，父容器首次布局才分得到空间
        # 容器尺寸一变就重新切分，保证任何窗口尺寸下上下比例都严格等于权重之比
        self.bind("<Configure>", self._relayout)

    def set_weights(self, top_weight: int, bottom_weight: int):
        """设置上下权重并立即重新布局"""
        self.top_weight = max(0, top_weight)
        self.bottom_weight = max(0, bottom_weight)
        self.weights = (self.top_weight, self.bottom_weight)
        self._relayout()

    def _relayout(self, event=None):
        """
        【内部方法】重新切分两个单元格（Configure 回调，两种模式统一入口）。

        注意这里有两次布局：
            第 1 次按当前容器尺寸切分 → 控件铺满后，单元格自然尺寸随之变化；
            第 2 次在把新尺寸上报给父容器之后重算一遍，消除"按旧尺寸取整"
            留下的 1 像素偏差，让上下比例在任何窗口尺寸下都最接近权重之比。
        """
        _layout_split(self, self._cells, self.weights, self._horizontal, self.gap,
                      self.proportional)
        self._sync_requested_size()
        _layout_split(self, self._cells, self.weights, self._horizontal, self.gap,
                      self.proportional)

    def _sync_requested_size(self):
        """
        【内部方法】把本容器的请求尺寸设为"两个单元格自然尺寸之和 + 间隙"。

        为什么要这么做：
            padx/pady 一律为 0、单元格又是用 place 摆的，
            所以容器自身没有任何尺寸来源，不主动上报就只能按 1×1 参与父容器布局，
            被放进主窗口或另一个分栏时会直接塌成一条线。
        """
        h = self._top._natural_size("h") + self._bottom._natural_size("h") + self.gap
        w = max(self._top._natural_size("w"), self._bottom._natural_size("w"))
        self.config(width=max(1, w), height=max(1, h))

    @property
    def top(self) -> _BoxFrame:
        return self._top

    @property
    def bottom(self) -> _BoxFrame:
        return self._bottom


class AppWindow:
    """
    顶层主窗口类，程序入口窗口
    参数：
        title:窗口标题
        width:初始宽度
        height:初始高度
        min_w:窗口最小宽度，不能缩得更小
        min_h:窗口最小高度，不能缩得更小
    成员：
        .on_close：关闭窗口回调函数，返回False则阻止窗口关闭
    方法：
        add(widget, expand=False)：向主窗口添加一级控件
        说明：全部控件都是 expand=False 时，第一个控件自动占据全部剩余空间。
              否则主容器只能按请求尺寸摆放，窗口拖大后容器不跟着长大，
              分栏比例看着就会"怪怪的"。
        mainloop()：启动UI消息循环，放在代码最后一行
    """
    def __init__(self, title: str, width: int = 700, height: int = 400, min_w: int = 400, min_h: int = 250):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min_w, min_h)

        self.root.grid_columnconfigure(0, weight=1)
        self._row_idx = 0
        self._first_widget: Optional[tk.Widget] = None  # 第一个一级控件，见 add()
        self.on_close: Optional[Callable[[], bool]] = None
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

    def add(self, widget: tk.Widget, expand: bool = False):
        """
        在主窗口纵向添加一级控件
        :param widget: 控件或者分栏容器
        :param expand: True=纵向拉伸填充；False=高度固定（取自身请求高度）
        """
        if self._first_widget is None:
            # 记住第一个控件：如果后面没有任何控件 expand=True，
            # 就由它独占剩余空间，主容器才不会被"按请求尺寸摆放"困住
            self._first_widget = widget
        weight = 1 if expand else 0
        self.root.grid_rowconfigure(self._row_idx, weight=weight)
        widget.grid(row=self._row_idx, column=0, sticky="nsew", padx=5, pady=5)
        self._row_idx += 1
        self.root.after_idle(self._apply_fill_fallback)

    def _apply_fill_fallback(self):
        """【内部方法】没有任何控件声明 expand=True 时，让第一个控件填满剩余空间"""
        try:
            weights = [int(self.root.grid_rowconfigure(i, "weight"))
                       for i in range(self._row_idx)]
        except tk.TclError:
            return  # 窗口已关闭
        if any(weights):
            return  # 已经有控件负责拉伸，不动用户的意思
        if self._first_widget is not None:
            self.root.grid_rowconfigure(0, weight=1)

    def _handle_close(self):
        """窗口关闭内部回调，用户不要直接调用"""
        if self.on_close is not None:
            ok = self.on_close()
            if not ok:
                return
        self.root.destroy()

    def mainloop(self):
        """启动UI，放在程序末尾"""
        self.root.mainloop()


# ==================== 演示代码（运行本文件直接打开示例窗口） ====================
if __name__ == "__main__":
    import os

    win = AppWindow("MyTkUI Demo", 720, 450, 600, 300)
    # 一级：左右分栏容器
    hsplit = HSplitFrame(win.root)
    win.add(hsplit, expand=True)

    # 左侧面板：文件选择控件
    fs = FileSelect(hsplit.left, label="目标文件：")
    hsplit.left.add(fs)

    # 右侧面板：嵌套上下分栏容器
    vsplit = VSplitFrame(hsplit.right)
    hsplit.right.add(vsplit, expand=True)

    # 上区域：代码编辑器文本面板，初始化设置字体和颜色
    editor = LogPanel(vsplit.top, font_name="Consolas", font_size=11, fg="#EEEEEE", bg="#222222")
    vsplit.top.add(editor, expand=True)
    editor.info("编辑器就绪，Ctrl+S保存，Ctrl+滚轮缩放字体")
    # 绑定Ctrl+S保存回调
    def save_action():
        path = fs.get_path()
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(editor.get_all_text())
            editor.info(f"文件已保存: {path}")
        else:
            editor.warn("未选择保存文件！")
    editor.on_save = save_action

    # 下区域：日志输出面板
    log = LogPanel(vsplit.bottom, font_name="Consolas", font_size=10, fg="black", bg="#f8f8f8")
    vsplit.bottom.add(log, expand=True)
    log.info("日志面板就绪")

    # 文件选中回调函数
    def on_file(path):
        log.info(f"加载文件：{path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                editor.set_text(f.read())
        except Exception as e:
            log.error(f"读取失败：{e}")
    fs.on_select = on_file

    win.mainloop()
