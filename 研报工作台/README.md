# 研报阅读工作台

本地 Web 工作台：分类浏览、全文搜索、内嵌阅读六家机构的研报（Platts / FGE / Energy Aspects / Kpler / JPM / GS），并自动关联 AI 精读总结页。

## 启动

双击 **启动研报工作台.bat** 即可（自动打开浏览器，地址 `http://127.0.0.1:8765`）。
关闭黑窗口即停止服务。

命令行方式：

```bash
cd 研报工作台
"C:/Users/连瑞康/.workbuddy/binaries/python/envs/default/Scripts/python.exe" server.py
```

依赖：仅 Python 标准库即可运行；装了 PyMuPDF（当前 venv 已装）才有 PDF 全文搜索，缺失时自动降级为只搜标题/分类。

## 放入研报

把 PDF 放进 `reports/` 下对应机构的文件夹，回到浏览器点「刷新」即可（切回浏览器窗口也会自动刷新）。

```
reports/
├─ Platts/
│  ├─ Daily/原油 · Daily/汽油柴油 · Daily/石脑油 · Daily/燃料油其它
│  ├─ Weekly/
│  └─ Monthly/
├─ FGE/
├─ Energy Aspects/
│  ├─ Weekly/
│  └─ Monthly/
├─ Kpler/  ├─ JPM/  ├─ Morgan Stanley/  └─ GS/
```

- **文件名建议带日期**：`2026-11-14 标题.pdf`、`20261114_标题.pdf`、`14-Nov-2026 标题.pdf` 均可识别；识别不出就用文件修改时间。
- 其它机构下想再分品种（如 Kpler/Crude、FGE/Products），直接建子文件夹即可，侧栏树会自动出现；Platts 的分类树是固定的。
- 未知的新机构文件夹也会自动出现在侧栏。

## AI 归档 + 精读总结（与 AI 协作约定）

把 PDF 交给 AI 时说一句「**归档到研报工作台并生成总结**」，AI 会：

1. 把 PDF 按机构/分类放入 `reports/` 对应文件夹，命名 `YYYY-MM-DD 标题.pdf`；
2. 用「研报精读总结」流程生成自包含 HTML 总结页；
3. 总结页存到 `summaries/` 下 **与 PDF 同名镜像** 的路径：

```
reports/Platts/Daily/原油/2026-11-14 Platts crude oil daily.pdf
              ↕ 同名镜像（自动发现，无需登记）
summaries/Platts/Daily/原油/2026-11-14 Platts crude oil daily.html
```

工作台里该研报会自动出现「总结」标签和「AI 总结」入口。

**只放总结、不归档原文也可以**：把总结页单独放进 `summaries/<机构>/<分类>/`（命名同样带日期），工作台会显示为「仅总结 · 无PDF」条目，点「总结」直接阅读——适合原文保存在别处、工作台只收精华总结的用法。

## 功能

- **分类树**：左侧机构 → 分类，节点带数量；Platts 固定展示 Daily 四小节 / Weekly / Monthly（空节点也显示）
- **搜索**：搜标题、分类、PDF 全文（PyMuPDF 提取、`.index/` 缓存按 mtime 失效）、AI 总结页文本；命中带片段高亮和来源标记（标题/总结命中/全文命中）
- **日期筛选**：今天 / 近7天 / 近30天 / 自定义起止
- **阅读**：浏览器内嵌 PDF；有总结的研报可在「原文 PDF ↔ AI 总结」间切换
- **已读标记**：读过的标题变灰（存浏览器 localStorage）
- **排序**：日期新→旧 / 旧→新 / 标题

## 常用路径与修改

| 事项 | 位置 |
|---|---|
| 改端口 | `server.py` 顶部 `PORT = 8765` |
| 改机构顺序/Platts 分类 | `server.py` 顶部 `ORGS` / `PLATTS_PRESET` |
| 清空全文缓存 | 删除 `.index/` 文件夹（会自动重建） |

> `.index/` 是全文搜索缓存目录，可随时删除，不影响研报文件。
