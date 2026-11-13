# Reports — 日报 / 周报

个人日报与周报仓库，通过 GitHub Pages 在线浏览。

## 在线阅读

开启 Pages 后访问：<https://lianrkcnd.github.io/reports/>

## 目录结构

```
reports/
├── daily/    ← 日报，命名建议：2026-11-13.html
├── weekly/   ← 周报，命名建议：2026-W46.html
├── push.bat          一键提交并推送所有改动
└── add-report.bat    把一份报告复制进仓库并推送
```

## 日常用法（两种方式）

**方式一：双击 push.bat**
把新报告文件手动放进 `daily/` 或 `weekly/` 文件夹后，双击 `push.bat` 即可上传。

**方式二：命令行**
```bat
add-report.bat "C:\路径\报告.html" daily
add-report.bat "C:\路径\周报.html" weekly
```

## 命名规范

- 日报：`YYYY-MM-DD.html`（例：`2026-11-13.html`）
- 周报：`YYYY-Www.html`（例：`2026-W46.html`）
- 命名规范后，文件在 GitHub 上按日期自然排序，方便查找。
